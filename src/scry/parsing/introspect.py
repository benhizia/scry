"""Extraction du modele a partir d'un header C++, via pygccxml et castxml.

Tout le savoir sur les pieges de pygccxml est concentre ici. Le reste du projet
ne voit que src.scry.model.

Pieges traites, chacun rencontre pour de vrai :

  * class_t n'a pas de decl_type. Seuls variable_t et typedef_t en ont. Une
    struct imbriquee apparait dans la liste des membres au meme titre qu'un
    champ, d'ou l'AttributeError classique.
  * variables() est RECURSIF par defaut et remonte les membres des types
    imbriques melanges a ceux du parent. Il faut recursive=False.
  * byte_offset et byte_size sont des flottants. Pour un champ de bits,
    l'offset est fractionnaire : 392.125 signifie octet 392, bit 1.
  * Les membres statiques ont un byte_offset de 0.0 qui ne veut rien dire.
  * Une struct ou union anonyme a un name vide, et son decl_string vaut le nom
    de la classe englobante, ce qui est trompeur. Il faut passer par la
    declaration et non par la chaine de type.
  * src.scry.introspect(header_file=...) est recursif et remonte aussi les types imbriques
    et anonymes. Pour une liste de racines, filtrer sur parent == namespace.
  * Le filtre header_file compare des chaines. Sur Windows, casse et
    separateurs different, d'ou des listes vides sans erreur. On compare des
    chemins normalises.
  * Un type incomplet, pointe mais jamais defini, donne un class_declaration_t
    sans byte_size.
  * Les templates n'existent dans l'AST que s'ils sont instancies.
  * Les structures auto-referencantes bouclent sans garde-fou.
"""

import os
from typing import Dict, List, Optional, Tuple

from pygccxml import declarations, parser, utils

from scry import model
from scry.config import Config, load_config


class IntrospectionError(RuntimeError):
    pass


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _int_or_none(value) -> Optional[int]:
    """byte_size et byte_offset sont des flottants chez pygccxml."""
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


class Introspector(object):
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or load_config()
        self._xml_config = None

    # -- configuration castxml ---------------------------------------------
    def xml_config(self):
        if self._xml_config is not None:
            return self._xml_config

        cflags = ["-std=%s" % self.cfg.std]
        if self.cfg.extra_cflags:
            cflags.append(self.cfg.extra_cflags)

        common = dict(
            xml_generator="castxml",
            include_paths=list(self.cfg.include_paths),
            define_symbols=list(self.cfg.defines),
            cflags=" ".join(cflags),
        )

        if self.cfg.compiler == "msvc":
            from scry.parsing.msvc_env import build_castxml_config
            self._xml_config = build_castxml_config(self.cfg, **common)
        else:
            path = str(self.cfg.castxml_path) if self.cfg.castxml_path else None
            if path is None:
                path, _ = utils.find_xml_generator()
            self._xml_config = parser.xml_generator_configuration_t(
                xml_generator_path=path,
                compiler=self.cfg.compiler,
                **common
            )
        return self._xml_config

    # -- parsing ------------------------------------------------------------
    def parse(self, header=None) -> List[model.Struct]:
        header = str(header or self.cfg.header or "")
        if not header:
            raise IntrospectionError("Aucun header : renseigne [paths] header dans scry.ini")
        full = os.path.abspath(header)
        if not os.path.isfile(full):
            raise IntrospectionError("Header introuvable : %s" % full)

        cache = None
        cache_file = self.cfg.cache_file
        if cache_file:
            os.makedirs(os.path.dirname(str(cache_file)), exist_ok=True)
            cache = parser.file_cache_t(str(cache_file))

        decls = parser.parse([full], self.xml_config(), cache=cache)
        global_ns = declarations.get_global_namespace(decls)

        roots = self._root_classes(global_ns, full)
        return [self.build_struct(cls) for cls in roots]

    def _root_classes(self, global_ns, header_full: str):
        """Classes definies dans le header, au premier niveau seulement."""
        target = _norm(header_full)
        out = []
        for cls in global_ns.classes(allow_empty=True):
            loc = getattr(cls, "location", None)
            if loc is None or _norm(loc.file_name) != target:
                continue
            # Ecarter les types imbriques et anonymes : ce sont des enfants,
            # ils seront visites lors de la descente dans leur parent.
            if not isinstance(cls.parent, declarations.namespace_t):
                continue
            if not cls.name:
                continue
            out.append(cls)
        out.sort(key=lambda c: c.name)
        return out

    # -- construction du modele ---------------------------------------------
    def build_struct(self, cls) -> model.Struct:
        struct = model.Struct(
            name=cls.name,
            kind=str(cls.class_type),
            size=_int_or_none(getattr(cls, "byte_size", None)),
            align=_int_or_none(getattr(cls, "byte_align", None)),
            header=getattr(getattr(cls, "location", None), "file_name", ""),
            is_polymorphic=self._is_polymorphic(cls),
        )
        struct.fields = self._members(cls, base_offset=0, path="obj",
                                     depth=0, seen=(self._key(cls),))
        return struct

    def _is_polymorphic(self, cls) -> bool:
        for m in cls.declarations:
            if isinstance(m, declarations.member_function_t) and getattr(m, "virtuality", None):
                if str(m.virtuality) != "not virtual":
                    return True
        return False

    def _key(self, decl) -> str:
        # decl_string d'un type anonyme renvoie le nom du parent : deux types
        # anonymes distincts partageraient la meme cle et le garde-fou
        # anti-cycle les couperait a tort.
        if not getattr(decl, "name", ""):
            return "anonyme@%d" % id(decl)
        try:
            return decl.decl_string
        except Exception:
            return "%s@%d" % (decl.name, id(decl))

    def _members(self, cls, base_offset: int, path: str, depth: int, seen: Tuple[str, ...]) -> List[model.Field]:
        fields = []
        try:
            variables = cls.variables(allow_empty=True, recursive=False)
        except Exception:
            return fields

        for var in variables:
            is_static = bool(getattr(var.type_qualifiers, "has_static", False))
            if is_static and not self.cfg.include_static:
                continue
            if not self.cfg.include_non_public:
                access = getattr(var, "access_type", None)
                if access is not None and str(access) != "public":
                    continue
            fields.append(self._build_field(var, base_offset, path, depth, seen, is_static))
        return fields

    def _build_field(self, var, base_offset: int, path: str, depth: int,
                     seen: Tuple[str, ...], is_static: bool) -> model.Field:
        raw_offset = 0.0 if is_static else float(getattr(var, "byte_offset", 0.0) or 0.0)
        byte_offset = int(raw_offset)
        bit_width = getattr(var, "bits", None)
        bit_offset = None
        if bit_width is not None:
            total_bits = int(round(raw_offset * 8))
            byte_offset = total_bits // 8
            bit_offset = total_bits % 8

        access_path = "%s.%s" % (path, var.name) if var.name else path

        fld = model.Field(
            name=var.name,
            type_name=var.decl_type.decl_string,
            kind=model.UNKNOWN,
            offset=byte_offset,
            abs_offset=base_offset + byte_offset,
            access_path=access_path,
            bit_width=bit_width,
            bit_offset=bit_offset,
            is_static=is_static,
        )
        self._describe_type(fld, var.decl_type, depth, seen)
        return fld

    def _describe_type(self, fld: model.Field, decl_type, depth: int, seen: Tuple[str, ...]):
        """Renseigne kind, size et enfants a partir du type pygccxml."""
        # remove_alias reconstruit le type et perd byte_size : on lit la taille
        # sur le type d'origine d'abord, puis sur le type resolu en secours.
        size = _int_or_none(getattr(decl_type, "byte_size", None))

        t = declarations.remove_alias(decl_type)
        if declarations.is_const(t) or declarations.is_volatile(t):
            fld.is_const = declarations.is_const(t)
            t = declarations.remove_cv(t)

        if not size:
            size = _int_or_none(getattr(t, "byte_size", None))
        fld.size = size if size else None

        # --- tableau --------------------------------------------------------
        if declarations.is_array(t):
            item = declarations.array_item_type(t)
            length = _int_or_none(declarations.array_size(t))
            fld.kind = model.ARRAY
            fld.array_len = length
            fld.elem_type = item.decl_string
            item_size = self._sizeof(item)
            if item_size is not None and length is not None:
                fld.size = item_size * length
            # On ne deplie pas les elements : un char[50] ferait 50 noeuds.
            # Le type d'element est decrit une fois, l'UI gere l'indexation.
            sub = model.Field(
                name="[]",
                type_name=item.decl_string,
                kind=model.UNKNOWN,
                offset=0,
                abs_offset=fld.abs_offset,
                access_path="%s[0]" % fld.access_path,
            )
            self._describe_type(sub, item, depth + 1, seen)
            if sub.kind in model.AGGREGATES and sub.children:
                fld.children = [sub]
            else:
                fld.elem_type = sub.type_name
            return

        # --- pointeur -------------------------------------------------------
        if declarations.is_pointer(t) or declarations.is_reference(t):
            fld.kind = model.POINTER
            fld.size = size or None
            if not self.cfg.follow_pointers:
                fld.truncated = "pointer"
                return
            pointee = declarations.remove_reference(declarations.remove_pointer(t))
            pointee = declarations.remove_cv(declarations.remove_alias(pointee))
            if declarations.is_class(pointee):
                self._descend_class(fld, pointee, depth, seen)
            return

        # --- enum -----------------------------------------------------------
        if declarations.is_enum(t):
            fld.kind = model.ENUM
            try:
                enum_decl = declarations.enum_declaration(t)
                fld.enum_values = [name for name, _ in enum_decl.values]
                fld.type_name = enum_decl.name or fld.type_name
            except Exception:
                pass
            return

        # --- classe, struct, union -------------------------------------------
        if declarations.is_class(t) or declarations.is_class_declaration(t):
            self._descend_class(fld, t, depth, seen)
            return

        # --- fondamental ------------------------------------------------------
        if declarations.is_fundamental(t):
            fld.kind = model.FUNDAMENTAL
            return

        if declarations.is_calldef_pointer(t) if hasattr(declarations, "is_calldef_pointer") else False:
            fld.kind = model.FUNCTION
            return

        fld.kind = model.UNKNOWN

    def _descend_class(self, fld: model.Field, t, depth: int, seen: Tuple[str, ...]):
        try:
            decl = declarations.class_traits.get_declaration(t)
        except Exception:
            try:
                decl = declarations.class_declaration_traits.get_declaration(t)
            except Exception:
                fld.kind = model.CLASS
                fld.truncated = "opaque"
                return

        # Type incomplet : declare mais jamais defini.
        if not isinstance(decl, declarations.class_t):
            fld.kind = model.CLASS
            fld.truncated = "opaque"
            return

        fld.kind = str(decl.class_type)
        fld.is_anonymous = not decl.name
        if fld.is_anonymous:
            # decl_string d'un type anonyme renvoie le nom du parent : inutilisable.
            fld.type_name = "<%s anonyme>" % fld.kind
        else:
            fld.type_name = decl.name
        fld.size = _int_or_none(getattr(decl, "byte_size", None)) or fld.size

        key = self._key(decl)
        if key in seen:
            fld.truncated = "cycle"
            return
        if depth + 1 >= self.cfg.max_depth:
            fld.truncated = "depth"
            return

        fld.children = self._members(
            decl,
            base_offset=fld.abs_offset,
            path=fld.access_path,
            depth=depth + 1,
            seen=seen + (key,),
        )

    def _sizeof(self, t) -> Optional[int]:
        direct = _int_or_none(getattr(t, "byte_size", None))
        if direct:
            return direct
        t = declarations.remove_cv(declarations.remove_alias(t))
        size = _int_or_none(getattr(t, "byte_size", None))
        if size:
            return size
        if declarations.is_array(t):
            item = self._sizeof(declarations.array_item_type(t))
            length = _int_or_none(declarations.array_size(t))
            if item is not None and length is not None:
                return item * length
            return None
        if declarations.is_class(t):
            try:
                return _int_or_none(declarations.class_traits.get_declaration(t).byte_size)
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------
# API de commodite
# ---------------------------------------------------------------------------
def parse_header(header=None, cfg: Optional[Config] = None) -> List[model.Struct]:
    return Introspector(cfg).parse(header)


def index_by_name(structs: List[model.Struct]) -> Dict[str, model.Struct]:
    return dict((s.name, s) for s in structs)
