"""Modele intermediaire de BuffyPyGen.

Pourquoi une couche intermediaire plutot que de promener des objets pygccxml
dans toute l'application : les declarations pygccxml sont vivantes, couteuses,
non serialisables et pleines de cas particuliers. Une fois converties ici, on
obtient des donnees plates, testables sans castxml, serialisables en JSON, et
consommables aussi bien par l'UI ImGui que par les templates Jinja ou, plus
tard, par un lecteur de memoire partagee.

L'invariant central pour le futur visualiseur memoire : chaque Field porte un
offset ABSOLU depuis le debut de la structure racine. Un lecteur SHM n'a alors
besoin que d'un pointeur de base et de cet offset.
"""

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

# Natures de champ.
FUNDAMENTAL = "fundamental"
ENUM = "enum"
STRUCT = "struct"
UNION = "union"
CLASS = "class"
POINTER = "pointer"
ARRAY = "array"
FUNCTION = "function"
UNKNOWN = "unknown"

AGGREGATES = (STRUCT, UNION, CLASS)


@dataclass
class Field:
    """Une donnee membre, eventuellement composite."""

    name: str
    type_name: str
    kind: str
    offset: int = 0                  # relatif au parent immediat, en octets
    abs_offset: int = 0              # depuis la racine, en octets
    size: Optional[int] = None       # en octets, None si inconnu
    access_path: str = ""            # "obj.origin.lat"

    # Tableaux
    array_len: Optional[int] = None
    elem_type: Optional[str] = None

    # Champs de bits
    bit_width: Optional[int] = None
    bit_offset: Optional[int] = None  # bits depuis abs_offset

    # Enums
    enum_values: List[str] = dc_field(default_factory=list)

    # Drapeaux
    is_static: bool = False
    is_anonymous: bool = False
    is_const: bool = False

    # Raison d'un arret de descente : "depth", "cycle", "opaque", "pointer"
    truncated: str = ""

    children: List["Field"] = dc_field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_bitfield(self) -> bool:
        return self.bit_width is not None

    @property
    def is_readable(self) -> bool:
        """Lisible directement depuis un buffer memoire par offset."""
        return (
            self.kind in (FUNDAMENTAL, ENUM, POINTER)
            and not self.is_static
            and self.size is not None
        )

    def label(self) -> str:
        if self.is_bitfield:
            return "%s : %d" % (self.name, self.bit_width)
        if self.array_len is not None:
            return "%s[%d]" % (self.name, self.array_len)
        return self.name or "<anonyme>"

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "label": self.label(),
            "type": self.type_name,
            "kind": self.kind,
            "offset": self.offset,
            "abs_offset": self.abs_offset,
            "size": self.size,
            "access_path": self.access_path,
            "array_len": self.array_len,
            "elem_type": self.elem_type,
            "bit_width": self.bit_width,
            "bit_offset": self.bit_offset,
            "enum_values": list(self.enum_values),
            "is_static": self.is_static,
            "is_anonymous": self.is_anonymous,
            "is_const": self.is_const,
            "truncated": self.truncated,
            "is_readable": self.is_readable,
        }
        d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class Struct:
    """Une structure de premier niveau, racine d'un arbre de Field."""

    name: str
    kind: str = STRUCT
    size: Optional[int] = None
    align: Optional[int] = None
    header: str = ""
    is_polymorphic: bool = False
    fields: List[Field] = dc_field(default_factory=list)

    def walk(self):
        """Parcours prefixe de tous les champs, profondeur incluse."""
        stack = [(f, 0) for f in reversed(self.fields)]
        while stack:
            node, depth = stack.pop()
            yield node, depth
            for child in reversed(node.children):
                stack.append((child, depth + 1))

    def leaves(self):
        for node, _ in self.walk():
            if node.is_leaf and node.is_readable:
                yield node

    def padding_bytes(self) -> Optional[int]:
        """Octets non couverts par un membre, au premier niveau.

        Calcule par fusion d'intervalles et non par somme des tailles : les
        unions se recouvrent, et plusieurs champs de bits partagent la meme
        unite de stockage. Une somme naive donnerait un resultat faux.
        """
        if self.size is None:
            return None
        spans = []
        for f in self.fields:
            if f.is_static or f.size is None:
                continue
            spans.append((f.offset, f.offset + f.size))
        if not spans:
            return self.size
        spans.sort()
        covered = 0
        cur_start, cur_end = spans[0]
        for start, end in spans[1:]:
            if start > cur_end:
                covered += cur_end - cur_start
                cur_start, cur_end = start, end
            else:
                cur_end = max(cur_end, end)
        covered += cur_end - cur_start
        return self.size - covered

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "align": self.align,
            "header": self.header,
            "is_polymorphic": self.is_polymorphic,
            "padding": self.padding_bytes(),
            "fields": [f.to_dict() for f in self.fields],
        }


# ---------------------------------------------------------------------------
# Correspondance type C++ -> format ImGui, utilisee par le generateur
# ---------------------------------------------------------------------------
PRINTF_FORMATS = {
    "bool": ("%s", '{expr} ? "true" : "false"'),
    "char": ("%c", "{expr}"),
    "signed char": ("%hhd", "{expr}"),
    "unsigned char": ("%hhu", "{expr}"),
    "short int": ("%hd", "{expr}"),
    "short unsigned int": ("%hu", "{expr}"),
    "int": ("%d", "{expr}"),
    "unsigned int": ("%u", "{expr}"),
    "long int": ("%ld", "{expr}"),
    "long unsigned int": ("%lu", "{expr}"),
    "long long int": ("%lld", "{expr}"),
    "long long unsigned int": ("%llu", "{expr}"),
    "float": ("%.3f", "static_cast<double>({expr})"),
    "double": ("%.6f", "{expr}"),
    "long double": ("%.6Lf", "{expr}"),
}


def printf_for(type_name: str):
    """Retourne (format, expression) pour un type fondamental, sinon None."""
    return PRINTF_FORMATS.get(type_name.strip())
