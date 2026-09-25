"""Bindings pybind11 generes : 'scry gen --pybind'.

Principe : des VUES sur la memoire C++, jamais des copies. Chaque struct
devient un py::class_<T>, chaque variable globale des headers une propriete
du module. On y accede par reference, depuis un interpreteur Python embarque
dans l'application : ecrire un attribut ecrit dans la memoire du programme.
C'est ce qu'il faut a un script qui lit et modifie les interfaces d'un
simulateur dans son propre cycle, sans IPC ni copie.

Le header genere expose scry::bind::register_types, register_globals et
register_all ; scry_module.generated.cpp definit le module embarque avec
register_all. Il inclut abi_checks.generated.h : les bindings ne compilent
que si le layout du modele est celui du compilateur.

Le code C++ des membres est prepare ici, pas dans Jinja : les regles
(bitfields, tableaux, types anonymes, STL, mots-cles Python) rendraient le
template illisible. Le template ne fait qu'assembler.
"""

import keyword
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from scry import model
from scry.codegen import generator
from scry.config import Config, load_config

CHAR_TYPES = ("char", "signed char", "unsigned char")
FLOAT_TYPES = ("float", "double", "long double")


# ---------------------------------------------------------------------------
# Noms
# ---------------------------------------------------------------------------
def _split_top(text: str, sep: str) -> List[str]:
    """Decoupe sur sep hors des chevrons de template."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0 and text.startswith(sep, i):
            parts.append(text[start:i])
            i += len(sep)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


def split_last(qualified: str) -> Tuple[str, str]:
    """'testgen::FlightPlan::Leg' -> ('testgen::FlightPlan', 'Leg').
    Les :: des arguments template ne coupent pas."""
    parts = _split_top(qualified, "::")
    return "::".join(parts[:-1]), parts[-1]


def py_identifier(name: str) -> str:
    """Identifiant Python valide. Un mot-cle prend un '_' final : le membre
    C++ 'from' devient 'from_', convention de pybind11 et de la stdlib."""
    out = re.sub(r"\W", "_", name) or "_"
    if out[0].isdigit():
        out = "_" + out
    if keyword.iskeyword(out):
        out += "_"
    return out


def py_type_name(last: str) -> str:
    """'RingBuffer<testgen::SensorSample, 8>' -> 'RingBuffer_SensorSample_8'."""
    if "<" not in last:
        return py_identifier(last)
    base, args = last.split("<", 1)
    args = args[:args.rfind(">")]
    # Arguments : nom court nettoye, sans le '_' de tete qu'ajoute
    # py_identifier devant un chiffre (8 -> 8, pas _8).
    names = [re.sub(r"\W+", "_", split_last(a.strip())[1]).strip("_")
             for a in _split_top(args, ",")]
    return py_identifier(base.strip()) + "_" + "_".join(n for n in names if n)


def _cstr(text: str) -> str:
    """Litteral C++ d'une ligne : guillemets et antislashs echappes."""
    return " ".join(str(text).split()).replace("\\", "\\\\").replace('"', '\\"')


def _is_std(qualified: str) -> bool:
    return qualified.startswith("std::")


def _is_std_string(qualified: str) -> bool:
    return qualified == "std::string" or qualified.startswith("std::basic_string<char,") \
        or qualified == "std::basic_string<char>"


def _elem_base(elem_type: str) -> str:
    """'double [4]' -> 'double' ; sert aux tableaux multidimensionnels."""
    return re.sub(r"\[\d*\]", "", elem_type or "").strip()


def _scalar_hint(type_name: str, size: Optional[int]) -> str:
    canon = model.canonical_type(type_name, size)
    if canon == "bool":
        return "bool"
    if canon in FLOAT_TYPES:
        return "float"
    return "int"


# ---------------------------------------------------------------------------
# Types et enums a enregistrer
# ---------------------------------------------------------------------------
class BoundType(object):
    def __init__(self, key, cpp, kind, qualified, fields, owner, member, root, index):
        self.key = key                # qualified_type, ou chemin pour un anonyme
        self.cpp = cpp                # expression C++ du type
        self.kind = kind
        self.qualified = qualified    # vide pour un type anonyme
        self.fields = fields
        self.owner = owner            # BoundType proprietaire d'un type anonyme
        self.member = member
        self.root = root              # model.Struct pour une racine
        self.alias = "T%d" % index
        self.var = "c%d" % index
        self.py_name = ""
        self.py_path = ""
        self.scope = "m"
        self.scope_type = None
        self.namespace = ""
        self.lines = []               # type: List[str]
        self.py_fields = []           # type: List[Tuple[str, str]]

    @property
    def level(self) -> int:
        return 0 if self.scope_type is None else self.scope_type.level + 1


class BoundEnum(object):
    def __init__(self, key, items, index):
        self.key = key
        self.cpp = key
        self.items = items            # [(nom, valeur)]
        self.alias = "E%d" % index
        self.py_name = ""
        self.py_path = ""
        self.scope = "m"
        self.namespace = ""


class BoundGlobal(object):
    """Variable globale exposee comme propriete d'un module Python."""

    def __init__(self, var: model.Variable):
        self.var = var
        self.namespace = var.namespace
        self.py_name = py_identifier(var.name)
        self.expr = "::" + var.qualified_name   # :: : jamais resolu dans scry::bind
        self.line = ""                            # appel C++ genere
        self.hint = ""                            # type pour le stub .pyi


class Binder(object):
    """Parcourt le modele et prepare tout ce que le template assemble."""

    def __init__(self, structs: Sequence[model.Struct],
                 variables: Sequence[model.Variable] = ()):
        self.types = []               # type: List[BoundType]
        self.by_key = {}              # type: Dict[str, BoundType]
        self.enums = []               # type: List[BoundEnum]
        self.enum_by_key = {}         # type: Dict[str, BoundEnum]
        self.views = []               # type: List[Tuple[BoundType, str]]
        self._view_keys = set()
        self.globals = [BoundGlobal(v) for v in variables]   # type: List[BoundGlobal]
        for s in structs:
            self._type(s.name, s.name, s.kind, s.name, s.fields, None, None, s)
        for g in self.globals:
            self._discover_global(g)
        self._finalize()

    def _discover_global(self, g: BoundGlobal):
        """Types a enregistrer pour une variable : son type, ses enfants."""
        f = g.var.field
        if f.kind == model.ENUM and f.enum_type:
            self._enum(f)
        if f.kind in model.AGGREGATES:
            q = f.qualified_type
            if q and _is_std(q):
                return
            if q:
                self._type(q, q, f.kind, q, f.children, None, None)
            else:
                # Variable d'un type anonyme : 'struct { int a; } g;'.
                self._type("global:" + g.var.qualified_name, "decltype(%s)" % g.expr,
                           f.kind, "", f.children, None, None)
        elif f.kind == model.ARRAY and f.children:
            elem = f.children[0]
            if elem.qualified_type and not _is_std(elem.qualified_type):
                t = self._type(elem.qualified_type, elem.qualified_type, elem.kind,
                               elem.qualified_type, elem.children, None, None)
            else:
                t = self._type("global:%s[]" % g.var.qualified_name,
                               "std::remove_all_extents_t<decltype(%s)>" % g.expr,
                               elem.kind, "", elem.children, None, None)
            self._view(t)

    # -- decouverte ---------------------------------------------------------
    def _type(self, key, cpp, kind, qualified, fields, owner, member, root=None):
        existing = self.by_key.get(key)
        if existing is not None:
            # Premier passage tronque (profondeur, cycle) : on complete.
            if not existing.fields and fields:
                existing.fields = fields
                self._scan(existing)
            if root is not None:
                existing.root = root
            return existing
        t = BoundType(key, cpp, kind, qualified, fields, owner, member, root, len(self.types))
        self.types.append(t)
        self.by_key[key] = t
        self._scan(t)
        return t

    def _scan(self, t: BoundType):
        for f in t.fields:
            self._discover(t, f)

    def _discover(self, owner: BoundType, f: model.Field):
        if f.is_static:
            return
        if f.kind in model.AGGREGATES and not f.name:
            for child in f.children:            # union ou struct anonyme promue
                self._discover(owner, child)
            return
        if f.kind == model.ENUM and f.enum_type:
            self._enum(f)
        if f.kind in model.AGGREGATES:
            q = f.qualified_type
            if _is_std(q):
                if q.startswith("std::array<"):
                    self._std_array(owner, f)
                return
            if q:
                self._type(q, q, f.kind, q, f.children, None, None)
            else:
                self._type("%s.%s" % (owner.key, f.name),
                           "decltype(%s::%s)" % (owner.alias, f.name),
                           f.kind, "", f.children, owner, f.name)
        elif f.kind == model.ARRAY and f.children:
            elem = f.children[0]
            self._view(self._element(owner, f, elem,
                                     "std::remove_all_extents_t<decltype(%s::%s)>"
                                     % (owner.alias, f.name)))

    def _element(self, owner, f, elem, anon_cpp):
        if elem.qualified_type and not _is_std(elem.qualified_type):
            q = elem.qualified_type
            return self._type(q, q, elem.kind, q, elem.children, None, None)
        return self._type("%s.%s[]" % (owner.key, f.name), anon_cpp, elem.kind, "",
                          elem.children, owner, f.name + "_item")

    def _std_array(self, owner, f):
        # MSVC : std::array<T, N> expose un membre _Elems de type T[N].
        inner = f.children[0] if f.children else None
        elem = inner.children[0] if inner is not None and inner.children else None
        if elem is None or elem.kind not in model.AGGREGATES:
            return
        self._view(self._element(owner, f, elem,
                                 "decltype(%s::%s)::value_type" % (owner.alias, f.name)))

    def _enum(self, f: model.Field):
        if f.enum_type in self.enum_by_key:
            return
        items = f.enum_items or [(n, i) for i, n in enumerate(f.enum_values)]
        e = BoundEnum(f.enum_type, items, len(self.enums))
        self.enums.append(e)
        self.enum_by_key[e.key] = e

    def _view(self, t: BoundType):
        if t.key not in self._view_keys:
            self._view_keys.add(t.key)
            self.views.append((t, ""))

    # -- noms, portees, membres ---------------------------------------------
    def _finalize(self):
        for t in self.types:
            if t.owner is not None:
                t.scope_type = t.owner
                t.py_name = py_identifier(t.member) + "_t"
            elif t.key.startswith("global:"):
                # Type anonyme d'une variable globale : nomme d'apres elle.
                qualified = t.key[len("global:"):].rstrip("[]")
                t.namespace, last = split_last(qualified)
                t.py_name = py_identifier(last) + ("_item_t" if t.key.endswith("[]") else "_t")
            else:
                parent, last = split_last(t.qualified)
                t.py_name = py_type_name(last)
                scope = self.by_key.get(parent) if parent else None
                if scope is not None and scope is not t:
                    t.scope_type = scope
                else:
                    t.namespace = parent
        for e in self.enums:
            parent, last = split_last(e.key)
            e.py_name = py_identifier(last)
            scope = self.by_key.get(parent)
            if scope is not None:
                e.scope = scope.var
                e._scope_type = scope
            else:
                e.namespace = parent
                e._scope_type = None

        self.namespaces = self._namespaces()
        ns_var = dict((n["path"], n["var"]) for n in self.namespaces)
        ns_py = dict((n["path"], n["py"]) for n in self.namespaces)

        for t in sorted(self.types, key=lambda x: x.level):
            if t.scope_type is not None:
                t.scope = t.scope_type.var
                t.py_path = "%s.%s" % (t.scope_type.py_path, t.py_name)
            else:
                t.scope = ns_var.get(t.namespace, "m")
                prefix = ns_py.get(t.namespace, "")
                t.py_path = "%s.%s" % (prefix, t.py_name) if prefix else t.py_name
        for e in self.enums:
            if e._scope_type is not None:
                e.py_path = "%s.%s" % (e._scope_type.py_path, e.py_name)
            else:
                e.scope = ns_var.get(e.namespace, "m")
                prefix = ns_py.get(e.namespace, "")
                e.py_path = "%s.%s" % (prefix, e.py_name) if prefix else e.py_name

        used = set()
        views = []
        for t, _ in self.views:
            name = "_ArrayView_%s" % t.py_path.replace(".", "_")
            while name in used:
                name += "_"
            used.add(name)
            views.append((t, name))
        self.views = views

        for t in self.types:
            self._bind_fields(t, t.fields, flattened=False)
            self._services(t)
        for g in self.globals:
            g.line, g.hint = self._global(g)
            g.module = ns_py.get(g.namespace, "")

    def _namespaces(self) -> List[Dict[str, str]]:
        paths = set()
        for item in list(self.types) + list(self.enums) + list(self.globals):
            ns = item.namespace
            while ns:
                paths.add(ns)
                ns = split_last(ns)[0]
        out = []
        for path in sorted(paths, key=lambda p: (p.count("::"), p)):
            parent, last = split_last(path)
            out.append({
                "path": path,
                "var": "m_" + "_".join(py_identifier(p) for p in path.split("::")),
                "parent": ("m_" + "_".join(py_identifier(p) for p in parent.split("::"))
                           if parent else "m"),
                "name": py_identifier(last),
                "py": ".".join(py_identifier(p) for p in path.split("::")),
            })
        return out

    def _global(self, g: BoundGlobal) -> Tuple[str, str]:
        """(appel C++, indication de type) pour exposer une variable globale.

        Toutes passent par detail::Globals, qui en fait des proprietes du
        module : lire sut.g_temps lit la variable, ecrire sut.g_temps = 3.0
        l'ecrit, sans copie ni cache. Les agregats sont rendus par reference :
        sut.g_etat.mode = 1 ecrit dans g_etat.
        """
        f, name = g.var.field, g.py_name
        ref = "[]() -> auto& { return %s; }" % g.expr
        call = 'globals.%s("%s", "%s", %s);'
        ns = g.namespace

        doc = getattr(f, "doc", "")

        def line(method):
            text = call % (method, ns, name, ref)
            if doc:
                text = text[:-2] + ', "%s");' % _cstr(doc)
            return text

        if f.kind in (model.FUNDAMENTAL, model.ENUM):
            hint = (self.enum_by_key[f.enum_type].py_path
                    if f.kind == model.ENUM and f.enum_type in self.enum_by_key
                    else _scalar_hint(f.type_name, f.size))
            return line("value"), hint
        if f.kind == model.POINTER:
            target = self.by_key.get(f.qualified_type) if f.qualified_type else None
            if target is not None and target.fields:
                # Pointeur vers une classe decrite : vue typee sur l'objet
                # pointe, None si nul. Relu a chaque acces.
                return line("pointee"), "Optional[%s]" % target.py_path
            return line("address"), "int"
        if f.kind == model.ARRAY:
            if f.children:
                elem = f.children[0]
                key = (elem.qualified_type
                       if elem.qualified_type and not _is_std(elem.qualified_type)
                       else "global:%s[]" % g.var.qualified_name)
                return line("view"), "ArrayView[%s]" % self._hint_for_type(key)
            base = _elem_base(f.elem_type)
            multi = "[" in (f.elem_type or "")
            elem_size = (f.size // f.array_len) if (f.size and f.array_len and not multi) else None
            canon = model.canonical_type(base, elem_size)
            if canon in CHAR_TYPES and not multi:
                return line("text"), "str"
            if canon in model.PRINTF_FORMATS:
                return line("numeric"), "numpy.ndarray"
            return "// %s : tableau de %s non gere" % (g.var.qualified_name, f.elem_type), ""
        if f.kind in model.AGGREGATES:
            q = f.qualified_type
            if _is_std_string(q):
                return line("value"), "str"
            if q.startswith("std::array<"):
                return "// %s : std::array global non gere" % g.var.qualified_name, ""
            if _is_std(q):
                return ("// %s : %s non liee (STL, pas un POD)"
                        % (g.var.qualified_name, q.split("<")[0])), ""
            key = q or "global:" + g.var.qualified_name
            return line("object"), self._hint_for_type(key)
        return "// %s : type non gere (%s)" % (g.var.qualified_name, f.type_name), ""

    def _hint_for_type(self, key: str) -> str:
        t = self.by_key.get(key)
        return t.py_path if t is not None else "object"

    def _bind_fields(self, t: BoundType, fields, flattened: bool):
        O, c = t.alias, t.var
        for f in fields:
            if f.is_static:
                t.lines.append("// %s : membre statique, hors instance" % f.name)
                continue
            if getattr(f, "access", "public") != "public":
                # Nommer un membre prive hors de la classe ne compile pas. Il
                # reste lisible par offset (scry watch, IHM), pas par nom.
                t.lines.append("// %s : membre %s, non expose"
                               % (f.name or f.type_name, f.access))
                continue
            if f.kind in model.AGGREGATES and not f.name:
                # Struct ou union anonyme, ou classe de base : ses membres
                # s'atteignent par le nom depuis la classe englobante.
                self._bind_fields(t, f.children, flattened=True)
                continue
            name, py = f.name, py_identifier(f.name)
            line, hint = self._member(t, f, O, c, name, py, flattened)
            if line is None:
                t.lines.append("// %s : %s" % (name, hint))
                continue
            t.lines.append(line)
            t.py_fields.append((py, hint))
            if getattr(f, "doc", ""):
                # Commentaire du header : docstring de la propriete, help() le montre.
                t.lines.append('detail::doc(%s, "%s", "%s");' % (c, py, _cstr(f.doc)))

    def _member(self, t, f, O, c, name, py, flattened):
        """(ligne C++, indication de type Python), ou (None, raison)."""
        scalar_prop = ('%s.def_property("%s", [](const %s& o) { return o.%s; }, '
                       '[](%s& o, decltype(%s::%s) v) { o.%s = v; });'
                       % (c, py, O, name, O, O, name, name))
        if f.is_bitfield:
            return scalar_prop, _scalar_hint(f.type_name, f.size)
        if f.kind in (model.FUNDAMENTAL, model.ENUM):
            hint = (self.enum_by_key[f.enum_type].py_path
                    if f.kind == model.ENUM and f.enum_type in self.enum_by_key
                    else _scalar_hint(f.type_name, f.size))
            if flattened:
                return scalar_prop, hint
            return 'detail::field(%s, "%s", &%s::%s);' % (c, py, O, name), hint
        if f.kind == model.POINTER:
            return ('%s.def_property_readonly("%s", [](const %s& o) { return '
                    'reinterpret_cast<std::uintptr_t>(o.%s); });' % (c, py, O, name), "int")
        if f.kind == model.ARRAY:
            return self._array(t, f, O, c, name, py)
        if f.kind in model.AGGREGATES:
            q = f.qualified_type
            if _is_std_string(q):
                return 'detail::field(%s, "%s", &%s::%s);' % (c, py, O, name), "str"
            if q.startswith("std::array<"):
                return self._std_array_member(f, O, c, name, py)
            if _is_std(q):
                return None, "%s non liee (STL, pas un POD)" % q.split("<")[0]
            key = q or "%s.%s" % (t.key, name)
            if flattened:
                return ('%s.def_property_readonly("%s", py::cpp_function([](%s& o) -> auto& '
                        '{ return o.%s; }, py::return_value_policy::reference_internal));'
                        % (c, py, O, name), self._hint_for_type(key))
            return 'detail::field(%s, "%s", &%s::%s);' % (c, py, O, name), \
                self._hint_for_type(key)
        return None, "type non gere (%s)" % f.type_name

    def _array(self, t, f, O, c, name, py):
        if f.children:
            elem = f.children[0]
            key = (elem.qualified_type if elem.qualified_type and not _is_std(elem.qualified_type)
                   else "%s.%s[]" % (t.key, name))
            return ('%s.def_property_readonly("%s", py::cpp_function([](%s& o) { return '
                    'detail::make_view(o.%s); }, py::keep_alive<0, 1>()));' % (c, py, O, name),
                    "ArrayView[%s]" % self._hint_for_type(key))
        base = _elem_base(f.elem_type)
        multi = "[" in (f.elem_type or "")
        elem_size = (f.size // f.array_len) if (f.size and f.array_len and not multi) else None
        canon = model.canonical_type(base, elem_size)
        if canon in CHAR_TYPES and not multi:
            return ('%s.def_property("%s", [](const %s& o) { return detail::char_get(o.%s); }, '
                    '[](%s& o, const std::string& s) { detail::char_set(o.%s, s, "%s"); });'
                    % (c, py, O, name, O, name, name), "str")
        if canon in model.PRINTF_FORMATS:
            return ('%s.def_property("%s", [](py::object self) { return detail::numeric_view('
                    'self, self.cast<%s&>().%s); }, [](%s& o, py::object v) { '
                    'detail::numeric_assign(o.%s, v); });' % (c, py, O, name, O, name),
                    "numpy.ndarray")
        return None, "tableau de %s non gere" % (f.elem_type or "?")

    def _std_array_member(self, f, O, c, name, py):
        inner = f.children[0] if f.children else None
        if inner is not None and inner.children:
            elem = inner.children[0]
            key = elem.qualified_type if elem.qualified_type else ""
            return ('%s.def_property_readonly("%s", py::cpp_function([](%s& o) { return '
                    'detail::make_view(o.%s); }, py::keep_alive<0, 1>()));' % (c, py, O, name),
                    "ArrayView[%s]" % self._hint_for_type(key))
        if inner is not None:
            base = _elem_base(inner.elem_type)
            if model.canonical_type(base) in model.PRINTF_FORMATS and base not in CHAR_TYPES:
                return ('%s.def_property("%s", [](py::object self) { return detail::numeric_view('
                        'self, self.cast<%s&>().%s); }, [](%s& o, py::object v) { '
                        'detail::numeric_assign(o.%s, v); });' % (c, py, O, name, O, name),
                        "numpy.ndarray")
        return None, "std::array non gere"

    def _services(self, t: BoundType):
        """Dict de layout, liste des champs et services communs de la classe."""
        lines = ["{", "    py::dict layout;",
                 '    layout["type"] = "%s";' % (t.qualified or t.cpp).replace('"', '\\"'),
                 "    layout[\"sizeof\"] = sizeof(%s);" % t.alias,
                 "    layout[\"alignof\"] = alignof(%s);" % t.alias,
                 "    py::dict offsets;"]
        offsets = self._offsets(t.fields)
        for py, offset in offsets:
            lines.append('    offsets["%s"] = %d;' % (py, offset))
        lines.append('    layout["offsets"] = offsets;')
        if t.root is not None:
            lines.append('    layout["layout_hash"] = py::int_(0x%016Xull);' % t.root.layout_hash)
        if t.root is not None and getattr(t.root, "doc", ""):
            lines.append('    %s.attr("__doc__") = "%s";' % (t.var, _cstr(t.root.doc)))
        fields = ", ".join('"%s"' % py for py, _ in t.py_fields)
        lines.append('    detail::services<%s>(%s, "%s", py::make_tuple(%s), layout);'
                     % (t.alias, t.var, t.py_path, fields))
        lines.append("}")
        t.lines.extend(lines)

    def _offsets(self, fields) -> List[Tuple[str, int]]:
        out = []
        for f in fields:
            if f.is_static or getattr(f, "access", "public") != "public":
                continue
            if f.kind in model.AGGREGATES and not f.name:
                out.extend((py, f.offset + off) for py, off in self._offsets(f.children))
                continue
            out.append((py_identifier(f.name), f.offset))
        return out

    # -- sorties -------------------------------------------------------------
    def classes_by_level(self) -> List[BoundType]:
        return sorted(self.types, key=lambda t: t.level)

    def root_hashes(self) -> List[Tuple[str, str]]:
        return [(t.key, "0x%016Xull" % t.root.layout_hash) for t in self.types
                if t.root is not None]


# ---------------------------------------------------------------------------
# Stub .pyi
# ---------------------------------------------------------------------------
_STUB_HEADER = '''"""Stub genere par Scry pour l'autocompletion. Ne pas editer a la main.

Les classes sont des VUES sur la memoire C++ : ecrire un attribut ecrit dans
le programme. Les namespaces C++ sont des sous-modules, representes ici par
des classes.
"""
from typing import Any, Dict, Generic, Iterator, Optional, TypeVar

import numpy

_T = TypeVar("_T")


class ArrayView(Generic[_T]):
    """Tableau de structures, element par reference."""
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> _T: ...
    def __setitem__(self, index: int, value: _T) -> None: ...
    def __iter__(self) -> Iterator[_T]: ...
'''


def render_stub(binder: Binder, globals_: Sequence[Tuple[str, str]] = ()) -> str:
    children = {}   # portee (var ou chemin de namespace) -> [entrees]

    def add(scope_key, entry):
        children.setdefault(scope_key, []).append(entry)

    for ns in binder.namespaces:
        add(("ns", split_last(ns["path"])[0]), ("ns", ns))
    for t in binder.types:
        key = ("type", t.scope_type.key) if t.scope_type is not None else ("ns", t.namespace)
        add(key, ("type", t))
    for e in binder.enums:
        scope = getattr(e, "_scope_type", None)
        key = ("type", scope.key) if scope is not None else ("ns", e.namespace)
        add(key, ("enum", e))
    for g in binder.globals:
        if g.hint:
            add(("ns", g.namespace), ("global", g))

    out = [_STUB_HEADER]

    def emit(scope_key, indent):
        pad = "    " * indent
        for kind, item in children.get(scope_key, []):
            out.append("")
            if kind == "global":
                note = "  # const" if item.var.is_const else ""
                out.append('%s%s: "%s"%s' % (pad, item.py_name, item.hint, note))
            elif kind == "ns":
                out.append("%sclass %s:  # namespace %s" % (pad, item["name"], item["path"]))
                before = len(out)
                emit(("ns", item["path"]), indent + 1)
                if len(out) == before:
                    out.append("%s    ..." % pad)
            elif kind == "enum":
                out.append("%sclass %s:  # enum %s" % (pad, item.py_name, item.key))
                for name, value in item.items:
                    out.append('%s    %s: "%s"  # = %d' % (pad, py_identifier(name),
                                                          item.py_path, value))
                out.append("%s    name: str" % pad)
                out.append("%s    value: int" % pad)
            else:
                t = item
                out.append("%sclass %s:  # %s" % (pad, t.py_name, t.qualified or t.cpp))
                emit(("type", t.key), indent + 1)
                for py, hint in t.py_fields:
                    out.append('%s    %s: "%s"' % (pad, py, hint))
                out.append("%s    __scry_fields__: tuple" % pad)
                out.append("%s    __scry_layout__: Dict[str, Any]" % pad)
                out.append("%s    def to_dict(self) -> Dict[str, Any]: ..." % pad)
                out.append("%s    @staticmethod" % pad)
                out.append('%s    def from_address(address: int) -> "%s": ...' % (pad, t.py_path))

    emit(("ns", ""), 0)
    if globals_:
        out.append("")
        out.append("# Instances exposees a la main par l'application ([pybind] globals).")
        for name, cpp in globals_:
            t = binder.by_key.get(cpp)
            out.append('%s: "%s"' % (py_identifier(name), t.py_path if t else "Any"))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Fragment CMake
# ---------------------------------------------------------------------------
def render_cmake(header: str, include_dirs: Sequence[str],
                 module_source: str = "scry_module.generated.cpp") -> str:
    dirs = "\n".join('    "%s"' % d.replace("\\", "/") for d in include_dirs)
    return """# =============================================================================
#  Genere par Scry (scry gen --pybind). Ne pas editer a la main.
#
#  Dans le CMakeLists de l'application :
#
#    execute_process(COMMAND python -m pybind11 --cmakedir
#                    OUTPUT_VARIABLE pybind11_DIR OUTPUT_STRIP_TRAILING_WHITESPACE)
#    find_package(pybind11 CONFIG REQUIRED)
#    include(<dossier Generated>/scry_pybind.cmake)
#
#    # interpreteur embarque dans l'application, module genere compris :
#    scry_pybind_embed(mon_app)
# =============================================================================

set(SCRY_GENERATED_DIR "${CMAKE_CURRENT_LIST_DIR}")
set(SCRY_PYBIND_HEADER "${CMAKE_CURRENT_LIST_DIR}/%s")
set(SCRY_PYBIND_MODULE_SOURCE "${CMAKE_CURRENT_LIST_DIR}/%s")
set(SCRY_SOURCE_INCLUDE_DIRS
%s
)

# Includes seuls : pour qui ecrit son propre module avec register_all.
function(scry_pybind_setup target)
    target_include_directories(${target} PRIVATE ${SCRY_GENERATED_DIR} ${SCRY_SOURCE_INCLUDE_DIRS})
    target_compile_features(${target} PRIVATE cxx_std_17)
endfunction()

# Tout : includes, module embarque genere, interpreteur Python.
function(scry_pybind_embed target)
    scry_pybind_setup(${target})
    target_sources(${target} PRIVATE ${SCRY_PYBIND_MODULE_SOURCE})
    target_link_libraries(${target} PRIVATE pybind11::embed)
endfunction()
""" % (header, module_source, dirs)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def header_name(cfg: Config) -> str:
    return cfg.get("pybind", "header", "scry_pybind.generated.h")


def module_name(cfg: Config) -> str:
    return cfg.get("pybind", "module", "sut")


def stub_name(cfg: Config) -> str:
    return cfg.get("pybind", "stub", module_name(cfg) + ".pyi")


def cmake_name(cfg: Config) -> str:
    return cfg.get("pybind", "cmake", "scry_pybind.cmake")


def module_source_name(cfg: Config) -> str:
    return cfg.get("pybind", "module_source", "scry_module.generated.cpp")


def select_variables(variables: Sequence[model.Variable], cfg: Config
                     ) -> List[model.Variable]:
    """[pybind] expose et hide : motifs glob sur le nom qualifie.

    expose vide ou absent : tout. hide l'emporte sur expose.
    """
    import fnmatch
    expose = cfg.get_list("pybind", "expose") or ["*"]
    hide = cfg.get_list("pybind", "hide")
    return [v for v in variables
            if any(fnmatch.fnmatchcase(v.qualified_name, p) for p in expose)
            and not any(fnmatch.fnmatchcase(v.qualified_name, p) for p in hide)]


def render_module(cfg: Config) -> str:
    return """// =============================================================================
//  Genere par Scry (scry gen --pybind). Ne pas editer a la main.
//
//  Module Python embarque '%(module)s' : tous les types et toutes les
//  variables globales des headers, par reference. A compiler dans
//  l'application, avec pybind11::embed. Un script embarque fait alors :
//
//      import %(module)s
//      %(module)s.<namespace>.<variable>.<membre> = 3.0   # ecrit en place
// =============================================================================
#include "%(header)s"

#include <pybind11/embed.h>

PYBIND11_EMBEDDED_MODULE(%(module)s, m)
{
    %(ns)s::bind::register_all(m);
}
""" % {"module": module_name(cfg), "header": header_name(cfg), "ns": cfg.cpp_namespace}


def stub_globals(cfg: Config) -> List[Tuple[str, str]]:
    """[pybind] globals = inputs: testgen::SensorSample; outputs: ..."""
    out = []
    for entry in cfg.get_list("pybind", "globals"):
        name, sep, cpp = entry.partition(":")
        if sep and name.strip():
            out.append((name.strip(), cpp.strip()))
    return out


def build_context(structs: Sequence[model.Struct], cfg: Config, header=None,
                  variables: Sequence[model.Variable] = ()) -> Dict:
    selected = select_variables(variables, cfg)
    binder = Binder(structs, selected)
    # Headers des structures, plus ceux qui ne declarent que des variables.
    sources = generator.source_headers(list(structs), cfg, header)
    for v in selected:
        name = os.path.basename(v.header) if v.header else ""
        if name and name not in sources:
            sources.append(name)
    return {
        "binder": binder,
        "namespace": cfg.cpp_namespace,
        "source_headers": sources,
        "emit_abi_checks": cfg.emit_abi_checks,
        "abi_header": cfg.abi_header,
        "compiler": cfg.compiler,
        "arch": cfg.arch,
        "std": cfg.std,
        "types": binder.types,
        "classes": binder.classes_by_level(),
        "enums": [
            {"alias": e.alias, "cpp": e.cpp, "scope": e.scope, "py_name": e.py_name,
             "values": [(py_identifier(n), n) for n, _ in e.items]}
            for e in binder.enums],
        "namespaces": binder.namespaces,
        "views": [{"alias": t.alias, "name": name} for t, name in binder.views],
        "hashes": binder.root_hashes(),
        "globals": binder.globals,
    }


def render(structs: Sequence[model.Struct], cfg: Optional[Config] = None, header=None,
           variables: Sequence[model.Variable] = ()) -> str:
    cfg = cfg or load_config()
    return generator.environment().get_template("pybind.h.j2").render(
        **build_context(structs, cfg, header, variables))


def generate(structs: Sequence[model.Struct], cfg: Optional[Config] = None,
             header=None, variables: Sequence[model.Variable] = ()) -> List[str]:
    """Ecrit le header de bindings, le module embarque, le stub .pyi et le
    fragment CMake."""
    cfg = cfg or load_config()
    structs = list(structs)
    written = []
    if cfg.emit_abi_checks:
        written.append(generator.generate_abi(structs, cfg, header=header))
    context = build_context(structs, cfg, header, variables)
    text = generator.environment().get_template("pybind.h.j2").render(**context)
    written.append(generator._write(cfg, header_name(cfg), text))
    written.append(generator._write(cfg, module_source_name(cfg), render_module(cfg)))
    written.append(generator._write(cfg, stub_name(cfg),
                                    render_stub(context["binder"], stub_globals(cfg))))
    dirs = []
    for origin in [s.header for s in structs] + [v.header for v in variables]:
        d = os.path.dirname(os.path.abspath(origin)) if origin else ""
        if d and d not in dirs:
            dirs.append(d)
    dirs += [d for d in cfg.include_paths if d not in dirs]
    written.append(generator._write(cfg, cmake_name(cfg),
                                    render_cmake(header_name(cfg), dirs, module_source_name(cfg))))
    return written
