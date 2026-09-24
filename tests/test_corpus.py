"""Corpus de headers varies, passe par le vrai castxml et le vrai compilateur.

Data/corpus reprend les headers d'essai d'InterfaceInspector : heritage,
templates, packing, types imbriques, statiques et amis, RAII, interfaces,
C++ moderne, commentaires. Pour chacun, avec et sans membres non publics :

  1. le parsing reussit ;
  2. le modele tient face a g++ : abi_checks.generated.h compile ;
  3. si Dear ImGui est present dans third_party/imgui, le header ImGui
     genere compile en -Wall -Wextra -Werror, se lie sans la bibliotheque
     d'aucun tiers, et ses fonctions de rendu s'executent en headless.

Tout saute proprement sur un poste sans castxml ou sans g++.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from scry import verify
from scry.codegen import generator
from scry.config import load_config
from scry.parsing.introspect import Introspector

ROOT = Path(__file__).resolve().parent.parent
CORPUS = sorted((ROOT / "Data" / "corpus").glob("*.hpp"))
IMGUI = ROOT / "third_party" / "imgui"
HEADLESS = Path(__file__).resolve().parent / "cpp" / "headless.cpp"
IMGUI_SOURCES = ["imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp"]

pytestmark = pytest.mark.skipif(
    not (shutil.which("castxml") and shutil.which("g++")),
    reason="castxml ou g++ absent")


def _cfg(tmp_path, non_public):
    ini = tmp_path / "scry.ini"
    ini.write_text(
        "[paths]\noutput = %s\ncache =\n"
        "[castxml]\ncompiler = gcc\n"
        "extra_cflags = -Wno-pragma-once-outside-header\n"
        "[introspection]\ninclude_non_public = %s\n"
        "[verify]\ngnu_profiles = release: -O2\n"
        % ((tmp_path / "out").as_posix(), "true" if non_public else "false"),
        encoding="utf-8")
    return load_config(ini)


def _parse(cfg, header):
    introspector = Introspector(cfg)
    structs = introspector.parse(str(header))
    assert not introspector.report.failures, introspector.report.lines()
    assert structs, "aucune structure dans %s" % header.name
    return structs


@pytest.fixture(autouse=True)
def _sans_surcharge(monkeypatch):
    for var in ("SCRY_VERIFY_GNU_PROFILES", "SCRY_VERIFY_CXX",
                "SCRY_INTROSPECTION_INCLUDE_NON_PUBLIC"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("non_public", [False, True], ids=["public", "non_public"])
@pytest.mark.parametrize("header", CORPUS, ids=[h.name for h in CORPUS])
def test_modele_tient_face_a_gxx(tmp_path, header, non_public):
    cfg = _cfg(tmp_path, non_public)
    structs = _parse(cfg, header)
    _, results = verify.run(structs, cfg, verify.load_profiles(cfg))
    for r in results:
        assert r.ok, "\n".join(r.errors) or r.output


def test_membres_non_publics_exclus_des_offsetof(tmp_path):
    cfg = _cfg(tmp_path, True)
    structs = {s.name: s for s in _parse(cfg, ROOT / "Data/corpus/02_class_with_methods.hpp")}
    calc = structs["Calculator"]
    assert {f.name: f.access for f in calc.fields} == {
        "state_": "private", "debug_mode_": "private"}
    abi = generator.render(list(structs.values()), cfg, "abi_checks.h.j2")
    assert "offsetof(abi_Calculator, state_)" not in abi
    assert "sizeof(abi_Calculator)" in abi


def test_constructeurs_hors_du_header_detectes(tmp_path):
    structs = _parse(_cfg(tmp_path, False), ROOT / "Data/corpus/11_constructeurs.hpp")
    got = {s.name: s.inline_constructible for s in structs}
    assert got == {
        "Implicit": True, "Defaulted": True, "InClass": True, "NoDefault": True,
        # std::vector ne construit aucun element : il ne demande rien au tiers.
        "VecOfBad": True,
        "OutOfLine": False, "HasBadMember": False, "HasBadBase": False,
        "HasBadArray": False,
        # Definition inline placee apres la classe : non vue, resultat prudent.
        "InlineLater": False,
    }


# -- C++ ImGui genere, compile et execute --------------------------------------
@pytest.fixture(scope="session")
def imgui_objects(tmp_path_factory):
    if not (IMGUI / "imgui.h").is_file():
        pytest.skip("Dear ImGui absent de third_party/imgui "
                    "(scry viewer --fetch-imgui, ou voir third_party/README.md)")
    out = tmp_path_factory.mktemp("imgui")
    objects = []
    procs = []
    for src in IMGUI_SOURCES:
        obj = out / (Path(src).stem + ".o")
        procs.append(subprocess.Popen(
            ["g++", "-std=c++17", "-O0", "-c", str(IMGUI / src), "-o", str(obj)]))
        objects.append(str(obj))
    assert all(p.wait() == 0 for p in procs)
    return objects


@pytest.mark.parametrize("non_public", [False, True], ids=["public", "non_public"])
@pytest.mark.parametrize("header", CORPUS, ids=[h.name for h in CORPUS])
def test_rendu_genere_compile_et_s_execute(tmp_path, header, non_public, imgui_objects):
    cfg = _cfg(tmp_path, non_public)
    structs = _parse(cfg, header)
    generator.generate(structs, cfg)
    exe = tmp_path / "headless"
    cmd = ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
           "-I%s" % (tmp_path / "out"), "-I%s" % IMGUI, "-I%s" % header.parent,
           str(HEADLESS)] + imgui_objects + ["-o", str(exe)]
    build = subprocess.run(cmd, capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-4000:]
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "structures=%d" % len(structs) in run.stdout


def test_heritage(tmp_path):
    structs = {s.name: s for s in _parse(_cfg(tmp_path, False),
                                         ROOT / "Data/corpus/12_heritage.hpp")}

    def top(name):
        return [(f.label(), f.abs_offset, f.size) for f in structs[name].fields]

    assert top("Multi") == [("(base) A", 0, 16), ("(base) B", 16, 1), ("m", 20, 4)]
    # Base vide omise : elle n'occupe aucun octet.
    assert top("WithEmpty") == [("w", 0, 4)]
    # Seul le destructeur est virtuel : polymorphe, vptr en tete de la base.
    assert structs["Poly"].is_polymorphic and structs["Derived"].is_polymorphic
    assert structs["Derived"].fields[0].is_polymorphic
    # Base virtuelle signalee, non placee.
    vbase = structs["V1"].fields[0]
    assert (vbase.kind, vbase.truncated, vbase.size) == ("base", "virtual", None)
    # Membres herites atteints par le chemin de la derivee.
    level2 = {f.access_path: f.abs_offset for f, _ in structs["Level2"].walk()
              if f.kind != "base"}
    assert level2 == {"obj.a": 0, "obj.d": 8, "obj.b": 16, "obj.m": 20, "obj.l2": 24}
    # Vtable portee par un destructeur hors du header : pas d'instance.
    assert not structs["Poly"].inline_constructible
    assert not structs["Derived"].inline_constructible
    assert structs["InlinePoly"].inline_constructible
    assert structs["FromInline"].inline_constructible
    # Base privee masquee sans include_non_public.
    assert top("PrivateBase") == [("pb", 16, 4)]
