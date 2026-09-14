"""Runtime autotest, avec une fausse application sequencee et un faux 'sut'.

Chaque cycle de la fausse appli : le code metier (altitude += rate), puis
l'etape autotest (runner.tick()). C'est exactement l'ordre de l'appli reelle.
"""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from autotest import (Runner, ScenarioTimeout, check, cycles, diff, expect, record,
                      scenario, snapshot, until)


def _sut():
    return SimpleNamespace(inputs=SimpleNamespace(rate=0.0),
                           outputs=SimpleNamespace(altitude=0.0, valid=False))


def _run(scenarios, **kw):
    sut = _sut()
    runner = Runner(scenarios, sut=sut, log=lambda *_: None, **kw)

    def metier():
        sut.outputs.altitude += sut.inputs.rate
        sut.outputs.valid = sut.outputs.altitude >= 100

    runner.run_all(metier, max_cycles=10000)
    assert runner.finished
    return runner


def test_cycles_et_expect():
    @scenario
    async def montee(sut):
        sut.inputs.rate = 10.0
        await cycles(10)
        expect(sut.outputs.altitude, "altitude").near(100)

    r = _run([montee])
    assert [x.status for x in r.results] == ["passed"]
    assert r.results[0].cycles == 11 and r.exit_code == 0


def test_until_atteint():
    @scenario
    async def seuil(sut):
        sut.inputs.rate = 7.0
        await until(lambda: sut.outputs.valid, timeout=50)
        expect(sut.outputs.altitude).ge(100)

    assert _run([seuil]).results[0].ok


def test_until_timeout_et_message_lisible():
    @scenario
    async def bloque(sut):
        await until(lambda: sut.outputs.valid, timeout=5)

    result = _run([bloque]).results[0]
    assert result.status == "failed" and "5 cycles" in result.message


def test_expect_en_echec_dit_obtenu_et_attendu():
    @scenario
    async def faux(sut):
        sut.inputs.rate = 1.0
        await cycles(3)
        expect(sut.outputs.altitude, "altitude").near(50, tol=1)

    result = _run([faux]).results[0]
    assert result.status == "failed"
    assert result.message == "altitude = 3, attendu 50 +/- 1"


def test_check_note_et_continue():
    fin = []

    @scenario
    async def souple(sut):
        check(1, "a").eq(2)
        check(3, "b").lt(0)
        await cycles(1)
        fin.append(True)

    result = _run([souple]).results[0]
    assert fin == [True]
    assert result.status == "failed" and len(result.checks_failed) == 2


def test_exception_classee_en_erreur():
    @scenario
    async def casse(sut):
        raise RuntimeError("boum")

    result = _run([casse]).results[0]
    assert result.status == "error" and "boum" in result.message


def test_scenarios_en_sequence_et_code_de_sortie():
    ordre = []

    @scenario
    async def premier(sut):
        ordre.append("premier")
        await cycles(2)

    @scenario
    async def second(sut):
        ordre.append("second")
        expect(True).false()

    r = _run([premier, second])
    assert ordre == ["premier", "second"]
    assert [x.status for x in r.results] == ["passed", "failed"]
    assert r.exit_code == 1


def test_timeout_de_scenario():
    @scenario(timeout=3)
    async def long(sut):
        await cycles(10)

    result = _run([long]).results[0]
    assert result.status == "failed" and "3 cycles" in result.message


def test_stop_on_failure():
    @scenario
    async def a(sut):
        expect(0).eq(1)

    @scenario
    async def b(sut):
        pass

    assert [x.name for x in _run([a, b], stop_on_failure=True).results] == ["a"]


def test_attente_invalide():
    @scenario
    async def mauvais(sut):
        await _Autre()

    result = _run([mauvais]).results[0]
    assert result.status == "error" and "cycles() ou until()" in result.message


class _Autre(object):
    def __await__(self):
        return (yield "pas une attente")


def test_decorateur_refuse_une_fonction_synchrone():
    with pytest.raises(TypeError):
        @scenario
        def synchrone(sut):
            pass


def test_trace_echantillonnee_a_chaque_tick():
    traces = {}

    @scenario
    async def trace(sut):
        sut.inputs.rate = 2.0
        traces["alt"] = record("altitude", lambda: sut.outputs.altitude)
        await cycles(5)

    _run([trace])
    assert list(traces["alt"].values) == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]


def test_rapport_junit(tmp_path):
    @scenario
    async def ok(sut):
        pass

    @scenario
    async def ko(sut):
        expect(1, "x").eq(2)

    path = tmp_path / "rapport.xml"
    _run([ok, ko], report=str(path))
    root = ET.parse(path).getroot()
    assert root.get("tests") == "2" and root.get("failures") == "1"
    failure = root.find("testcase[@name='ko']/failure")
    assert failure.get("message") == "x = 1, attendu 2"


def test_decouverte_depuis_un_dossier_et_selection(tmp_path):
    (tmp_path / "test_vol.py").write_text(
        "from autotest import scenario, cycles\n"
        "@scenario\nasync def decollage(sut):\n    await cycles(1)\n"
        "@scenario(tags=['lent'])\nasync def croisiere(sut):\n    await cycles(1)\n",
        encoding="utf-8")
    (tmp_path / "helpers.py").write_text("x = 1\n", encoding="utf-8")
    assert [s.name for s in Runner.discover(str(tmp_path))] == ["decollage", "croisiere"]
    assert [x.name for x in _run(str(tmp_path), select="lent").results] == ["croisiere"]


def test_snapshot_et_diff():
    class Vue(object):
        def __init__(self, d):
            self.d = d

        def to_dict(self):
            return {"legs": [{"phase": p} for p in self.d], "alt": 1.0}

    avant = snapshot(Vue(["Cruise", "Cruise"]))
    apres = snapshot(Vue(["Cruise", "Climb"]))
    assert diff(avant, apres) == ["legs[1].phase : 'Cruise' -> 'Climb'"]
    assert diff({"a": 1.0}, {"a": 1.05}, tol=0.1) == []
