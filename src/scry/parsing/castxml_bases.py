"""Offsets des classes de base, que pygccxml ne lit pas.

castxml ecrit, sous chaque Struct ou Class, un element par classe de base :

    <Struct id="_11" name="Multi" bases="_8 _9" size="192" align="64">
      <Base type="_8" access="public" virtual="0" offset="0"/>
      <Base type="_9" access="public" virtual="0" offset="16"/>
    </Struct>

pygccxml n'en retient que l'attribut 'bases', herite du format gccxml : il
perd l'offset de chaque base, et lit toutes les bases comme non virtuelles.
Sans ces offsets, impossible de placer les membres herites.

Ce module enveloppe le scanner SAX de pygccxml pour recueillir ces elements
et les attacher a la declaration de classe, dans l'ordre de l'attribut
'bases', qui est aussi celui de hierarchy_info_t dans cls.bases. Les donnees
voyagent avec la declaration, donc aussi dans le cache pygccxml.

Seul le parsing touche a ce module, comme a pygccxml.
"""

from typing import List, NamedTuple, Optional

from pygccxml.parser import scanner as _scanner

ATTRIBUTE = "_scry_base_layout"
_CLASS_ELEMENTS = ("Struct", "Class", "Union")


class BaseLayout(NamedTuple):
    offset: Optional[int]   # en octets, None pour une base virtuelle
    is_virtual: bool


def install():
    """Idempotent : n'enveloppe le scanner qu'une fois."""
    cls = _scanner.scanner_t
    if getattr(cls, "_scry_bases_installed", False):
        return
    original_start = cls.startElement
    original_end = cls.endElement

    def startElement(self, name, attrs):
        original_start(self, name, attrs)
        if name in _CLASS_ELEMENTS:
            decls = getattr(self, "_scanner_t__declarations", {})
            self._scry_class = decls.get(attrs.get("id"))
            if self._scry_class is not None:
                setattr(self._scry_class, ATTRIBUTE, [])
        elif name == "Base":
            current = getattr(self, "_scry_class", None)
            if current is None:
                return
            virtual = attrs.get("virtual", "0") == "1"
            offset = attrs.get("offset")
            getattr(current, ATTRIBUTE).append(BaseLayout(
                None if virtual or offset is None else int(offset), virtual))

    def endElement(self, name):
        original_end(self, name)
        if name in _CLASS_ELEMENTS:
            self._scry_class = None

    cls.startElement = startElement
    cls.endElement = endElement
    cls._scry_bases_installed = True


def base_layout(cls) -> List[BaseLayout]:
    """Une entree par element de cls.bases, [] si castxml n'a rien donne."""
    layout = getattr(cls, ATTRIBUTE, None) or []
    if len(layout) != len(getattr(cls, "bases", [])):
        return []
    return list(layout)
