"""Runtime autotest, avec une fausse application sequencee et un faux 'sut'.

Chaque cycle de la fausse appli : le code metier (altitude += rate), puis
l'etape autotest (runner.tick()). C'est exactement l'ordre de l'appli reelle.
"""

import os
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from autotest import (Runner, ScenarioTimeout, TickStats, check, cycles, diff, expect,
                      record, scenario, snapshot, until)


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


# -- rechargement a chaud ----------------------------------------------------
def _ecrire(path, corps):
    """Ecrit un fichier de scenario et pousse son horodatage, pour que le
    changement soit visible quelle que soit la granularite du systeme."""
    path.write_text(corps, encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


SCENARIO = ("from autotest import scenario, cycles\n"
            "@scenario\nasync def essai(sut):\n"
            "    sut.inputs.rate = %s\n    await cycles(1)\n")


def _veille(tmp_path, **kw):
    """Runner en veille sur un dossier, avec un faux sut et sans journal."""
    sut = _sut()
    fichier = tmp_path / "test_essai.py"
    _ecrire(fichier, SCENARIO % "1.0")
    runner = Runner(str(tmp_path), sut=sut, log=lambda *_: None, watch=True,
                    watch_every=1, **kw)
    return runner, sut, fichier


def test_veille_ne_se_declare_jamais_terminee(tmp_path):
    """C'est la condition du rechargement : si tick() rendait False, l'appli
    s'arreterait avant d'avoir pu recharger quoi que ce soit."""
    runner, sut, _ = _veille(tmp_path)
    for _ in range(20):
        assert runner.tick() is True
    assert runner.finished and len(runner.results) == 1
    assert sut.inputs.rate == 1.0


def test_un_fichier_modifie_relance_une_passe(tmp_path):
    runner, sut, fichier = _veille(tmp_path)
    while not runner.finished:
        runner.tick()
    assert (runner.passes, sut.inputs.rate) == (1, 1.0)

    _ecrire(fichier, SCENARIO % "7.5")
    runner.tick()                          # le poll voit la date changer
    assert runner.passes == 2 and runner.results == []
    while not runner.finished:
        runner.tick()
    # Le nouveau code a bien tourne : c'est la valeur du fichier reecrit.
    assert sut.inputs.rate == 7.5
    assert [r.status for r in runner.results] == ["passed"]


def test_le_compteur_de_cycles_survit_au_rechargement(tmp_path):
    """Le cycle est celui de l'application, que le rechargement n'interrompt
    pas : c'est tout l'interet, le simulateur garde son etat."""
    runner, _, fichier = _veille(tmp_path)
    while not runner.finished:
        runner.tick()
    avant = runner.cycle
    _ecrire(fichier, SCENARIO % "2.0")
    runner.tick()
    assert runner.cycle == avant + 1


def test_un_fichier_ajoute_ou_supprime_est_vu(tmp_path):
    """Un importlib.reload ne verrait ni l'ajout ni la suppression : le
    rechargement purge les modules et relit le dossier."""
    runner, _, fichier = _veille(tmp_path)
    while not runner.finished:
        runner.tick()
    _ecrire(tmp_path / "test_autre.py", SCENARIO.replace("essai", "autre") % "3.0")
    runner.tick()
    assert len(runner._pending) + (1 if runner._current else 0) == 2
    while not runner.finished:
        runner.tick()
    assert sorted(r.name for r in runner.results) == ["autre", "essai"]

    (tmp_path / "test_autre.py").unlink()
    runner.tick()
    while not runner.finished:
        runner.tick()
    assert [r.name for r in runner.results] == ["essai"]


def test_rechargement_en_pleine_execution_abandonne_le_scenario(tmp_path):
    """La coroutine en vol tient des fonctions de l'ancien module : la
    reprendre executerait du code qui n'existe plus."""
    sut = _sut()
    fichier = tmp_path / "test_long.py"
    _ecrire(fichier, "from autotest import scenario, cycles\n"
                     "@scenario\nasync def long(sut):\n    await cycles(500)\n")
    runner = Runner(str(tmp_path), sut=sut, log=lambda *_: None, watch=True, watch_every=1)
    for _ in range(5):
        runner.tick()
    assert runner._current is not None and not runner.results

    _ecrire(fichier, SCENARIO % "4.0")
    runner.tick()
    # La passe neuve demarre dans le meme tick ; 'long' est abandonne sans
    # laisser de resultat, puisqu'il n'a ni reussi ni echoue.
    assert runner.passes == 2
    while not runner.finished:
        runner.tick()
    assert [r.name for r in runner.results] == ["essai"]
    assert sut.inputs.rate == 4.0


def test_reload_explicite_sans_veille(tmp_path):
    """reload() s'appelle aussi a la main, depuis l'application : une touche,
    une commande reseau. La veille n'est qu'un declencheur parmi d'autres."""
    sut = _sut()
    _ecrire(tmp_path / "test_essai.py", SCENARIO % "1.0")
    runner = Runner(str(tmp_path), sut=sut, log=lambda *_: None)
    while runner.tick():
        pass
    assert runner.finished and runner.passes == 1

    _ecrire(tmp_path / "test_essai.py", SCENARIO % "9.0")
    assert runner.reload() == 2
    assert not runner.finished
    while runner.tick():
        pass
    assert sut.inputs.rate == 9.0


def test_le_rapport_est_reecrit_a_chaque_passe(tmp_path):
    """Les resultats d'une passe decrivent du code qui n'existe plus : ils sont
    remplaces, pas cumules."""
    rapport = tmp_path / "rapport.xml"
    dossier = tmp_path / "scenarios"
    dossier.mkdir()
    sut = _sut()
    _ecrire(dossier / "test_essai.py", SCENARIO % "1.0")
    runner = Runner(str(dossier), sut=sut, log=lambda *_: None, watch=True,
                    watch_every=1, report=str(rapport))
    while not runner.finished:
        runner.tick()
    assert ET.parse(rapport).getroot().get("tests") == "1"

    _ecrire(dossier / "test_autre.py", SCENARIO.replace("essai", "autre") % "2.0")
    runner.tick()
    while not runner.finished:
        runner.tick()
    root = ET.parse(rapport).getroot()
    assert root.get("tests") == "2"
    assert sorted(c.get("name") for c in root.findall("testcase")) == ["autre", "essai"]


# -- budget de temps par tick ------------------------------------------------
def test_histogramme_moyenne_et_pire_cas():
    stats = TickStats()
    for ms, cycle in [(0.05, 1), (0.3, 2), (0.3, 3), (7.0, 4), (120.0, 5), (0.05, 6)]:
        stats.add(ms, cycle)
    assert stats.count == 6
    assert (stats.worst_ms, stats.worst_cycle) == (120.0, 5)
    assert stats.mean_ms == pytest.approx(sum([0.05, 0.3, 0.3, 7.0, 120.0, 0.05]) / 6)
    # Seules les tranches non vides sortent, et une valeur hors des bornes
    # tombe dans la derniere.
    assert stats.histogram() == [("0.00-0.10 ms", 2), ("0.25-0.50 ms", 2),
                                 ("5.00-10.00 ms", 1), (">= 50.00 ms", 1)]
    assert "pire 120.000 ms au cycle 5" in stats.summary()
    assert TickStats().summary() == "aucun tick mesure"


def test_les_ticks_sont_mesures_sans_budget():
    """L'histogramme ne depend pas du budget : il dit ou part le temps, meme
    quand personne n'a fixe de limite."""
    @scenario
    async def court(sut):
        await cycles(3)

    r = _run([court])
    stats = r.results[0].ticks
    assert stats.count == r.results[0].cycles
    assert stats.worst_ms > 0.0 and stats.mean_ms > 0.0


def test_depassement_compte_et_impute_au_bon_scenario():
    @scenario
    async def lent(sut):
        time.sleep(0.01)          # 10 ms, bien au-dela du budget
        await cycles(1)

    @scenario
    async def rapide(sut):
        await cycles(1)

    r = _run([lent, rapide], tick_budget_ms=1.0)
    lent_res, rapide_res = r.results
    assert lent_res.slow_ticks >= 1 and lent_res.ticks.worst_ms > 5.0
    # Le scenario suivant n'herite pas du cout du precedent.
    assert rapide_res.slow_ticks == 0


def test_profil_du_tick_qui_suit_le_depassement():
    """On ne peut pas profiler le passe : c'est le tick suivant qui est
    echantillonne, et il execute le meme code."""
    @scenario
    async def lent(sut):
        for _ in range(4):
            _brule(0.01)
            await cycles(1)

    r = _run([lent], tick_budget_ms=1.0, profile_slow=True)
    profil = r.results[0].profile
    assert profil and "tick de " in profil
    assert "_brule" in profil                      # la fonction coupable est nommee
    assert r.results[0].slow_ticks >= 2


def test_pas_de_profil_sans_l_option():
    @scenario
    async def lent(sut):
        _brule(0.01)
        await cycles(1)

    assert _run([lent], tick_budget_ms=1.0).results[0].profile == ""


def test_max_slow_ticks_coupe_le_scenario():
    @scenario
    async def gourmand(sut):
        for _ in range(100):
            _brule(0.01)
            await cycles(1)

    r = _run([gourmand], tick_budget_ms=1.0, max_slow_ticks=3)
    result = r.results[0]
    assert result.status == "failed"
    assert "au-dela de 1.000 ms" in result.message
    # Coupe bien avant les 100 cycles demandes.
    assert result.cycles < 20


def test_un_scenario_dans_le_budget_n_est_pas_coupe():
    @scenario
    async def sobre(sut):
        await cycles(5)

    r = _run([sobre], tick_budget_ms=50.0, max_slow_ticks=1)
    assert [x.status for x in r.results] == ["passed"]
    assert r.results[0].slow_ticks == 0


def test_rapport_porte_l_histogramme_et_le_profil(tmp_path):
    @scenario
    async def lent(sut):
        for _ in range(3):
            _brule(0.01)
            await cycles(1)

    path = tmp_path / "rapport.xml"
    _run([lent], report=str(path), tick_budget_ms=1.0, profile_slow=True)
    case = ET.parse(path).getroot().find("testcase[@name='lent']")
    noms = {p.get("name") for p in case.findall("properties/property")}
    assert {"tick_mean_ms", "tick_worst_ms", "tick_worst_cycle", "slow_ticks"} <= noms
    sortie = case.find("system-out").text
    assert "Duree des ticks" in sortie and "ms " in sortie
    assert "Profil du tick qui suit le premier depassement" in sortie


def _brule(secondes: float):
    """Occupe le processeur, plutot que de dormir : un sleep ne se verrait pas
    dans un profil, et ce sont des calculs que l'on veut attraper."""
    fin = time.perf_counter() + secondes
    total = 0.0
    while time.perf_counter() < fin:
        total += 1.0
    return total
