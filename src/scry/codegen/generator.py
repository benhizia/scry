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
    fmt = model.printf_for(fld.type_name)
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
        "children": [field_context(c) for c in fld.children],
    }
    return ctx


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
        "kind": struct_info.kind,
        "size": struct_info.size,
        "align": struct_info.align,
        "padding": struct_info.padding_bytes(),
        "is_polymorphic": struct_info.is_polymorphic,
        "abi_checks": checks,
        "fields": [field_context(f) for f in struct_info.fields],
    }


def build_context(structs: List[model.Struct], cfg: Optional[Config] = None,
                  header: Optional[str] = None) -> Dict:
    cfg = cfg or load_config()
    source_header = header or (str(cfg.header) if cfg.header else "")
    return {
        "namespace": cfg.cpp_namespace,
        "source_header": os.path.basename(source_header),
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
    template = env.get_template(template_name)
    return template.render(**build_context(structs, cfg, header))


def generate(structs: List[model.Struct], cfg: Optional[Config] = None,
             header: Optional[str] = None) -> str:
    """Rend le template et ecrit le fichier. Retourne le chemin ecrit."""
    cfg = cfg or load_config()
    text = render(structs, cfg, header=header)
    out_dir = cfg.output_dir
    os.makedirs(str(out_dir), exist_ok=True)
    out_path = os.path.join(str(out_dir), cfg.output_header)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return out_path


def dump_json(structs: List[model.Struct], path: str) -> str:
    """Export du modele brut. Utile pour alimenter un autre outil ou diffuser l'ABI."""
    import json
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([s.to_dict() for s in structs], fh, indent=2, ensure_ascii=False)
    return path
