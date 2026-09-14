"""Scenarios de demonstration sur l'application legacy factice.

'sut' est le module embarque par l'application (autotest_glue.cpp) : sensor,
target, telemetry et plan sont ses globales C++, lues et ecrites en place.
"""

from autotest import check, cycles, expect, record, scenario, until


@scenario
async def au_sol_sans_capteur(sut):
    """Sans mesure valide, l'application reste en Preflight."""
    Phase = sut.testgen.FlightPlan.Phase
    sut.sensor.valid = False
    await cycles(1)
    expect(sut.telemetry.phase, "phase").eq(Phase.Preflight)


@scenario(timeout=100)
async def montee_puis_croisiere(sut):
    """Rampe d'altitude jusqu'a la consigne : Taxi, Climb, puis Cruise."""
    Phase = sut.testgen.FlightPlan.Phase
    sut.target.position.z = 3000.0
    sut.sensor.unit = sut.testgen.Unit.Feet
    sut.sensor.label = "ALT-1"
    sut.sensor.valid = True

    phases = record("phase", lambda: sut.telemetry.phase.value)
    for altitude in range(0, 3001, 250):
        sut.sensor.value = float(altitude)
        await cycles(1)
        if altitude == 1000:
            check(sut.telemetry.phase, "phase a 1000 ft").eq(Phase.Climb)

    await until(lambda: sut.telemetry.phase == Phase.Cruise, timeout=5)
    expect(sut.plan.payload.halves.lo, "altitude publiee").eq(3000)
    # La phase n'a fait que monter : jamais de retour en arriere.
    values = list(phases.values)
    expect(values, "suite des phases").satisfies(
        lambda v: all(a <= b for a, b in zip(v, v[1:])), "une suite croissante")


@scenario
async def conversion_metres(sut):
    """1000 m sont publies en pieds."""
    sut.sensor.unit = sut.testgen.Unit.Meters
    sut.sensor.value = 1000.0
    sut.sensor.valid = True
    await cycles(1)
    expect(sut.plan.payload.halves.lo, "altitude en pieds").near(3281, tol=1)
