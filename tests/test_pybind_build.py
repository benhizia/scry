"""Integration pybind11 : compile un vrai module a partir des bindings generes,
ecrit depuis Python, puis relit les octets aux offsets du modele.

C'est la preuve de bout en bout : si Python ecrit la ou le modele dit que se
trouve le membre, les bindings, le modele et le compilateur sont d'accord.

Lent, une compilation pybind11 prend quelques dizaines de secondes. Lance
seulement avec SCRY_INTEGRATION=1.
"""

import importlib.util
import os
import struct
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from scry.runtime import memory
from scry.runtime.memory import BufferSource

ROOT = Path(__file__).resolve().parent.parent
HEADERS = [ROOT / "Data" / "test_structs_complexe.h", ROOT / "tests" / "data" / "pybind_cases.h"]

pytestmark = pytest.mark.skipif(os.environ.get("SCRY_INTEGRATION") != "1",
                                reason="compilation pybind11 : SCRY_INTEGRATION=1 pour lancer")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    pybind11 = pytest.importorskip("pybind11")
    pytest.importorskip("numpy")
    from scry import verify
    from scry.codegen import pybind
    from scry.config import load_config
    from scry.parsing import msvc_env
    from scry.parsing.introspect import Introspector, index_by_name
    from scry.viewer.build import runtime_flags

    out = tmp_path_factory.mktemp("pybind")
    base = ROOT / "scry.ini"
    cfg = load_config(base if base.is_file() else ROOT / "scry.ini.example")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SCRY_PATHS_OUTPUT", str(out))
        structs = Introspector(cfg).parse([str(h) for h in HEADERS])
        pybind.generate(structs, cfg)

    glue = out / "glue.cpp"
    glue.write_text('#include "scry_pybind.generated.h"\n\n'
                    "PYBIND11_MODULE(scry_cases, m)\n{\n"
                    "    %s::bind::register_types(m);\n}\n" % cfg.cpp_namespace,
                    encoding="utf-8")
    target = out / ("scry_cases" + sysconfig.get_config_var("EXT_SUFFIX"))
    includes = ([str(out), pybind11.get_include(), sysconfig.get_paths()["include"]]
                + [d for h in HEADERS for d in [str(h.parent)]])
    cmd = ([str(msvc_env.prepare_cl(cfg)), "/nologo", "/LD", "/EHsc", "/O1", "/bigobj",
            "/utf-8", msvc_env._cl_std_flag(cfg.std)] + runtime_flags(cfg)
           + ["/I%s" % d for d in includes]
           + [str(glue), "/Fe%s" % target, "/Fo%s\\" % out,
              "/link", "/LIBPATH:%s" % (Path(sys.base_prefix) / "libs")])
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=str(out))
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, "\n".join(verify.extract_errors(output)[:30]) or output[-4000:]

    spec = importlib.util.spec_from_file_location("scry_cases", str(target))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, index_by_name(structs)


def _field(struct_model, name):
    return next(f for f, _ in struct_model.walk() if f.name == name)


def _sample(built):
    mod, models = built
    buf = bytearray(mod.cases.Sample.__scry_layout__["sizeof"])
    return mod, models["cases::Sample"], buf, mod.cases.Sample.from_buffer(buf)


def test_scalaires_enum_chaine_bits(built):
    mod, model_, buf, s = _sample(built)
    s.speed = mod.cases.Speed.Fast
    s.mode, s.armed, s.level = 5, 1, 0xABC
    s.tag = "RWY27"
    s.from_ = -7

    src = BufferSource(bytes(buf))
    assert memory.decode(src, _field(model_, "speed")) == "Fast (10)"
    assert memory.decode(src, _field(model_, "mode")) == "5"
    assert memory.decode(src, _field(model_, "armed")) == "1"
    assert memory.decode(src, _field(model_, "level")) == str(0xABC)
    assert memory.decode(src, _field(model_, "tag")) == '"RWY27"'
    assert memory.decode(src, _field(model_, "from")) == "-7"
    assert (s.speed, s.level, s.tag, s.from_) == (mod.cases.Speed.Fast, 0xABC, "RWY27", -7)

    with pytest.raises(ValueError):
        s.tag = "x" * 8                     # 7 caracteres au plus
    with pytest.raises(AttributeError):
        s.not_a_field = 1                   # une faute de frappe ne passe pas


def test_vues_numpy_sans_copie(built):
    _, model_, buf, s = _sample(built)
    s.values[2] = 4.5                       # ecrit a travers la vue
    s.grid[1, 2] = -3
    s.vec = [1.0, 2.0, 3.0]

    assert struct.unpack_from("<d", buf, _field(model_, "values").abs_offset + 16)[0] == 4.5
    assert struct.unpack_from("<h", buf, _field(model_, "grid").abs_offset + 5 * 2)[0] == -3
    assert struct.unpack_from("<3f", buf, _field(model_, "vec").abs_offset) == (1.0, 2.0, 3.0)
    assert s.grid.shape == (2, 3)
    with pytest.raises(ValueError):
        s.values = [1.0, 2.0]               # taille verifiee


def test_union_et_struct_anonymes(built):
    _, model_, buf, s = _sample(built)
    s.raw = 0x3F800000
    assert s.as_float == 1.0
    s.pair.lo, s.pair.hi = 1, 2
    assert struct.unpack_from("<HH", buf, _field(model_, "pair").abs_offset) == (1, 2)


def test_structures_imbriquees_tableaux_stl(built):
    mod, _ = built
    tg = mod.testgen
    fp = tg.FlightPlan()                    # std::string : pas de from_buffer
    assert not hasattr(tg.FlightPlan, "from_buffer")
    fp.callsign = "AF123"
    fp.legs[2].phase = tg.FlightPlan.Phase.Climb
    fp.legs[2].from_.position.x = 3.0
    fp.payload.raw = 0x00020001
    fp.origin.lat = 1.5

    assert (fp.payload.halves.lo, fp.payload.halves.hi) == (1, 2)
    assert len(fp.legs) == 16
    assert fp.legs[-1].phase == tg.FlightPlan.Phase.Cruise   # initialiseur par defaut
    d = fp.to_dict()
    assert d["callsign"] == "AF123"
    assert d["legs"][2]["phase"] == "Climb"
    assert d["legs"][2]["from_"]["position"]["x"] == 3.0
    assert d["origin"]["lat"] == 1.5


def test_empreintes_layout_et_template(built):
    mod, models = built
    for name in ("testgen::SensorSample", "cases::Sample"):
        assert mod.__scry_layout_hashes__[name] == models[name].layout_hash
    assert mod.cases.Sample.__scry_layout__["sizeof"] == models["cases::Sample"].size

    ring = mod.testgen.detail.RingBuffer_SensorSample_8
    buf = bytearray(ring.__scry_layout__["sizeof"])
    view = ring.from_buffer(buf)
    view.data[3].value = 7.0
    assert struct.unpack_from("<d", buf, 3 * 56 + 8)[0] == 7.0
    assert [item.value for item in view.data][3] == 7.0
