"""scry verify de bout en bout, avec le vrai castxml et le vrai compilateur.

Sous Windows, c'est cl et ses profils /MD et /MDd ; ailleurs g++ ou clang++,
-O2 contre -D_GLIBCXX_DEBUG. Des deux cotes, la STL de debug grossit les
conteneurs : un modele calcule sans elle ne tient pas dans ce profil.
"""

from pathlib import Path

import pytest

import toolchain
from scry import verify
from scry.config import load_config
from scry.parsing.introspect import Introspector

DATA = Path(__file__).resolve().parent.parent / "Data"

pytestmark = toolchain.needs_toolchain


def _cfg(tmp_path, extra=""):
    ini = tmp_path / "scry.ini"
    ini.write_text(
        toolchain.ini_paths(output=(tmp_path / "out").as_posix())
        + toolchain.ini_castxml("-Wno-pragma-once-outside-header %s" % extra)
        + toolchain.ini_verify("both"),
        encoding="utf-8")
    return load_config(ini)


def _run(cfg, header):
    structs = Introspector(cfg).parse(str(header))
    _, results = verify.run(structs, cfg, verify.load_profiles(cfg))
    return {r.name: r for r in results}


def test_layout_simple_tient_dans_tous_les_profils(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRY_VERIFY_GNU_PROFILES", raising=False)
    monkeypatch.delenv("SCRY_VERIFY_PROFILES", raising=False)
    results = _run(_cfg(tmp_path), DATA / "test_structs_simple.h")
    assert all(r.ok for r in results.values()), results


def test_stl_de_debug_est_detectee(tmp_path, monkeypatch):
    # /MDd sous MSVC, -D_GLIBCXX_DEBUG ailleurs.
    monkeypatch.delenv("SCRY_VERIFY_GNU_PROFILES", raising=False)
    monkeypatch.delenv("SCRY_VERIFY_PROFILES", raising=False)
    results = _run(_cfg(tmp_path), DATA / "test_structs_complexe.h")
    assert results["release"].ok
    assert not results["debug"].ok
    assert any(e.startswith("Scry : sizeof(") for e in results["debug"].errors)
