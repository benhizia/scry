"""Lecture de valeurs a partir d'un buffer memoire et des offsets du modele.

C'est la maquette Python de ce que fera plus tard le C++ genere : le modele
fournit un offset absolu et une taille, la source fournit des octets, et on
decode. La meme structure de code s'appliquera a une memoire partagee ou a un
flux reseau, seule la source change.

Attention, l'hypothese qui rend tout cela valide : les offsets viennent de
castxml, donc de l'ABI de la cible declaree dans scry.ini. Si l'application qui
produit les octets est compilee avec une autre architecture, un autre packing
ou un autre compilateur, les offsets ne correspondent plus. Le code C++ genere
inclut des static_assert pour transformer ce risque silencieux en erreur de
compilation.
"""

import struct
from typing import Optional

from scry import model

# Type fondamental C++ -> format struct, en little-endian explicite.
STRUCT_FORMATS = {
    "bool": "?",
    "char": "c",
    "signed char": "b",
    "unsigned char": "B",
    "short int": "h",
    "short unsigned int": "H",
    "int": "i",
    "unsigned int": "I",
    "long int": "l",
    "long unsigned int": "L",
    "long long int": "q",
    "long long unsigned int": "Q",
    "float": "f",
    "double": "d",
}


class MemorySource(object):
    """Interface minimale d'une source d'octets."""

    def read(self, offset: int, size: int) -> Optional[bytes]:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return True


class BufferSource(MemorySource):
    """Source triviale sur un bytes ou bytearray en memoire."""

    def __init__(self, buffer: bytes):
        self.buffer = buffer

    def read(self, offset: int, size: int) -> Optional[bytes]:
        if offset < 0 or offset + size > len(self.buffer):
            return None
        return bytes(self.buffer[offset:offset + size])


class SharedMemorySource(MemorySource):
    """Lecture d'un segment de memoire partagee POSIX ou Windows.

    Utilise multiprocessing.shared_memory, disponible depuis Python 3.8. Le
    producteur C++ doit creer le segment sous le meme nom ; sous Windows cela
    correspond a un mapping de fichier nomme.
    """

    def __init__(self, name: str):
        from multiprocessing import shared_memory
        self._shm = shared_memory.SharedMemory(name=name)

    def read(self, offset: int, size: int) -> Optional[bytes]:
        if offset < 0 or offset + size > self._shm.size:
            return None
        return bytes(self._shm.buf[offset:offset + size])

    def close(self):
        self._shm.close()


def decode(source: MemorySource, field: model.Field) -> Optional[str]:
    """Valeur lisible d'un champ, ou None si non decodable."""
    if source is None or field.size is None or field.is_static:
        return None

    # Champ de bits : on lit l'unite de stockage puis on extrait les bits.
    if field.is_bitfield:
        raw = source.read(field.abs_offset, field.size)
        if raw is None:
            return None
        word = int.from_bytes(raw, "little")
        shift = field.bit_offset or 0
        mask = (1 << field.bit_width) - 1
        return str((word >> shift) & mask)

    if field.kind == model.POINTER:
        raw = source.read(field.abs_offset, field.size)
        if raw is None:
            return None
        return "0x%016X" % int.from_bytes(raw, "little")

    if field.kind == model.ENUM:
        raw = source.read(field.abs_offset, field.size)
        if raw is None:
            return None
        value = int.from_bytes(raw, "little", signed=True)
        # Valeurs reelles de l'enum, pas un index : 'Fast = 10' se lit Fast.
        name = model.enum_name(field, value)
        return "%s (%d)" % (name, value) if name is not None else str(value)

    # Cas tres frequent dans les headers tiers : char[N] utilise comme chaine.
    if field.kind == model.ARRAY and field.elem_type in ("char", "signed char", "unsigned char"):
        raw = source.read(field.abs_offset, field.size)
        if raw is None:
            return None
        text = raw.split(b"\x00", 1)[0]
        return '"%s"' % text.decode("utf-8", errors="replace")

    if field.kind == model.FUNDAMENTAL:
        fmt = STRUCT_FORMATS.get(model.canonical_type(field.type_name, field.size))
        if fmt is None:
            return None
        raw = source.read(field.abs_offset, struct.calcsize("<" + fmt))
        if raw is None:
            return None
        value = struct.unpack("<" + fmt, raw)[0]
        # Memes chaines que le C++ genere (model.PRINTF_FORMATS).
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, bytes):
            return repr(value.decode("latin-1"))
        if isinstance(value, float):
            return "%.6g" % value
        return str(value)

    return None


def make_demo_buffer(struct_info: model.Struct) -> bytes:
    """Buffer de demonstration : motif reconnaissable a la taille de la structure."""
    size = struct_info.size or 0
    return bytes((i * 7 + 3) % 251 for i in range(size))
