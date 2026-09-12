"""scry verify, sans lancer cl : profils, commande, lecture des erreurs."""

from pathlib import Path

import pytest

from scry import verify
from scry.config import load_config

EXAMPLE_INI = Path(__file__).resolve().parent.parent / "scry.ini.example"


def test_parse_profiles():
    assert verify.parse_profiles(["release: /MD", " debug : /MDd /DFOO "]) == [
        ("release", "/MD"), ("debug", "/MDd /DFOO")]


def test_parse_profiles_mal_forme():
    with pytest.raises(ValueError, match="nom: options"):
        verify.parse_profiles(["/MD"])


def test_profils_par_defaut_et_ceux_de_l_exemple(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRY_VERIFY_PROFILES", raising=False)
    ini = tmp_path / "scry.ini"
    ini.write_text("[paths]\n", encoding="utf-8")
    assert verify.load_profiles(load_config(ini)) == verify.DEFAULT_PROFILES
    assert verify.load_profiles(load_config(EXAMPLE_INI)) == [
        ("release", "/MD"), ("debug", "/MDd")]


def test_extract_errors_isole_le_message_des_static_assert():
    output = "\n".join([
        "scry_verify.cpp",
        "X:\\G\\abi.h(12): error C2338: static_assert failed: "
        "'Scry : sizeof(A) differe de castxml (8).'",
        "X:\\G\\abi.h(3): fatal error C1083: fichier introuvable",
        "X:\\G\\abi.h(12): note: l'expression a pour valeur false",
    ])
    assert verify.extract_errors(output) == [
        "Scry : sizeof(A) differe de castxml (8).",
        "C1083 fichier introuvable",
    ]


def test_compile_command():
    cfg = load_config(EXAMPLE_INI)
    cmd = verify.compile_command("cl.exe", cfg, "/MDd /DX=1", ["C:/inc"], "t.cpp")
    assert cmd[:2] == ["cl.exe", "/nologo"]
    # /Zs : analyse complete, static_assert compris, sans fichier objet.
    for option in ("/Zs", "/std:c++17", "/MDd", "/DX=1", "/IC:/inc"):
        assert option in cmd
    assert cmd[-1] == "t.cpp"
