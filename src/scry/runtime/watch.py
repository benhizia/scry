"""'scry watch' : les valeurs d'un canal de memoire partagee, en console.

Pendant generique du simple_spy d'InterfaceInspector : aucun type code en
dur, la structure vient du modele et les valeurs sont decodees par offset.
Fonctions pures sur un modele et une MemorySource : testees sans segment.
"""

import time
from typing import List, Optional

from scry import model
from scry.runtime.memory import decode


class WatchError(RuntimeError):
    pass


def pick_struct(structs: List[model.Struct], source, wanted: Optional[str] = None
                ) -> model.Struct:
    """Structure a decoder : celle demandee, sinon celle que le segment annonce.

    Refuse une structure dont la taille differe de la charge utile : les
    offsets ne s'appliqueraient pas, et tout ce qui serait affiche serait faux.
    """
    name = wanted or source.type_name
    by_name = {s.name: s for s in structs}
    struct = by_name.get(name)
    if struct is None:
        raise WatchError("Le segment publie '%s', absent du modele (%s). --struct pour "
                         "choisir." % (name, ", ".join(sorted(by_name)) or "vide"))
    if struct.size != source.payload_size:
        raise WatchError("%s fait %s o dans le modele, le segment en publie %d : "
                         "producteur compile avec un autre layout ?"
                         % (struct.name, struct.size, source.payload_size))
    return struct


def _shown(struct: model.Struct):
    """Membres decodables : fondamentaux, enums, pointeurs, et tableaux de
    char, que les headers tiers utilisent comme chaines."""
    for f, _ in struct.walk():
        if f.is_static or not f.is_leaf:
            continue
        is_text = f.kind == model.ARRAY and f.elem_type in ("char", "signed char",
                                                            "unsigned char")
        if f.is_readable or is_text:
            yield f


def render(struct: model.Struct, source, segment: str = "") -> List[str]:
    """Lignes affichees : en-tete, puis un membre lisible par ligne."""
    age = ""
    stamp = getattr(source, "timestamp_ns", None)
    if callable(stamp) and stamp():
        # steady_clock du producteur et monotonic_ns de Python partagent la
        # meme horloge sous Linux et Windows ; ailleurs l'age est indicatif.
        age = "   age %.0f ms" % max(0.0, (time.monotonic_ns() - stamp()) / 1e6)
    lines = ["%s  %s  %s o   publication %d%s"
             % (segment, struct.name, struct.size, getattr(source, "publications", 0), age),
             ""]
    if not source.available:
        lines.append("(aucune publication coherente pour l'instant)")
        return lines
    shown = [f for f in _shown(struct)]
    width = max([len(f.access_path) for f in shown] + [10])
    for f in shown:
        value = decode(source, f)
        lines.append("  %-*s @%-6d %-22s %s"
                     % (width, f.access_path, f.abs_offset, f.type_name[:22],
                        "-" if value is None else value))
    return lines
