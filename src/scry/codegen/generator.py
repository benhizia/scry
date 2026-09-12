"""Generation du C++ d'introspection a partir du modele, via Jinja.

Deux choses sont emises, et c'est la demonstration centrale du projet :

  1. des static_assert sur sizeof et offsetof. Le modele vient de castxml, le
     code compile vient de MSVC. Si les deux ABI divergent, la compilation
     casse au lieu de produire un visualiseur qui lit n'importe quoi ;
  2. des fonctions de rendu ImGui qui lisent par offset depuis un pointeur
     d'octets. Elles n'ont pas besoin du type reel, donc elles fonctionnent
     aussi bien sur une instance locale que sur un bloc recu par memoire
     partagee ou par le reseau.
"""

import os
from importlib.resources import files
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from scry import model
from scry.config import Config, load_config


def _cpp_identifier(name: str) -> str:
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    if not out or out[0].isdigit():
        out = "_" + out
    return out


def field_context(fld: model.Field) -> Dict:
    """Vue plate d'un champ, prete a etre consommee par le template."""
    fmt = model.printf_for(fld.type_name, fld.size)
    is_char_array = fld.kind == model.ARRAY and fld.elem_type in (
        "char", "signed char", "unsigned char")

    ctx = {
        "name": fld.name,
        "label": fld.label(),
        "type": fld.type_name,
        "kind": fld.kind,
        "offset": fld.offset,          # relatif au parent, utilise par le template
        "abs_offset": fld.abs_offset,  # depuis la racine, utilise par l'UI et le SHM
        "size": fld.size,
        "access_path": fld.access_path,
        "array_len": fld.array_len,
        "elem_type": fld.elem_type,
        "bit_width": fld.bit_width,
        "bit_offset": fld.bit_offset,
        "enum_values": list(fld.enum_values),
        "is_static": fld.is_static,
        "is_anonymous": fld.is_anonymous,
        "truncated": fld.truncated,
        "is_char_array": is_char_array,
        "printf_fmt": fmt[0] if fmt else None,
        "printf_expr": fmt[1] if fmt else None,
        "color": "detail::" + _KIND_COLORS.get(fld.kind, "kColorDefault"),
    }
    # Lignes du tree-table : membres et trous de padding, dans l'ordre des
    # offsets, comme dans l'IHM Python.
    ctx["rows"] = _rows(fld.children, fld.size, fld.abs_offset,
                        with_holes=model.shows_holes(fld))
    ctx["children"] = [r for r in ctx["rows"] if r["kind"] != "padding"]
    return ctx


_KIND_COLORS = {
    model.FUNDAMENTAL: "kColorFundamental",
    model.ENUM: "kColorEnum",
    model.POINTER: "kColorPointer",
    model.ARRAY: "kColorArray",
    model.UNION: "kColorUnion",
}


def _rows(fields, size, base_abs: int, with_holes: bool, vptr: bool = False) -> List[Dict]:
    out = []
    for _, fld, hole in model.layout_items(list(fields), size, with_holes):
        if hole is None:
            out.append(field_context(fld))
            continue
        start, end = hole
        out.append({
            "kind": "padding",
            "label": model.hole_label(start, end, vptr and start == 0),
            "offset": start,
            "abs_offset": base_abs + start,
            "size": end - start,
        })
    return out


def struct_context(struct_info: model.Struct, cfg: Config) -> Dict:
    # offsetof n'est fiable que sur les membres de premier niveau non statiques
    # et non champs de bits : on ne genere des assertions que pour ceux-la.
    checks = [
        {"member": f.name, "offset": f.abs_offset}
        for f in struct_info.fields
        if f.name and not f.is_static and not f.is_bitfield and not f.is_anonymous
    ]

    return {
        "name": struct_info.name,
        "func": "draw_%s" % _cpp_identifier(struct_info.name),
        # offsetof est une macro : la virgule de RingBuffer<T, 8> couperait son
        # premier argument en deux. Les assertions passent par cet alias.
        "alias": "abi_%s" % _cpp_identifier(struct_info.name),
        "kind": struct_info.kind,
        "size": struct_info.size,
        "align": struct_info.align,
        "padding": struct_info.padding_bytes(),
        "is_polymorphic": struct_info.is_polymorphic,
        "abi_checks": checks,
        "fields": [field_context(f) for f in struct_info.fields],
        "rows": _rows(struct_info.fields, struct_info.size, 0, with_holes=True,
                      vptr=struct_info.is_polymorphic),
    }


def source_headers(structs: List[model.Struct], cfg: Optional[Config] = None,
                   header=None) -> List[str]:
    """Headers a inclure dans le C++ genere, en noms courts, ordre stable.

    Chaque Struct connait le header dont elle vient : c'est la source fiable
    en multi-fichiers. Le parametre header (chaine ou liste, comme -H) et
    [paths] header ne servent que de repli pour un modele sans origine.
    """
    paths = [s.header for s in structs if s.header]
    if not paths:
        if isinstance(header, (list, tuple)):
            paths = [str(h) for h in header]
        elif header:
            paths = [str(header)]
        elif cfg is not None and cfg.header:
            paths = [str(cfg.header)]

    out = []
    for path in paths:
        name = os.path.basename(path)
        if name and name not in out:
            out.append(name)
    return out


def build_context(structs: List[model.Struct], cfg: Optional[Config] = None,
                  header=None) -> Dict:
    cfg = cfg or load_config()
    return {
        "namespace": cfg.cpp_namespace,
        "source_headers": source_headers(structs, cfg, header),
        "abi_header": cfg.abi_header,
        "cl_flags": cfg.cl_flags,
        "emit_abi_checks": cfg.emit_abi_checks,
        "compiler": cfg.compiler,
        "arch": cfg.arch,
        "std": cfg.std,
        "structs": [struct_context(s, cfg) for s in structs],
    }


def _templates_dir() -> str:
    """Les templates voyagent avec le paquet.

    Resolution par importlib.resources et jamais par rapport au repertoire
    courant : c'est ce qui permet de lancer 'scry gen' depuis n'importe ou, et
    de faire fonctionner le paquet une fois installe depuis un wheel.
    """
    return str(files("scry.codegen") / "templates")


def render(structs: List[model.Struct], cfg: Optional[Config] = None,
           template_name: str = "introspection.h.j2", header: Optional[str] = None) -> str:
    cfg = cfg or load_config()
    env = Environment(
        loader=FileSystemLoader(_templates_dir()),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # Chaine litterale C++ : les noms de type ne contiennent normalement ni
    # guillemet ni antislash, mais un header tiers n'offre aucune garantie.
    env.filters["cstr"] = lambda s: str(s).replace("\\", "\\\\").replace('"', '\\"')
    template = env.get_template(template_name)
    return template.render(**build_context(structs, cfg, header))


def _write(cfg: Config, name: str, text: str) -> str:
    out_dir = cfg.output_dir
    os.makedirs(str(out_dir), exist_ok=True)
    out_path = os.path.join(str(out_dir), name)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return out_path


def generate_abi(structs: List[model.Struct], cfg: Optional[Config] = None,
                 header=None) -> str:
    """Ecrit le header d'assertions ABI seul. Retourne son chemin.

    Sans ImGui ni code : c'est le fichier a inclure dans le build de
    l'application cible, et celui que compile 'scry verify'.
    """
    cfg = cfg or load_config()
    return _write(cfg, cfg.abi_header,
                  render(structs, cfg, "abi_checks.h.j2", header=header))


def generate(structs: List[model.Struct], cfg: Optional[Config] = None,
             header=None) -> str:
    """Ecrit le header ImGui et, si emit_abi_checks, le header ABI qu'il
    inclut. Retourne le chemin du header ImGui."""
    cfg = cfg or load_config()
    if cfg.emit_abi_checks:
        generate_abi(structs, cfg, header=header)
    return _write(cfg, cfg.output_header, render(structs, cfg, header=header))


def dump_json(structs: List[model.Struct], path: str) -> str:
    """Export du modele brut. Utile pour alimenter un autre outil ou diffuser l'ABI."""
    import json
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([s.to_dict() for s in structs], fh, indent=2, ensure_ascii=False)
    return path
