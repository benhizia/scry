"""Instantanes et differences de structures.

snapshot() fige une vue C++ en types Python simples (to_dict() des bindings
generes) : l'instantane ne bouge plus quand l'application ecrit. diff() liste
ce qui a change, chemin par chemin.

    avant = snapshot(sut.outputs)
    await cycles(5)
    for ligne in diff(avant, snapshot(sut.outputs)):
        print(ligne)          # legs[2].phase : Cruise -> Climb
"""

import copy
from typing import Any, List


def snapshot(obj) -> Any:
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(obj, (list, tuple)):
        return [snapshot(item) for item in obj]
    tolist = getattr(obj, "tolist", None)                  # vue numpy
    if callable(tolist):
        return tolist()
    return copy.deepcopy(obj)


def diff(before, after, path: str = "", tol: float = 0.0) -> List[str]:
    """Differences lisibles entre deux instantanes. tol s'applique aux flottants."""
    out = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in list(before) + [k for k in after if k not in before]:
            sub = "%s.%s" % (path, key) if path else str(key)
            if key not in after:
                out.append("%s : supprime" % sub)
            elif key not in before:
                out.append("%s : ajoute" % sub)
            else:
                out.extend(diff(before[key], after[key], sub, tol))
        return out
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            out.append("%s : %d elements -> %d" % (path, len(before), len(after)))
        for i, (a, b) in enumerate(zip(before, after)):
            out.extend(diff(a, b, "%s[%d]" % (path, i), tol))
        return out
    if isinstance(before, float) and isinstance(after, float) and abs(before - after) <= tol:
        return out
    if before != after:
        out.append("%s : %r -> %r" % (path or "valeur", before, after))
    return out
