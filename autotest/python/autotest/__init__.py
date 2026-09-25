"""Autotest embarque : scenarios Python pilotes par le sequenceur d'une appli C++.

L'application appelle Runner.tick() une fois par cycle, a son etape autotest,
quand le code metier a fini. Les scenarios lisent et ecrivent directement ses
structures via les bindings generes par Scry (scry gen --pybind).

    from autotest import scenario, cycles, until, expect, check

    @scenario
    async def montee(sut):
        sut.inputs.rate = 10.0
        await cycles(10)                                  # dix cycles de l'appli
        expect(sut.outputs.altitude, "altitude").near(100, tol=0.5)
        await until(lambda: sut.outputs.valid, timeout=50)

Le runtime est du Python pur : il se teste sans compiler, avec un faux 'sut'.
"""

from autotest.expect import ExpectationError, check, expect
from autotest.runner import (Runner, Scenario, ScenarioResult, ScenarioTimeout, UntilTimeout,
                             cycles, record, scenario, until)
from autotest.snapshot import diff, snapshot

__all__ = [
    "Runner", "Scenario", "ScenarioResult", "ScenarioTimeout", "UntilTimeout",
    "scenario", "cycles", "until", "record",
    "expect", "check", "ExpectationError",
    "snapshot", "diff",
]
