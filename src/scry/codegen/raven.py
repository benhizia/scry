"""Glue RAVEN : descripteur .rvndesc et publication cote simulateur.

Deux fichiers, a partir des variables globales choisies comme canaux :

- <nom>.rvndesc : le descripteur, un fichier texte ligne a ligne que raven.exe
  charge au demarrage. Il ne contient que des donnees : noms, chemins, natures,
  offsets, tailles, enums, unites. RAVEN n'est jamais recompile quand un header
  change.
- raven_publish.gen.h : compile dans le simulateur. static_assert sur le
  layout, puis une fonction publish() qui copie chaque variable dans la trame
  de l'anneau de memoire partagee.

Format du descripteur (version 1), un enregistrement par ligne, champs separes
par des espaces, le dernier champ texte pouvant en contenir :

    rvndesc 1
    schema 0x<fnv1a64 du reste>
    frame_size <octets>
    enum <id> <nombre> <nom>
    item <valeur> <nom>
    channel <id> <offset_trame> <taille> <nb_champs> <nom>
    field <idx> <parent> <nature> <offset> <taille_elem> <nombre> <enum> <unite> <chemin>
    end

Les champs d'un canal suivent sa ligne 'channel', en ordre prefixe : un parent
precede toujours ses enfants. L'offset est relatif au debut du canal.
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from scry import model

FORMAT_VERSION = 1
FRAME_ALIGN = 8

_UNIT_RE = re.compile(r"^\s*\[([^\]]+)\]")


def _kind(fld: model.Field, type_name: str) -> str:
    """Nature RAVEN d'une feuille : bool, int, uint, float, enum, pointer, other."""
    if fld.is_bitfield:
        return "other"                      # hors perimetre du logiciel minimal
    if fld.kind == model.ENUM:
        return "enum"
    if fld.kind == model.POINTER:
        return "pointer"
    t = type_name.replace("::", " ").replace("std ", "").strip()
    if t == "bool":
        return "bool"
    if t in ("float", "double", "long double"):
        return "float"
    if "unsigned" in t or t.startswith("uint") or t in ("size_t", "char16_t", "char32_t"):
        return "uint"
    return "int"


def _unit(fld: model.Field) -> str:
    m = _UNIT_RE.match(fld.doc or "")
    return m.group(1).replace(" ", "_") if m else "-"


class _Builder(object):
    def __init__(self):
        self.enums = {}          # type: Dict[str, Tuple[int, List[Tuple[int, str]]]]
        self.lines = []          # type: List[str]

    def enum_id(self, fld: model.Field) -> int:
        key = fld.enum_type or fld.qualified_type or fld.type_name
        if key not in self.enums:
            self.enums[key] = (len(self.enums), model.enum_cases(fld))
        return self.enums[key][0]

    def fields(self, root: model.Field) -> List[str]:
        out = []  # type: List[str]

        def emit(fld, parent, path, base):
            idx = len(out)
            off = fld.abs_offset - base
            if fld.children:
                kind = "struct"
                out.append("field %d %d struct %d %d 1 -1 - %s"
                           % (idx, parent, off, fld.size or 0, path))
                # Tableau de structures : chaque element devient un champ a
                # part entiere, a son propre offset. Le modele ne decrit que
                # l'element 0 ; on le remet une fois par element en decalant la
                # base, ce qui decale du meme coup tous ses membres.
                #
                # Sans cela, seul le premier element serait enregistrable,
                # observable et tracable : le descripteur n'aurait decrit que
                # legs[0], et legs[1..3] n'auraient existe nulle part.
                if (fld.kind == model.ARRAY and fld.array_len and fld.size
                        and len(fld.children) == 1):
                    elem = fld.children[0]
                    esize = fld.size // fld.array_len
                    for i in range(fld.array_len):
                        emit(elem, idx, "%s[%d]" % (path, i), base - i * esize)
                    return
                for c in fld.children:
                    if c.is_static or c.kind == model.FUNCTION:
                        continue
                    name = c.name or "<anonyme>"
                    emit(c, idx, "%s.%s" % (path, name) if path else name, base)
                return
            if fld.kind == model.ARRAY and fld.array_len:
                count = fld.array_len
                esize = (fld.size or 0) // count if count else 0
                kind = _kind(fld, fld.elem_type or "")
            else:
                count, esize = 1, fld.size or 0
                kind = _kind(fld, fld.type_name)
            enum = self.enum_id(fld) if kind == "enum" else -1
            out.append("field %d %d %s %d %d %d %d %s %s"
                       % (idx, parent, kind, off, esize, count, enum, _unit(fld), path))

        for c in root.children:
            if not c.is_static and c.kind != model.FUNCTION:
                emit(c, -1, c.name, root.abs_offset)
        return out


def _fnv1a64(text: str) -> int:
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def select_channels(variables: List[model.Variable], names: List[str]) -> List[model.Variable]:
    """Variables retenues comme canaux, dans l'ordre demande (toutes si vide)."""
    if not names:
        return [v for v in variables if not v.is_const]
    by_name = {}
    for v in variables:
        by_name[v.name] = v
        by_name[v.qualified_name] = v
    missing = [n for n in names if n not in by_name]
    if missing:
        raise ValueError("canaux introuvables dans les headers : %s" % ", ".join(missing))
    return [by_name[n] for n in names]


def select_types(structs: List[model.Struct], names: List[str]) -> List[model.Variable]:
    """Structures retenues comme canaux : pour le mode reseau, ou un message
    transporte une struct entiere et non une variable globale. Le canal porte
    le nom court du type ("TelemetryBroadcast")."""
    by_name = {}
    for st in structs:
        by_name[st.name] = st
        by_name[st.name.split("::")[-1]] = st
    missing = [n for n in names if n not in by_name]
    if missing:
        raise ValueError("types introuvables dans les headers : %s" % ", ".join(missing))
    out = []
    for n in names:
        st = by_name[n]
        if st.size is None:
            raise ValueError("taille inconnue pour %s" % n)
        root = model.Field(name=n, type_name=st.name, kind=model.STRUCT, size=st.size,
                           qualified_type=st.name, children=st.fields)
        out.append(model.Variable(name=n.split("::")[-1], qualified_name=st.name, field=root))
    return out


def build(channels: List[model.Variable]) -> Tuple[str, List[Tuple[model.Variable, int]], int, int]:
    """Texte du descripteur, offsets des canaux dans la trame, taille, schema."""
    b = _Builder()
    body = []  # type: List[str]
    placed = []
    offset = 0
    for cid, var in enumerate(channels):
        if var.field.size is None:
            raise ValueError("taille inconnue pour %s" % var.name)
        offset = (offset + FRAME_ALIGN - 1) // FRAME_ALIGN * FRAME_ALIGN
        fields = b.fields(var.field) if var.field.children else [
            "field 0 -1 %s 0 %d 1 %d %s %s" % (
                _kind(var.field, var.field.type_name), var.field.size,
                b.enum_id(var.field) if var.field.kind == model.ENUM else -1,
                _unit(var.field), var.name)]
        body.append("channel %d %d %d %d %s" % (cid, offset, var.field.size, len(fields), var.name))
        body.extend(fields)
        placed.append((var, offset))
        offset += var.field.size
    frame_size = (offset + FRAME_ALIGN - 1) // FRAME_ALIGN * FRAME_ALIGN

    head = ["frame_size %d" % frame_size]
    for _key, (eid, cases) in sorted(b.enums.items(), key=lambda kv: kv[1][0]):
        head.append("enum %d %d %s" % (eid, len(cases), _key.lstrip(":")))
        head.extend("item %d %s" % (v, n) for v, n in cases)
    text = "\n".join(head + body + ["end"]) + "\n"
    schema = _fnv1a64(text)
    full = "rvndesc %d\nschema 0x%016X\n" % (FORMAT_VERSION, schema) + text
    return full, placed, frame_size, schema


def _publish_header(placed, frame_size: int, schema: int, headers: List[str]) -> str:
    lines = [
        "// GENERE PAR SCRY (scry raven), ne pas modifier.",
        "// Publication des canaux RAVEN, a compiler dans le simulateur.",
        "#pragma once",
    ]
    lines += ['#include "%s"' % h for h in headers]
    lines += [
        "#include <raven/producer.h>",
        "#include <cstddef>",
        "#include <cstring>",
        "",
        "// Le layout compile doit etre celui que decrit le .rvndesc : sinon,",
        "// relancer 'scry raven'.",
    ]
    for var, _off in placed:
        lines.append('static_assert(sizeof(%s) == %d, "%s a change : relancer scry raven");'
                     % (var.qualified_name, var.field.size, var.name))
        for leaf in _leaves(var.field):
            member = leaf.access_path.split(".", 1)[1] if "." in leaf.access_path else ""
            if member and leaf.access == "public" and not leaf.is_bitfield:
                lines.append("static_assert(offsetof(decltype(%s), %s) == %d, \"%s\");"
                             % (var.qualified_name, member, leaf.abs_offset - var.field.abs_offset,
                                leaf.access_path))
    lines += [
        "",
        "namespace raven_gen {",
        "",
        "constexpr unsigned long long kSchemaHash = 0x%016XULL;" % schema,
        "constexpr unsigned kFrameSize = %d;" % frame_size,
        "",
        "// Ouvre l'anneau de memoire partagee 'name' (cree par le simulateur).",
        "inline bool open(raven::Producer& p, const char* name, unsigned slots = 64) {",
        "    return p.create(name, kSchemaHash, kFrameSize, slots);",
        "}",
        "",
        "// A appeler en fin de cycle : copie chaque canal dans une trame, puis la publie.",
        "inline void publish(raven::Producer& p) {",
        "    unsigned char* f = p.begin_frame();",
    ]
    for var, off in placed:
        lines.append("    std::memcpy(f + %d, &%s, sizeof(%s));"
                     % (off, var.qualified_name, var.qualified_name))
    lines += ["    p.end_frame();", "}", "", "} // namespace raven_gen", ""]
    return "\n".join(lines)


def _leaves(fld: model.Field):
    stack = [fld]
    while stack:
        f = stack.pop()
        if f.children:
            stack.extend(reversed(f.children))
        elif f is not fld and not f.is_static:
            yield f


def generate(variables: List[model.Variable], names: List[str], out_dir: str,
             desc_name: str, include_headers: List[str],
             structs: Optional[List[model.Struct]] = None,
             type_names: Optional[List[str]] = None) -> List[str]:
    """Ecrit le .rvndesc, et la glue du simulateur s'il y a des variables.

    Sans type_names, les canaux sont les variables globales (toutes si 'names'
    est vide). Avec type_names, ce sont ces structures, suivies des variables
    explicitement demandees dans 'names'.
    """
    if type_names:
        typed = select_types(structs or [], type_names)
        globals_ = select_channels(variables, names) if names else []
    else:
        typed, globals_ = [], select_channels(variables, names)
    channels = globals_ + typed
    if not channels:
        raise ValueError("aucune variable globale ni aucun type a publier")
    text, placed, frame_size, schema = build(channels)
    placed = [(v, off) for v, off in placed if v not in typed]
    os.makedirs(out_dir, exist_ok=True)
    desc_path = os.path.join(out_dir, desc_name + ".rvndesc")
    with open(desc_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if not placed:                     # que des types : rien a publier par SHM
        return [desc_path]
    pub_path = os.path.join(out_dir, "raven_publish.gen.h")
    with open(pub_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_publish_header(placed, frame_size, schema, include_headers))
    return [desc_path, pub_path]
