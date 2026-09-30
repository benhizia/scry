"""Ordonnanceur de scenarios, avance d'un pas par cycle de l'application.

Chaque scenario est une coroutine. 'await cycles(10)' rend la main au runner,
qui la reprend dix ticks plus tard ; 'await until(cond, timeout)' la reprend
des que cond() est vraie. Il n'y a ni thread ni boucle asyncio : le runner fait
avancer les coroutines a la main (send, throw), dans le thread du sequenceur.
Tout est donc deterministe, et un tick correspond exactement a un cycle.

Les scenarios s'executent l'un apres l'autre, dans l'ordre de declaration. Le
suivant demarre au tick qui suit la fin du precedent.

Avec watch=True, le runner reste en veille au lieu de se declarer termine : il
surveille la date des fichiers test_*.py et repart d'une passe neuve des qu'un
seul change. On corrige un scenario, on l'enregistre, et il rejoue dans la
seconde, sans relancer le simulateur, qui garde tout son etat.
"""

import importlib.util
import inspect
import os
import sys
import time
import traceback
from typing import Callable, Dict, List, Optional

from autotest import junit

PASSED, FAILED, ERROR = "passed", "failed", "error"

# Prefixe des modules de scenarios dans sys.modules. Le rechargement purge
# tout ce qui commence par la ; les modules d'aide importes par un scenario
# sous leur propre nom, eux, ne sont pas relus.
_MODULE_PREFIX = "autotest_scenarios."

# Runner en cours de tick : check() et record() s'y rattachent.
_ACTIVE = None


# ---------------------------------------------------------------------------
# Declaration des scenarios
# ---------------------------------------------------------------------------
class Scenario(object):
    def __init__(self, func, name=None, timeout=None, tags=()):
        self.func = func
        self.name = name or func.__name__
        self.timeout = timeout              # en cycles, None : pas de limite
        self.tags = tuple(tags)
        self.doc = inspect.getdoc(func) or ""
        self.module = func.__module__


def scenario(func=None, *, name=None, timeout=None, tags=()):
    """Declare un scenario. Utilisable nu (@scenario) ou parametre
    (@scenario(timeout=500, tags=["vol"]))."""
    def wrap(f):
        if not inspect.iscoroutinefunction(f):
            raise TypeError("@scenario attend une fonction 'async def' : %s" % f.__name__)
        f.__autotest__ = Scenario(f, name, timeout, tags)
        return f
    return wrap(func) if func is not None else wrap


# ---------------------------------------------------------------------------
# Attentes
# ---------------------------------------------------------------------------
class _Wait(object):
    def __await__(self):
        return (yield self)


class Cycles(_Wait):
    def __init__(self, count: int):
        if count < 1:
            raise ValueError("cycles() attend au moins 1, recu %d" % count)
        self.count = count


class Until(_Wait):
    def __init__(self, condition: Callable[[], bool], timeout: int, message: Optional[str]):
        if timeout < 1:
            raise ValueError("until() attend un timeout d'au moins 1 cycle")
        self.condition = condition
        self.timeout = timeout
        self.message = message


def cycles(count: int = 1) -> Cycles:
    """Rend la main pour 'count' cycles de l'application."""
    return Cycles(int(count))


def until(condition: Callable[[], bool], timeout: int, message: Optional[str] = None) -> Until:
    """Rend la main jusqu'a ce que condition() soit vraie, 'timeout' cycles au
    plus. Au-dela, UntilTimeout est levee dans le scenario."""
    return Until(condition, int(timeout), message)


class UntilTimeout(AssertionError):
    pass


class ScenarioTimeout(AssertionError):
    pass


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------
class Trace(object):
    """Valeur echantillonnee a chaque tick, du record() jusqu'a la fin du
    scenario. values donne un tableau numpy si numpy est disponible."""

    def __init__(self, name: str, getter: Callable):
        self.name = name
        self.getter = getter
        self.cycles = []      # type: List[int]
        self._values = []

    def sample(self, cycle: int):
        value = self.getter()
        copy = getattr(value, "copy", None)     # vue numpy : on fige la valeur
        self._values.append(copy() if callable(copy) else value)
        self.cycles.append(cycle)

    @property
    def values(self):
        try:
            import numpy
            return numpy.asarray(self._values)
        except Exception:
            return list(self._values)


def record(name: str, getter: Callable) -> Trace:
    """Enregistre getter() a chaque tick du scenario en cours."""
    run = _ACTIVE._current if _ACTIVE is not None else None
    if run is None:
        raise RuntimeError("record() s'appelle depuis un scenario en cours")
    trace = Trace(name, getter)
    trace.sample(_ACTIVE.cycle)
    run.result.traces[name] = trace
    return trace


# ---------------------------------------------------------------------------
# Resultats
# ---------------------------------------------------------------------------
class ScenarioResult(object):
    def __init__(self, scenario: Scenario, start_cycle: int):
        self.scenario = scenario
        self.name = scenario.name
        self.status = PASSED
        self.message = ""
        self.details = ""
        self.checks_failed = []     # type: List[str]
        self.start_cycle = start_cycle
        self.cycles = 0
        self.seconds = 0.0
        self.slow_ticks = 0
        self.traces = {}            # type: Dict[str, Trace]

    @property
    def ok(self) -> bool:
        return self.status == PASSED


class _Run(object):
    def __init__(self, scenario, coro, cycle):
        self.scenario = scenario
        self.coro = coro
        self.result = ScenarioResult(scenario, cycle)
        self.wait = None
        self.resume_at = 0
        self.deadline = 0
        self.started = time.perf_counter()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class Runner(object):
    """Execute les scenarios, un tick par cycle de l'application.

    scenarios : dossier ou fichier de test_*.py, module, ou liste de
    fonctions @scenario. sut : objet passe aux scenarios ; par defaut le
    module 'sut' (PYBIND11_EMBEDDED_MODULE de l'application).
    """

    def __init__(self, scenarios="scenarios", sut=None, report: Optional[str] = None,
                 select: Optional[str] = None, tick_budget_ms: float = 0.0,
                 stop_on_failure: bool = False, sut_module: str = "sut", log=print,
                 watch: bool = False, watch_every: int = 25):
        self._source = scenarios
        self._select = select
        self.sut = sut
        self.sut_module = sut_module
        self.report = report
        self.tick_budget_ms = float(tick_budget_ms or 0.0)
        self.stop_on_failure = stop_on_failure
        self.log = log
        self.cycle = 0
        self.results = []           # type: List[ScenarioResult]
        self.finished = False
        self._current = None        # type: Optional[_Run]
        self._closed = False
        # Mode veille : le runner ne se declare jamais termine, il relance une
        # passe des qu'un fichier de scenario change. watch_every espace les
        # stat() du disque, comptes en cycles de l'application.
        self.watch = bool(watch)
        self.watch_every = max(1, int(watch_every))
        self.passes = 1
        self._stamps = self._file_stamps()
        self._pending = self._select_scenarios()
        self.log("[autotest] %d scenario(s)%s"
                 % (len(self._pending), ", veille sur les fichiers" if self.watch else ""))

    # -- decouverte ---------------------------------------------------------
    @staticmethod
    def scenario_files(source) -> List[str]:
        """Fichiers test_*.py derriere 'source', [] si source n'est pas un
        chemin. C'est ce que le mode veille surveille."""
        if isinstance(source, (list, tuple)) or inspect.ismodule(source):
            return []
        path = os.fspath(source)
        if os.path.isdir(path):
            return sorted(os.path.join(path, n) for n in os.listdir(path)
                          if n.startswith("test_") and n.endswith(".py"))
        if os.path.isfile(path):
            return [path]
        raise FileNotFoundError("scenarios introuvables : %s" % path)

    @staticmethod
    def discover(source) -> List[Scenario]:
        if isinstance(source, (list, tuple)):
            return [_as_scenario(item) for item in source]
        if inspect.ismodule(source):
            return _from_module(source)
        found = []
        for file in Runner.scenario_files(source):
            found.extend(_from_module(_load(file)))
        return found

    # -- rechargement a chaud --------------------------------------------------
    def _select_scenarios(self) -> List[Scenario]:
        return [s for s in self.discover(self._source)
                if not self._select or self._select in s.name or self._select in s.tags]

    def _file_stamps(self) -> Dict[str, tuple]:
        """(mtime, taille) par fichier de scenario. La taille double le mtime :
        deux ecritures dans la meme granularite d'horodatage se distinguent
        alors quand le contenu a change de longueur."""
        stamps = {}
        try:
            files = self.scenario_files(self._source)
        except FileNotFoundError:
            return stamps
        for path in files:
            try:
                st = os.stat(path)
                stamps[path] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
        return stamps

    def reload(self) -> int:
        """Relit les scenarios sur le disque et repart d'une passe neuve.

        Le scenario en cours est abandonne : sa coroutine tient des fonctions de
        l'ancien module, et la reprendre executerait l'ancien code. Les
        resultats de la passe precedente sont REMPLACES et non cumules, car ils
        decrivent du code qui n'existe plus ; le rapport est reecrit a la fin de
        chaque passe.

        Le compteur de cycles, lui, continue : c'est celui de l'application, que
        le rechargement n'interrompt pas. C'est tout l'interet, d'ailleurs : le
        simulateur garde son etat, on ne recharge que les scenarios.

        Retourne le numero de la nouvelle passe.
        """
        if self._current is not None and self._current.coro is not None:
            self._current.coro.close()
        self._current = None
        # Purger les modules deja charges : les relire suffit a prendre en
        # compte un fichier modifie, ajoute ou supprime, ce qu'un
        # importlib.reload ne ferait pas pour les deux derniers cas.
        for name in [n for n in sys.modules if n.startswith(_MODULE_PREFIX)]:
            del sys.modules[name]
        self._stamps = self._file_stamps()
        self._pending = self._select_scenarios()
        self.results = []
        self.finished = False
        self._closed = False
        self.passes += 1
        self.log("[autotest] passe %d : %d scenario(s) recharge(s)"
                 % (self.passes, len(self._pending)))
        return self.passes

    def _poll(self):
        """Relance une passe si un fichier de scenario a bouge."""
        stamps = self._file_stamps()
        if stamps == self._stamps:
            return
        changed = sorted(set(stamps) ^ set(self._stamps)
                         | {p for p in stamps if p in self._stamps
                            and stamps[p] != self._stamps[p]})
        self.log("[autotest] modifie : %s"
                 % ", ".join(os.path.basename(p) for p in changed))
        self.reload()

    # -- boucle ---------------------------------------------------------------
    def tick(self) -> bool:
        """Un cycle de l'application. Retourne False quand tout est termine.

        En mode veille, il ne retourne jamais False : l'application continue de
        tourner, et le runner attend une modification des scenarios.
        """
        global _ACTIVE
        self.cycle += 1
        if self.watch and self.cycle % self.watch_every == 0:
            self._poll()
        if self.finished:
            return bool(self.watch)
        start = time.perf_counter()
        _ACTIVE = self
        try:
            self._step()
        finally:
            _ACTIVE = None
        if self.tick_budget_ms:
            elapsed = (time.perf_counter() - start) * 1000.0
            if elapsed > self.tick_budget_ms and self._current is not None:
                self._current.result.slow_ticks += 1
        if self.finished:
            self._close()
            return bool(self.watch)
        return True

    def run_all(self, app_cycle: Callable[[], None] = None, max_cycles: int = 1000000) -> int:
        """Boucle de commodite hors application : app_cycle() puis tick()."""
        for _ in range(max_cycles):
            if app_cycle is not None:
                app_cycle()
            if not self.tick():
                break
        return self.exit_code

    @property
    def exit_code(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    # -- mecanique --------------------------------------------------------------
    def _sut(self):
        if self.sut is None:
            self.sut = importlib.import_module(self.sut_module)
        return self.sut

    def _step(self):
        run = self._current
        if run is None:
            if not self._pending:
                self.finished = True
                return
            sc = self._pending.pop(0)
            self.log("[autotest] >> %s" % sc.name)
            try:
                coro = sc.func(self._sut())
            except Exception as exc:
                run = self._current = _Run(sc, None, self.cycle)
                self._end(run, exc)
                return
            run = self._current = _Run(sc, coro, self.cycle)
            self._resume(run)
            return

        for trace in run.result.traces.values():
            trace.sample(self.cycle)

        wait = run.wait
        if isinstance(wait, Cycles):
            if self.cycle >= run.resume_at:
                self._resume(run)
        elif isinstance(wait, Until):
            try:
                reached = bool(wait.condition())
            except Exception as exc:
                self._throw(run, exc)
                return
            if reached:
                self._resume(run)
            elif self.cycle >= run.deadline:
                self._throw(run, UntilTimeout(
                    wait.message or "condition non atteinte en %d cycles" % wait.timeout))

        limit = run.scenario.timeout
        if run is self._current and limit and self.cycle - run.result.start_cycle >= limit:
            self._throw(run, ScenarioTimeout("scenario non termine en %d cycles" % limit))

    def _resume(self, run: _Run):
        try:
            wait = run.coro.send(None)
        except StopIteration:
            self._end(run, None)
            return
        except BaseException as exc:
            self._end(run, exc)
            return
        self._arm(run, wait)

    def _throw(self, run: _Run, exc: BaseException):
        try:
            wait = run.coro.throw(exc)
        except StopIteration:
            self._end(run, None)
            return
        except BaseException as caught:
            self._end(run, caught)
            return
        self._arm(run, wait)

    def _arm(self, run: _Run, wait):
        run.wait = wait
        if isinstance(wait, Cycles):
            run.resume_at = self.cycle + wait.count
        elif isinstance(wait, Until):
            run.deadline = self.cycle + wait.timeout
        else:
            self._throw(run, TypeError("un scenario n'attend que cycles() ou until(), "
                                       "recu %r" % (wait,)))

    def _end(self, run: _Run, exc: Optional[BaseException]):
        result = run.result
        result.cycles = self.cycle - result.start_cycle + 1
        result.seconds = time.perf_counter() - run.started
        if exc is None:
            if result.checks_failed:
                result.status = FAILED
                result.message = "%d verification(s) en echec" % len(result.checks_failed)
        elif isinstance(exc, AssertionError):
            result.status = FAILED
            result.message = str(exc) or type(exc).__name__
            result.details = _traceback(exc)
        else:
            result.status = ERROR
            result.message = "%s: %s" % (type(exc).__name__, exc)
            result.details = _traceback(exc)
        if run.coro is not None:
            run.coro.close()
        self.results.append(result)
        self._current = None
        self.log("[autotest] %s %s (%d cycles)%s"
                 % ({PASSED: "OK   ", FAILED: "ECHEC", ERROR: "ERREUR"}[result.status],
                    result.name, result.cycles,
                    (" : " + result.message) if result.message else ""))
        for message in result.checks_failed:
            self.log("[autotest]        - %s" % message)
        if not result.ok and self.stop_on_failure:
            self._pending.clear()

    def _soft_failure(self, message: str):
        if self._current is not None:
            self._current.result.checks_failed.append(message)

    def _close(self):
        if self._closed:
            return
        self._closed = True
        passed = sum(1 for r in self.results if r.ok)
        self.log("[autotest] termine : %d reussi(s), %d en echec, sur %d cycles"
                 % (passed, len(self.results) - passed, self.cycle))
        if self.report:
            junit.write(self.results, self.report)
            self.log("[autotest] rapport : %s" % os.path.abspath(self.report))
        if self.watch:
            self.log("[autotest] veille : en attente d'une modification des scenarios")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def _as_scenario(item) -> Scenario:
    if isinstance(item, Scenario):
        return item
    meta = getattr(item, "__autotest__", None)
    if meta is None:
        raise TypeError("%r n'est pas un @scenario" % (item,))
    return meta


def _from_module(module) -> List[Scenario]:
    return [obj.__autotest__ for obj in vars(module).values()
            if getattr(obj, "__autotest__", None) is not None]


def _load(path: str):
    name = _MODULE_PREFIX + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
