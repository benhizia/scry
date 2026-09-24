"""scry verify de bout en bout, avec le vrai castxml et le vrai g++.

Saute si l'un des deux manque : les autres tests restent executables sur un
poste sans toolchain. En CI Linux, 'pip install castxml' suffit a les activer.
"""

import shutil
from pathlib import Path

import pytest

from scry import verify
from scry.config import load_config
from scry.parsing.introspect import Introspector

DATA = Path(__file__).resolve().parent.parent / "Data"

pytestmark = pytest.mark.skipif(
    not (shutil.which("castxml") and shutil.which("g++")),
    reason="castxml ou g++ absent")


def _cfg(tmp_path, extra=""):
    ini = tmp_path / "scry.ini"
    ini.write_text(
        "[paths]\noutput = %s\ncache =\n"
        "[castxml]\ncompiler = gcc\n"
        "extra_cflags = -Wno-pragma-once-outside-header %s\n"
        % ((tmp_path / "out").as_posix(), extra),
        encoding="utf-8")
    return load_config(ini)


def _run(cfg, header):
    structs = Introspector(cfg).parse(str(header))
    _, results = verify.run(structs, cfg, verify.load_profiles(cfg))
    return {r.name: r for r in results}


def test_layout_simple_tient_dans_tous_les_profils(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRY_VERIFY_GNU_PROFILES", raising=False)
    results = _run(_cfg(tmp_path), DATA / "test_structs_simple.h")
    assert all(r.ok for r in results.values()), results


def test_glibcxx_debug_est_detecte(tmp_path, monkeypatch):
    # Le pendant de /MDd : la STL de debug change la taille des conteneurs,
    # et un modele calcule sans la macro ne tient pas dans ce profil.
    monkeypatch.delenv("SCRY_VERIFY_GNU_PROFILES", raising=False)
    results = _run(_cfg(tmp_path), DATA / "test_structs_complexe.h")
    assert results["release"].ok
    assert not results["debug"].ok
    assert any(e.startswith("Scry : sizeof(") for e in results["debug"].errors)
