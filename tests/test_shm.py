"""Canal de memoire partagee : protocole, lecteur Python, producteur C++."""

import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
from multiprocessing import shared_memory

import pytest
from pathlib import Path

from scry import model, producer
from scry.config import load_config
from scry.runtime import shm, watch

HEADER = struct.Struct("<IIIIQQ")


def _header(payload_size, sequence=2, type_name=b"demo::Etat", magic=shm.MAGIC,
            version=shm.VERSION):
    head = HEADER.pack(magic, version, shm.HEADER_SIZE, payload_size, sequence, 0)
    return head + type_name.ljust(shm.TYPE_NAME_SIZE, b"\0")


def test_en_tete_decode():
    info = shm.parse_header(_header(40))
    assert info == {"header_size": 128, "payload_size": 40, "type_name": "demo::Etat"}


@pytest.mark.parametrize("kw, message", [
    ({"magic": 0x1234}, "pas un canal Scry"),
    ({"version": 9}, "Version de protocole 9"),
])
def test_en_tete_refuse(kw, message):
    with pytest.raises(shm.ShmError, match=message):
        shm.parse_header(_header(4, **kw))


def test_en_tete_trop_court():
    with pytest.raises(shm.ShmError, match="trop petit"):
        shm.parse_header(b"\0" * 10)


def test_snapshot_sequence_impaire_ou_nulle():
    payload = bytes(range(8))
    assert shm.snapshot(_header(8, sequence=3) + payload, 128, 8, max_tries=3) == (0, None)
    assert shm.snapshot(_header(8, sequence=0) + payload, 128, 8, max_tries=3) == (0, None)
    assert shm.snapshot(_header(8, sequence=4) + payload, 128, 8) == (4, payload)


class _Moving(bytearray):
    """Buffer dont la sequence avance a chaque copie de la charge : un
    ecrivain qui publie pendant la lecture."""

    def __getitem__(self, key):
        data = bytearray.__getitem__(self, key)
        if isinstance(key, slice) and key.start == 128:
            seq = struct.unpack_from("<Q", self, 16)[0]
            struct.pack_into("<Q", self, 16, seq + 2)
        return data


def test_snapshot_rejette_une_copie_dechiree():
    buf = _Moving(_header(4, sequence=2) + b"abcd")
    assert shm.snapshot(buf, 128, 4, max_tries=5) == (0, None)


def _segment(payload, name=None, sequence=2):
    name = name or "scry_test_%s" % uuid.uuid4().hex[:8]
    raw = _header(len(payload), sequence) + payload
    seg = shared_memory.SharedMemory(name=name, create=True, size=len(raw))
    seg.buf[:len(raw)] = raw
    return seg


def test_canal_lu_depuis_python():
    payload = bytes((i * 7 + 3) % 251 for i in range(16))
    seg = _segment(payload)
    try:
        src = shm.ShmChannelSource(seg.name)
        assert (src.type_name, src.payload_size, src.publications) == ("demo::Etat", 16, 1)
        assert src.read(4, 4) == payload[4:8]
        assert src.read(14, 4) is None
        src.close()
    finally:
        seg.close()
        seg.unlink()


def test_segment_absent():
    with pytest.raises(shm.ShmError, match="producteur"):
        shm.ShmChannelSource("scry_absent_%s" % uuid.uuid4().hex[:8])


# -- scry watch -----------------------------------------------------------------
def _etat():
    return model.Struct(name="demo::Etat", size=16, align=8, fields=[
        model.Field(name="mode", type_name="int", kind=model.FUNDAMENTAL, offset=0,
                    abs_offset=0, size=4, access_path="obj.mode"),
        model.Field(name="v", type_name="double", kind=model.FUNDAMENTAL, offset=8,
                    abs_offset=8, size=8, access_path="obj.v"),
    ])


class _Fake(object):
    type_name = "demo::Etat"
    payload_size = 16
    publications = 7
    available = True

    def __init__(self, data):
        self.data = data

    def read(self, offset, size):
        return self.data[offset:offset + size]


def test_watch_choisit_la_structure_annoncee():
    fake = _Fake(struct.pack("<iid", 42, 0, 1.5))
    s = watch.pick_struct([_etat()], fake)
    lines = watch.render(s, fake, "scry_demo")
    assert lines[0].startswith("scry_demo  demo::Etat  16 o   publication 7")
    assert any("obj.mode" in line and line.endswith("42") for line in lines)
    assert any("obj.v" in line and line.endswith("1.5") for line in lines)


def test_watch_refuse_un_layout_different():
    fake = _Fake(b"")
    fake.payload_size = 24
    with pytest.raises(watch.WatchError, match="autre layout"):
        watch.pick_struct([_etat()], fake)
    fake.type_name = "autre::T"
    with pytest.raises(watch.WatchError, match="absent du modele"):
        watch.pick_struct([_etat()], fake)


# -- producteur C++ reel ----------------------------------------------------------
needs_toolchain = pytest.mark.skipif(
    sys.platform == "win32" or not (shutil.which("castxml") and shutil.which("g++")),
    reason="castxml ou g++ absent")

HEADER_H = """#pragma once
#include <cstdint>
namespace demo {
struct Etat { std::int32_t mode; double vitesse; char nom[12]; std::uint16_t bits : 5; };
}
"""


def _cfg(tmp_path, segment):
    (tmp_path / "demo.h").write_text(HEADER_H, encoding="utf-8")
    ini = tmp_path / "scry.ini"
    ini.write_text(
        "[paths]\nheaders = demo.h\noutput = out\ncache =\n"
        "[castxml]\ncompiler = gcc\nextra_cflags = -Wno-pragma-once-outside-header\n"
        "[shm]\nname = %s\nbuild_dir = build\n" % segment, encoding="utf-8")
    return load_config(ini)


def _wait_for(name, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            src = shm.ShmChannelSource(name)
            if src.available:
                return src
            src.close()
        except shm.ShmError:
            pass
        time.sleep(0.05)
    raise AssertionError("segment %s jamais publie" % name)


@needs_toolchain
def test_producteur_cpp_et_lecteur_python_sans_dechirure(tmp_path):
    from scry.parsing.introspect import Introspector
    segment = "scry_test_%s" % uuid.uuid4().hex[:8]
    cfg = _cfg(tmp_path, segment)
    structs = Introspector(cfg).parse()
    exe = producer.build(structs, cfg)
    # --period 0 : l'ecrivain publie sans pause, chaque lecture chevauche une
    # ecriture. Le seqlock doit rejeter toutes les copies dechirees.
    proc = subprocess.Popen([str(exe), "--period", "0"], stdout=subprocess.PIPE)
    try:
        src = _wait_for(segment)
        etat = watch.pick_struct(structs, src)
        assert etat.name == "demo::Etat" and src.payload_size == etat.size
        seen = set()
        for _ in range(300):
            if not src.refresh():
                continue
            data = src.read(0, src.payload_size)
            # Tick de cette publication, deduit du premier octet : tous les
            # autres doivent venir du meme tick.
            tick = (data[0] - 3) % 251
            assert data == bytes((i * 7 + 3 + tick) % 251 for i in range(len(data)))
            seen.add(src.sequence)
        assert len(seen) > 10
        lines = watch.render(etat, src, segment)
        assert any(line.lstrip().startswith("obj.bits") for line in lines)
        src.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    # L'ecrivain retire son segment a l'arret.
    assert not os.path.exists("/dev/shm/%s" % segment) or sys.platform == "darwin"


@needs_toolchain
def test_scry_watch_une_fois(tmp_path, capsys):
    from scry import cli
    segment = "scry_test_%s" % uuid.uuid4().hex[:8]
    cfg = _cfg(tmp_path, segment)
    assert cli.main(["producer", "-c", str(tmp_path / "scry.ini")]) == 0
    exe = producer.exe_path(cfg)
    proc = subprocess.Popen([str(exe), "--period", "20"], stdout=subprocess.PIPE)
    try:
        _wait_for(segment).close()
        capsys.readouterr()
        assert cli.main(["watch", "--once", "-c", str(tmp_path / "scry.ini")]) == 0
        out = capsys.readouterr().out
        assert "demo::Etat" in out and "obj.vitesse" in out and "obj.nom" in out
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_commande_de_compilation_du_producteur(tmp_path):
    ini = tmp_path / "scry.ini"
    ini.write_text("[castxml]\ncompiler = gcc\ndefines = A=1\n[shm]\nname = scry_x\n",
                   encoding="utf-8")
    cfg = load_config(ini)
    assert producer.segment_name(cfg) == "scry_x"
    cmd = producer.compile_command(cfg, "p.cpp", ["/inc"], producer.exe_path(cfg))
    assert cmd[:3] == ["g++", "-std=c++17", "-O2"]
    assert "-DA=1" in cmd and "-I/inc" in cmd
    msvc = load_config(Path(__file__).resolve().parent.parent / "scry.ini.example")
    cmd = producer.compile_command(msvc, "p.cpp", ["C:/inc"], producer.exe_path(msvc), "cl.exe")
    assert cmd[0] == "cl.exe" and "/MD" in cmd and "/IC:/inc" in cmd
    assert producer.exe_path(msvc).name == "scry_producer.exe"


def test_header_du_protocole_embarque():
    text = shm.header_path().read_text(encoding="utf-8")
    assert "static_assert(sizeof(Header) == 128" in text
    # Offsets codes en dur des deux cotes : ils doivent concorder.
    assert "offsetof(Header, sequence) == %d" % shm.SEQUENCE_OFFSET in text
    assert "offsetof(Header, type_name) == %d" % shm.TYPE_NAME_OFFSET in text
