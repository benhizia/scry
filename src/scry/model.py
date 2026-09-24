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
from typing import Any, Dict, List, Optional, Tuple

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
# Sous-objet d'une classe de base : ses membres sont ses enfants.
BASE = "base"

AGGREGATES = (STRUCT, UNION, CLASS, BASE)


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
    # "public", "protected" ou "private". offsetof n'est permis, hors de la
    # classe, que sur un membre public.
    access: str = "public"

    # Agregat polymorphe : son offset 0 est un pointeur de vtable.
    is_polymorphic: bool = False

    # Raison d'un arret de descente : "depth", "cycle", "opaque", "pointer",
    # "virtual" pour une base virtuelle, dont l'offset n'est pas constant
    truncated: str = ""

    # Commentaire de documentation relu dans le header, '' si aucun.
    doc: str = ""

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
        if self.kind == BASE:
            return "(base%s) %s" % (" virtuelle" if self.truncated == "virtual" else "",
                                    self.type_name)
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
            "access": self.access,
            "is_polymorphic": self.is_polymorphic,
            "truncated": self.truncated,
            "is_readable": self.is_readable,
            "doc": self.doc,
        }
        d["children"] = [c.to_dict() for c in self.children]
        return d


def padding_spans(fields: List[Field], size: Optional[int]) -> List[Tuple[int, int]]:
    """Intervalles [debut, fin) non couverts par un membre, relatifs au parent.

    Fusion d'intervalles et non somme des tailles : les unions se recouvrent,
    et plusieurs champs de bits partagent la meme unite de stockage. Une somme
    naive donnerait un resultat faux. Le padding de fin, qui arrondit sizeof
    a un multiple de alignof, est inclus.
    """
    if size is None:
        return []
    spans = sorted((f.offset, f.offset + f.size) for f in fields
                   if not f.is_static and f.size is not None)
    holes = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            holes.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < size:
        holes.append((cursor, size))
    return holes


def layout_items(fields: List[Field], size: Optional[int], with_holes: bool = True):
    """Membres et trous tries par offset relatif.

    Retourne des triplets (offset, field, None) ou (offset, None, (debut, fin)).
    A offset egal, un trou passe avant le membre, et les membres gardent
    l'ordre du source : unions et champs de bits restent lisibles. Partage par
    l'IHM Python et le generateur C++, pour que les deux affichent les memes
    lignes.
    """
    items = [(f.offset, 1, i, f, None) for i, f in enumerate(fields)]
    if with_holes:
        items += [(start, 0, i, None, (start, end))
                  for i, (start, end) in enumerate(padding_spans(fields, size))]
    items.sort(key=lambda it: it[:3])
    return [(offset, fld, span) for offset, _, _, fld, span in items]


def shows_holes(fld: Field) -> bool:
    """Un agregat imbrique n'affiche ses trous que s'il a un membre visible.

    std::string, std::map et la plupart des classes n'ont que des membres
    prives : avec include_non_public = false, ils n'ont aucun enfant, et tout
    leur contenu serait compte a tort comme du padding.
    """
    return fld.kind in AGGREGATES and any(not c.is_static for c in fld.children)


def hole_label(start: int, end: int, vptr: bool = False) -> str:
    """Libelle d'un trou. Sur un type polymorphe, le trou a l'offset 0 est le
    pointeur de vtable, et le cas echeant les membres des classes de base."""
    size = end - start
    if vptr:
        return "[vptr %d o]" % size if size == 8 else "[vptr et bases %d o]" % size
    return "[padding %d o]" % size


@dataclass
class Struct:
    """Une structure de premier niveau, racine d'un arbre de Field."""

    name: str
    kind: str = STRUCT
    size: Optional[int] = None
    align: Optional[int] = None
    header: str = ""
    is_polymorphic: bool = False
    # Constructible par defaut sans lier la bibliotheque du tiers : aucun
    # constructeur par defaut, de la classe, de ses bases ou de ses membres,
    # n'est defini hors du header. Faux, le visualiseur natif ne tente pas de
    # construire d'instance, ce qui echouerait a l'edition des liens.
    inline_constructible: bool = True
    doc: str = ""
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

    def padding_spans(self) -> List[Tuple[int, int]]:
        """Trous du premier niveau, voir padding_spans()."""
        return padding_spans(self.fields, self.size)

    def padding_bytes(self) -> Optional[int]:
        """Octets non couverts par un membre, au premier niveau.

        Sur un type polymorphe, le pointeur de vtable en fait partie : il
        n'est pas un membre declare.
        """
        if self.size is None:
            return None
        return sum(end - start for start, end in self.padding_spans())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "align": self.align,
            "header": self.header,
            "is_polymorphic": self.is_polymorphic,
            "inline_constructible": self.inline_constructible,
            "doc": self.doc,
            "padding": self.padding_bytes(),
            "fields": [f.to_dict() for f in self.fields],
        }


# ---------------------------------------------------------------------------
# Correspondance type C++ -> format ImGui, utilisee par le generateur
# ---------------------------------------------------------------------------
PRINTF_FORMATS = {
    "bool": ("%s", '{expr} ? "true" : "false"'),
    "char": ("'%c'", "{expr}"),
    "signed char": ("%hhd", "{expr}"),
    "unsigned char": ("%hhu", "{expr}"),
    "short int": ("%hd", "{expr}"),
    "short unsigned int": ("%hu", "{expr}"),
    "int": ("%d", "{expr}"),
    "unsigned int": ("%u", "{expr}"),
    "long int": ("%ld", "{expr}"),
    "long unsigned int": ("%lu", "{expr}"),
    # Conversion explicite : sous Linux (LP64), uint64_t et size_t sont des
    # unsigned long, pas des unsigned long long, et %llu n'y correspond pas.
    "long long int": ("%lld", "static_cast<long long>({expr})"),
    "long long unsigned int": ("%llu", "static_cast<unsigned long long>({expr})"),
    # %.6g comme scry.runtime.memory.decode : l'IHM Python et le visualiseur
    # C++ affichent ainsi les memes chaines pour les memes octets.
    "float": ("%.6g", "static_cast<double>({expr})"),
    "double": ("%.6g", "{expr}"),
    "long double": ("%.6Lg", "{expr}"),
}


# Alias de taille fixe : pygccxml rend le nom du typedef ('::uint64_t'), pas le
# type fondamental. Sans cette table, aucun entier de <cstdint> n'est decode.
FIXED_WIDTH_ALIASES = {
    "int8_t": "signed char",
    "uint8_t": "unsigned char",
    "int16_t": "short int",
    "uint16_t": "short unsigned int",
    "int32_t": "int",
    "uint32_t": "unsigned int",
    "int64_t": "long long int",
    "uint64_t": "long long unsigned int",
}
# Alias dont la taille depend de l'architecture : resolus par la taille du champ.
SIZED_ALIASES = {
    "size_t": ("unsigned int", "long long unsigned int"),
    "uintptr_t": ("unsigned int", "long long unsigned int"),
    "ptrdiff_t": ("int", "long long int"),
    "intptr_t": ("int", "long long int"),
}


def canonical_type(type_name: str, size: Optional[int] = None) -> str:
    """Type fondamental derriere un alias standard, sinon le nom tel quel."""
    name = type_name.strip()
    bare = name
    for prefix in ("::", "std::", "::std::"):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
    if bare in FIXED_WIDTH_ALIASES:
        return FIXED_WIDTH_ALIASES[bare]
    if bare in SIZED_ALIASES:
        small, large = SIZED_ALIASES[bare]
        return large if size == 8 else small
    return name


def printf_for(type_name: str, size: Optional[int] = None):
    """Retourne (format, expression) pour un type fondamental, sinon None.
    Les alias de <cstdint> et <cstddef> sont ramenes a leur type fondamental."""
    return PRINTF_FORMATS.get(canonical_type(type_name, size))
