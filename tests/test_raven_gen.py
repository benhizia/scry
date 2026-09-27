"""scry raven : descripteur .rvndesc et glue de publication."""
import os

import pytest

import toolchain
from scry.codegen import raven

pytestmark = toolchain.needs_castxml

HEADER = os.path.join(os.path.dirname(__file__), "..", "raven", "demo", "sim_state.h")


@pytest.fixture(scope="module")
def variables():
    from scry.config import load_config
    from scry.parsing.introspect import Introspector
    it = Introspector(load_config())
    it.parse([HEADER])
    return it.variables


def test_descripteur(variables):
    text, placed, frame_size, schema = raven.build(
        raven.select_channels(variables, ["g_flight", "g_sim"]))
    lines = text.splitlines()
    assert lines[0] == "rvndesc 1"
    assert lines[1] == "schema 0x%016X" % schema
    assert "frame_size 72" in lines
    assert "item 1 Running" in lines
    assert "channel 1 56 12 3 g_sim" in lines
    assert "field 4 1 float 24 4 1 -1 ft pos.alt" in lines      # unite relue du commentaire
    assert "field 7 -1 float 36 4 4 -1 kg fuel" in lines        # tableau de scalaires
    assert lines[-1] == "end"
    assert [off for _, off in placed] == [0, 56]


def test_canal_inconnu(variables):
    with pytest.raises(ValueError):
        raven.select_channels(variables, ["g_absent"])


def test_glue(variables, tmp_path):
    written = raven.generate(variables, ["g_sim"], str(tmp_path), "t", [HEADER])
    glue = open(written[1]).read()
    assert "static_assert(sizeof(g_sim) == 12" in glue
    assert "offsetof(decltype(g_sim), scenario) == 8" in glue
    assert "std::memcpy(f + 0, &g_sim, sizeof(g_sim));" in glue
