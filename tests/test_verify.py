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


# -- gcc et clang --------------------------------------------------------------
def _gnu_cfg(tmp_path, body=""):
    ini = tmp_path / "scry.ini"
    ini.write_text("[castxml]\ncompiler = gcc\n" + body, encoding="utf-8")
    return load_config(ini)


def test_profils_gnu_par_defaut(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRY_VERIFY_GNU_PROFILES", raising=False)
    cfg = _gnu_cfg(tmp_path)
    assert verify.load_profiles(cfg) == verify.DEFAULT_GNU_PROFILES


def test_profils_gnu_ignorent_ceux_de_cl(tmp_path, monkeypatch):
    # Un meme scry.ini sert sous Windows et en CI Linux : /MD n'a aucun sens
    # pour g++, les deux jeux de profils sont donc separes.
    monkeypatch.delenv("SCRY_VERIFY_GNU_PROFILES", raising=False)
    cfg = _gnu_cfg(tmp_path, "[verify]\nprofiles = release: /MD\n"
                             "gnu_profiles = asan: -fsanitize=address\n")
    assert verify.load_profiles(cfg) == [("asan", "-fsanitize=address")]


def test_find_cxx(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRY_VERIFY_CXX", raising=False)
    assert verify.find_cxx(_gnu_cfg(tmp_path)) == "g++"
    ini = tmp_path / "clang.ini"
    ini.write_text("[castxml]\ncompiler = clang\n", encoding="utf-8")
    assert verify.find_cxx(load_config(ini)) == "clang++"
    assert verify.find_cxx(_gnu_cfg(tmp_path, "[verify]\ncxx = g++-13\n")) == "g++-13"


def test_gnu_compile_command(tmp_path):
    cfg = _gnu_cfg(tmp_path, "defines = FOO=1\n")
    cmd = verify.gnu_compile_command("g++", cfg, "-D_GLIBCXX_DEBUG", ["/inc"], "t.cpp")
    assert cmd[:3] == ["g++", "-fsyntax-only", "-std=c++17"]
    for option in ("-D_GLIBCXX_DEBUG", "-DFOO=1", "-I/inc"):
        assert option in cmd
    assert cmd[-1] == "t.cpp"


def test_extract_errors_gcc_et_clang():
    output = "\n".join([
        "abi.h:28:47: error: static assertion failed: "
        "Scry : sizeof(testgen::A) differe de castxml (3968).",
        "abi.h:36:15: error: static assertion failed due to requirement "
        "'__builtin_offsetof(testgen::A, b) == 8U': "
        "Scry : offsetof(testgen::A, b) differe de castxml (8).",
        "abi.h:36:15: note: expression evaluates to '16 == 8'",
        "t.cpp:1:10: fatal error: abi.h: No such file or directory",
    ])
    assert verify.extract_errors(output) == [
        "Scry : sizeof(testgen::A) differe de castxml (3968).",
        "Scry : offsetof(testgen::A, b) differe de castxml (8).",
        "abi.h: No such file or directory",
    ]
