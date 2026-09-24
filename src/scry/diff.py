"""Comparaison de deux modeles : 'scry diff'.

Le cas vise : une bibliotheque tierce precompilee livre une nouvelle version
de son header. Si un layout a change, tout code qui lit ces structures par
offset, ou qui a ete compile contre l'ancien header, lit a cote. Aucun
compilateur ne le signale, puisque la bibliotheque est deja compilee. On garde
l'export JSON d'une version de reference et on compare.

Le modele exporte porte la plateforme qui l'a produit (compilateur,
architecture, standard, options) : comparer deux modeles de cibles
differentes signalerait des ecarts qui n'en sont pas, et diff le dit.

Ce module ne travaille que sur des dictionnaires, ceux de Struct.to_dict() :
il se teste sans castxml.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

import scry
from scry.config import Config

FORMAT = "scry-model"
FORMAT_VERSION = 1

# Proprietes d'un champ qui font son layout. Un changement de l'une d'elles
# casse les lecteurs par offset.
FIELD_KEYS = ("abs_offset", "size", "type", "kind", "array_len", "bit_width", "bit_offset")
STRUCT_KEYS = ("size", "align")
# Proprietes de la plateforme qui changent le layout.
PLATFORM_KEYS = ("compiler", "arch", "std", "cl_flags", "defines", "extra_cflags")


# -- export -------------------------------------------------------------------
def platform_info(cfg: Config, headers: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "scry": scry.__version__,
        "compiler": cfg.compiler,
        "toolset": cfg.toolset,
        "arch": cfg.arch,
        "std": cfg.std,
        "cl_flags": cfg.cl_flags,
        "defines": list(cfg.defines),
        "extra_cflags": cfg.extra_cflags,
        "headers": list(headers or []),
    }


def document(structs, cfg: Config, headers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Le JSON exporte : format, plateforme, structures."""
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "platform": platform_info(cfg, headers),
        "structs": [s.to_dict() for s in structs],
    }


def load(path: str) -> Dict[str, Any]:
    """Lit un export. Accepte aussi l'ancien format, une simple liste."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return {"format": FORMAT, "version": 0, "platform": {}, "structs": data}
    if data.get("format") != FORMAT:
        raise ValueError("%s n'est pas un export de Scry (scry json)." % path)
    return data


# -- comparaison --------------------------------------------------------------
def _fields(struct: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Champs a plat, indexes par chemin d'acces. Les statiques sont hors
    instance : ils ne font pas partie du layout."""
    out = {}
    stack = list(struct.get("fields", []))
    while stack:
        f = stack.pop()
        if not f.get("is_static"):
            out[f.get("access_path") or f.get("label") or f.get("name")] = f
        stack.extend(f.get("children", []))
    return out


class StructDiff(object):
    def __init__(self, name: str):
        self.name = name
        self.changes: List[Tuple[str, str, Any, Any]] = []   # (quoi, cle, avant, apres)
        self.removed: List[str] = []
        self.added: List[str] = []

    @property
    def breaking(self) -> bool:
        """Un lecteur par offset de l'ancienne version lirait a cote."""
        return bool(self.changes or self.removed)

    @property
    def empty(self) -> bool:
        return not (self.changes or self.removed or self.added)


class ModelDiff(object):
    def __init__(self):
        self.platform: List[Tuple[str, Any, Any]] = []
        self.removed: List[str] = []
        self.added: List[str] = []
        self.structs: List[StructDiff] = []

    @property
    def breaking(self) -> bool:
        return bool(self.removed) or any(s.breaking for s in self.structs)

    @property
    def empty(self) -> bool:
        return not (self.removed or self.added or self.structs)


def compare(ref: Dict[str, Any], new: Dict[str, Any]) -> ModelDiff:
    out = ModelDiff()
    ref_platform, new_platform = ref.get("platform", {}), new.get("platform", {})
    if ref_platform and new_platform:
        for key in PLATFORM_KEYS:
            if ref_platform.get(key) != new_platform.get(key):
                out.platform.append((key, ref_platform.get(key), new_platform.get(key)))

    ref_structs = {s["name"]: s for s in ref.get("structs", [])}
    new_structs = {s["name"]: s for s in new.get("structs", [])}
    out.removed = sorted(set(ref_structs) - set(new_structs))
    out.added = sorted(set(new_structs) - set(ref_structs))

    for name in sorted(set(ref_structs) & set(new_structs)):
        d = _compare_struct(name, ref_structs[name], new_structs[name])
        if not d.empty:
            out.structs.append(d)
    return out


def _compare_struct(name: str, a: Dict[str, Any], b: Dict[str, Any]) -> StructDiff:
    d = StructDiff(name)
    for key in STRUCT_KEYS:
        if a.get(key) != b.get(key):
            d.changes.append((name, key, a.get(key), b.get(key)))
    fa, fb = _fields(a), _fields(b)
    d.removed = sorted(set(fa) - set(fb))
    d.added = sorted(set(fb) - set(fa))
    for path in sorted(set(fa) & set(fb)):
        for key in FIELD_KEYS:
            if fa[path].get(key) != fb[path].get(key):
                d.changes.append((path, key, fa[path].get(key), fb[path].get(key)))
    return d


# -- rapport ------------------------------------------------------------------
def report(diff: ModelDiff) -> List[str]:
    lines = []
    if diff.platform:
        lines.append("[attention] les deux modeles ne viennent pas de la meme cible :")
        for key, a, b in diff.platform:
            lines.append("    %s : %r -> %r" % (key, a, b))
        lines.append("  Les ecarts ci-dessous peuvent venir de la cible, pas du header.")
        lines.append("")
    for name in diff.removed:
        lines.append("[supprime] %s" % name)
    for name in diff.added:
        lines.append("[ajoute]   %s" % name)
    for s in diff.structs:
        lines.append("[%s] %s" % ("CASSE " if s.breaking else "modifie", s.name))
        for what, key, a, b in s.changes:
            lines.append("    %-40s %-10s %s -> %s" % (what, key, a, b))
        for path in s.removed:
            lines.append("    - %s" % path)
        for path in s.added:
            lines.append("    + %s" % path)
    if not lines:
        lines.append("Layouts identiques.")
    return lines
