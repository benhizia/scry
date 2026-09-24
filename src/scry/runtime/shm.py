"""Lecteur Python du canal de memoire partagee Scry.

Le protocole est decrit et implemente cote C++ dans scry_shm.h, embarque dans
le paquet : un en-tete de 128 octets, puis la charge utile, les octets bruts
d'une instance. L'ecrivain encadre chaque copie d'un compteur de sequence,
impair pendant l'ecriture (seqlock) : une copie est coherente si la sequence
est paire et n'a pas change entre avant et apres.

ShmChannelSource est une MemorySource : l'IHM et 'scry watch' decodent ses
octets par offset comme n'importe quel buffer. refresh() prend un nouvel
instantane coherent ; read() lit toujours dans le dernier, pour que tous les
membres affiches viennent de la meme publication.
"""

import struct
import sys
import time
from typing import Optional

from scry.runtime.memory import MemorySource

MAGIC = 0x59524353  # "SCRY"
VERSION = 1
HEADER_SIZE = 128
TYPE_NAME_OFFSET = 32
TYPE_NAME_SIZE = 96
SEQUENCE_OFFSET = 16
TIMESTAMP_OFFSET = 24

_PREFIX = struct.Struct("<IIII")      # magic, version, header_size, payload_size
_U64 = struct.Struct("<Q")


class ShmError(RuntimeError):
    pass


def header_path():
    """Chemin de scry_shm.h, a inclure dans le producteur C++."""
    from importlib.resources import files
    return files("scry.runtime") / "scry_shm.h"


class _Segment(object):
    """Segment ouvert en lecture : buf, close().

    Sous POSIX, shm_open et mmap en lecture seule, sans passer par
    multiprocessing.shared_memory : avant Python 3.13, son resource_tracker
    considere tout segment ouvert comme le sien et le detruit a la sortie du
    lecteur, sous les pieds du producteur. Sous Windows, pas de tracker, et
    SharedMemory sait retrouver la taille d'un mapping nomme existant.
    """

    def __init__(self, name: str):
        if sys.platform == "win32":
            from multiprocessing import shared_memory
            try:
                self._shm = shared_memory.SharedMemory(name=name, create=False)
            except FileNotFoundError:
                raise ShmError("Aucun segment '%s' : le producteur est-il lance ?" % name)
            self._map = None
            self.buf = self._shm.buf
            return

        import mmap
        import os

        import _posixshmem
        try:
            fd = _posixshmem.shm_open("/" + name, os.O_RDONLY, mode=0)
        except FileNotFoundError:
            raise ShmError("Aucun segment '%s' : le producteur est-il lance ?" % name)
        try:
            size = os.fstat(fd).st_size
            if size == 0:
                raise ShmError("Segment '%s' vide : producteur en cours de demarrage ?" % name)
            self._map = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ)
        finally:
            os.close(fd)
        self._shm = None
        self.buf = memoryview(self._map)

    def close(self):
        if self._map is not None:
            self.buf.release()
            self._map.close()
        else:
            self._shm.close()
        self.buf = None


def parse_header(buf) -> dict:
    """En-tete decode depuis un buffer d'au moins HEADER_SIZE octets."""
    if len(buf) < HEADER_SIZE:
        raise ShmError("Segment trop petit pour un en-tete Scry (%d octets)." % len(buf))
    magic, version, header_size, payload_size = _PREFIX.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ShmError("Ce segment n'est pas un canal Scry (magic 0x%08X)." % magic)
    if version != VERSION:
        raise ShmError("Version de protocole %d non geree (attendue %d)." % (version, VERSION))
    raw = bytes(buf[TYPE_NAME_OFFSET:TYPE_NAME_OFFSET + TYPE_NAME_SIZE])
    return {
        "header_size": header_size,
        "payload_size": payload_size,
        "type_name": raw.split(b"\0", 1)[0].decode("utf-8", errors="replace"),
    }


def snapshot(buf, header_size: int, payload_size: int, max_tries: int = 100):
    """(sequence, octets) d'une copie coherente, ou (0, None).

    Meme algorithme que Reader::snapshot en C++. La sequence est lue par un
    acces aligne de 8 octets, atomique sur les architectures visees.
    """
    for attempt in range(max_tries):
        before = _U64.unpack_from(buf, SEQUENCE_OFFSET)[0]
        if before == 0 or before & 1:
            if attempt:
                time.sleep(0)
            continue
        data = bytes(buf[header_size:header_size + payload_size])
        if _U64.unpack_from(buf, SEQUENCE_OFFSET)[0] == before:
            return before, data
    return 0, None


class ShmChannelSource(MemorySource):
    """Canal Scry ouvert en lecture, decode comme un buffer."""

    def __init__(self, name: str):
        self.name = name
        self._shm = _Segment(name)
        info = parse_header(self._shm.buf)
        self.header_size = info["header_size"]
        self.payload_size = info["payload_size"]
        self.type_name = info["type_name"]
        if len(self._shm.buf) < self.header_size + self.payload_size:
            raise ShmError("Segment plus petit que sa charge annoncee.")
        self.sequence = 0
        self._data = None  # type: Optional[bytes]
        self.refresh()

    @property
    def available(self) -> bool:
        return self._data is not None

    @property
    def publications(self) -> int:
        """Nombre de publications vues par le producteur."""
        return self.sequence // 2

    def timestamp_ns(self) -> int:
        return _U64.unpack_from(self._shm.buf, TIMESTAMP_OFFSET)[0]

    def refresh(self) -> bool:
        """Nouvel instantane. False si aucune copie coherente n'a pu etre
        prise ; le precedent est alors conserve."""
        seq, data = snapshot(self._shm.buf, self.header_size, self.payload_size)
        if data is None:
            return False
        self.sequence, self._data = seq, data
        return True

    def read(self, offset: int, size: int) -> Optional[bytes]:
        if self._data is None or offset < 0 or offset + size > len(self._data):
            return None
        return self._data[offset:offset + size]

    def close(self):
        self._data = None
        try:
            self._shm.close()
        except Exception:
            pass
