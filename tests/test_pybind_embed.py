"""Bindings generes, dans un interpreteur Python EMBARQUE dans une appli C++.

C'est l'usage vise : l'application C++ embarque Python, le module genere par
Scry (scry_module.generated.cpp) expose tous ses types et toutes ses variables
globales par reference, et un script les lit et les ecrit dans le cycle de
l'application, sans copie ni IPC.

L'hote (tests/cpp/pybind_host.cpp) definit les globales de
tests/data/pybind_cases.h, execute un script, puis vide les octets de ses
structures : le test les decode aux offsets du modele. Ce que Python a ecrit
doit s'y trouver, ce qui prouve que bindings, modele et compilateur sont
d'accord.

Compile une fois par session (une vingtaine de secondes). Saute sans castxml,
g++, pybind11, numpy ou les headers et la bibliotheque de Python.
"""

import shutil
import subprocess
import sys
import sysconfig
import textwrap
from pathlib import Path

import pytest

from scry.runtime import memory
from scry.runtime.memory import BufferSource

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "Data"
CASES = ROOT / "tests" / "data" / "pybind_cases.h"
HOST = ROOT / "tests" / "cpp" / "pybind_host.cpp"


def _python_build_flags():
    """-I et -l pour embarquer l'interpreteur courant, ou None."""
    include = sysconfig.get_paths()["include"]
    libdir = sysconfig.get_config_var("LIBDIR")
    ldlib = sysconfig.get_config_var("LDLIBRARY") or ""
    if not (Path(include) / "Python.h").is_file() or not ldlib.endswith(".so"):
        return None
    name = ldlib[3:-3]                      # libpython3.11.so -> python3.11
    return ["-I%s" % include], ["-L%s" % libdir, "-Wl,-rpath,%s" % libdir, "-l%s" % name]


pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not (shutil.which("castxml") and shutil.which("g++"))
    or _python_build_flags() is None,
    reason="castxml, g++ ou libpython absent")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    pybind11 = pytest.importorskip("pybind11")
    pytest.importorskip("numpy")
    from scry.codegen import pybind
    from scry.config import load_config
    from scry.parsing.introspect import Introspector, index_by_name

    out = tmp_path_factory.mktemp("pybind_embed")
    ini = out / "scry.ini"
    ini.write_text(
        "[paths]\noutput = gen\ncache =\n"
        "[castxml]\ncompiler = gcc\nextra_cflags = -Wno-pragma-once-outside-header\n"
        "include_paths = %s\n"
        # include_non_public : les membres prives entrent dans le modele, les
        # bindings doivent les ecarter pour compiler.
        "[introspection]\nstop_on_error = true\ninclude_non_public = true\n"
        % DATA.as_posix(), encoding="utf-8")
    cfg = load_config(ini)
    introspector = Introspector(cfg)
    structs = introspector.parse([str(CASES), str(DATA / "test_structs_complexe.h")])
    pybind.generate(structs, cfg, variables=introspector.variables)

    gen = out / "gen"
    py_inc, py_lib = _python_build_flags()
    exe = out / "pybind_host"
    cmd = (["g++", "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
            # Hors du perimetre de cette branche : -Winvalid-offsetof dans le
            # header ABI, s_internal inutilise dans le header de test.
            "-Wno-invalid-offsetof", "-Wno-unused-variable",
            "-I%s" % gen, "-I%s" % CASES.parent, "-I%s" % DATA,
            "-I%s" % pybind11.get_include()] + py_inc
           + [str(HOST), str(gen / "scry_module.generated.cpp"), "-o", str(exe)] + py_lib)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-6000:]
    return exe, index_by_name(structs), introspector.variables, gen


def run(built, tmp_path, script):
    exe = built[0]
    path = tmp_path / "script.py"
    path.write_text(textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run([str(exe), str(path)], capture_output=True, text=True, timeout=60)
    out = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(" ")
        out[key] = value
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


def _field(struct_model, name):
    return next(f for f, _ in struct_model.walk() if f.name == name)


def test_variables_collectees_static_ecartee(built):
    names = {v.qualified_name for v in built[2]}
    assert {"cases::g_sample", "cases::g_speed", "cases::g_version",
            "cases::inner::g_ticks", "cases::g_sensors"} <= names
    assert "cases::s_internal" not in names


def test_scalaires_enum_chaine_bits_dans_une_globale(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        s = c.g_sample
        s.speed = c.Speed.Fast
        s.mode, s.armed, s.level = 5, 1, 0xABC
        s.tag = "RWY27"
        s.from_ = -7
        for stmt, exc in [("s.tag = 'x' * 8", ValueError), ("s.pas_un_champ = 1", AttributeError)]:
            try:
                exec(stmt)
                raise SystemExit("aucune erreur : " + stmt)
            except exc:
                pass
    """)
    model_ = built[1]["cases::Sample"]
    src = BufferSource(bytes.fromhex(out["SAMPLE"]))
    assert memory.decode(src, _field(model_, "speed")) == "Fast (10)"
    assert memory.decode(src, _field(model_, "mode")) == "5"
    assert memory.decode(src, _field(model_, "armed")) == "1"
    assert memory.decode(src, _field(model_, "level")) == str(0xABC)
    assert memory.decode(src, _field(model_, "tag")) == '"RWY27"'
    assert memory.decode(src, _field(model_, "from")) == "-7"


def test_vues_numpy_sans_copie(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        s = sut.cases.g_sample
        v = s.values
        v[2] = 4.5                     # ecrit a travers la vue
        assert v.base is not None      # vue, pas copie
        s.grid[1, 2] = -3
        s.vec = [1.0, 2.0, 3.0]
        assert s.grid.shape == (2, 3)
        try:
            s.values = [1.0, 2.0]
            raise SystemExit("taille non verifiee")
        except ValueError:
            pass
        g = sut.cases.g_gains          # tableau numerique global
        g[1] = 20.0
        sut.cases.g_gains = [7, 8, 9]  # affectation complete
    """)
    import struct
    model_ = built[1]["cases::Sample"]
    raw = bytes.fromhex(out["SAMPLE"])
    assert struct.unpack_from("<d", raw, _field(model_, "values").abs_offset + 16)[0] == 4.5
    assert struct.unpack_from("<h", raw, _field(model_, "grid").abs_offset + 5 * 2)[0] == -3
    assert struct.unpack_from("<3f", raw, _field(model_, "vec").abs_offset) == (1.0, 2.0, 3.0)
    assert out["GAINS"] == "7 8 9"


def test_union_et_struct_anonymes(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        s = sut.cases.g_sample
        s.raw = 0x3F800000
        assert s.as_float == 1.0
        s.pair.lo, s.pair.hi = 1, 2
    """)
    import struct
    raw = bytes.fromhex(out["SAMPLE"])
    offset = _field(built[1]["cases::Sample"], "pair").abs_offset
    assert struct.unpack_from("<HH", raw, offset) == (1, 2)


def test_globales_scalaires_constantes_et_namespaces(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        assert c.g_version == 42
        assert c.g_callsign == "F-GKXA"
        c.g_speed = c.Speed.Max
        c.g_callsign = "N123"
        c.inner.g_ticks += 5
        c.inner.g_ticks += 5
        for stmt in ["c.g_version = 1", "c.g_speeed = 1", "c.inner.g_tick = 1"]:
            try:
                exec(stmt)
                raise SystemExit("aucune erreur : " + stmt)
            except AttributeError:
                pass
        assert not hasattr(c, "s_internal")
        assert "g_sample" in type(c).__scry_globals__
    """)
    assert out["SPEED"] == "255"
    assert out["CALLSIGN"] == "N123"
    assert out["TICKS"] == "10"


def test_pointeur_vers_une_structure_decrite(built, tmp_path):
    run(built, tmp_path, """
        import sut
        c = sut.cases
        p = c.g_current                  # g_current = &g_sample, pose par le C++
        assert p is not None
        p.from_ = 11
        assert c.g_sample.from_ == 11    # meme objet C++
        assert p.__address__ == c.g_sample.__address__
    """)


def test_structures_imbriquees_tableaux_de_structs_stl(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        tg, c = sut.testgen, sut.cases
        fp = c.g_plan
        fp.callsign = "AF123"                       # std::string
        fp.legs[2].phase = tg.FlightPlan.Phase.Climb
        fp.legs[2].from_.position.x = 3.0
        fp.payload.raw = 0x00020001
        assert (fp.payload.halves.lo, fp.payload.halves.hi) == (1, 2)
        assert len(fp.legs) == 16
        assert fp.legs[-1].phase == tg.FlightPlan.Phase.Cruise   # initialiseur par defaut
        d = fp.to_dict()
        assert d["legs"][2]["from_"]["position"]["x"] == 3.0
        c.g_sensors[2].value = 7.5                  # tableau global de structures
        assert len(c.g_sensors) == 4
    """)
    callsign, phase, raw = out["PLAN"].split()
    assert (callsign, int(raw)) == ("AF123", 0x00020001)
    assert int(phase) == 2      # Phase::Climb
    import struct
    sensor = built[1]["testgen::SensorSample"]
    raw = bytes.fromhex(out["SENSOR2"])
    assert struct.unpack_from("<d", raw, _field(sensor, "value").abs_offset)[0] == 7.5


def test_empreintes_et_stub(built, tmp_path):
    models = built[1]
    out = run(built, tmp_path, """
        import sut
        print("HASH", sut.__scry_layout_hashes__["cases::Sample"])
        print("SIZE", sut.cases.Sample.__scry_layout__["sizeof"])
    """)
    assert int(out["HASH"]) == models["cases::Sample"].layout_hash
    assert int(out["SIZE"]) == models["cases::Sample"].size
    stub = (built[3] / "sut.pyi").read_text(encoding="utf-8")
    assert 'g_sample: "cases.Sample"' in stub
    assert 'g_version: "int"  # const' in stub
    assert 'g_current: "Optional[cases.Sample]"' in stub


def test_heritage_prive_et_docstrings(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        child = c.g_child
        child.base_value = 3          # membre herite, ecrit en place
        child.weight = 2.5
        child.extra = 9
        assert "base_value" in c.Child.__scry_fields__
        h = c.g_hidden
        assert h.shown == 1
        assert not hasattr(h, "secret_")        # prive : jamais nomme
        assert "valeur portee par la base" in c.Child.base_value.__doc__
        assert c.Base.__doc__ == "Une base documentee."
        assert "enfant documente" in type(c).g_child.__doc__
    """)
    assert out["CHILD"] == "3 2.5 9"
