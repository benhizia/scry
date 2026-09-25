"""Scenarios de demonstration sur l'application legacy factice.

'sut' est le module embarque genere par Scry (scry gen --pybind) : chaque
variable globale de legacy_app.h y est, par reference, sous le namespace C++
qui la declare. sut.app.g_sensor EST app::g_sensor : l'ecrire ecrit dans
l'application, sans copie.
"""

from autotest import check, cycles, expect, record, scenario, until


@scenario
async def au_sol_sans_capteur(sut):
    """Sans mesure valide, l'application reste en Preflight."""
    Phase = sut.testgen.FlightPlan.Phase
    sut.app.g_sensor.valid = False
    await cycles(1)
    expect(sut.app.g_telemetry.phase, "phase").eq(Phase.Preflight)


@scenario(timeout=100)
async def montee_puis_croisiere(sut):
    """Rampe d'altitude jusqu'a la consigne : Taxi, Climb, puis Cruise."""
    Phase = sut.testgen.FlightPlan.Phase
    sut.app.g_target.position.z = 3000.0
    sut.app.g_sensor.unit = sut.testgen.Unit.Feet
    sut.app.g_sensor.label = "ALT-1"
    sut.app.g_sensor.valid = True

    phases = record("phase", lambda: sut.app.g_telemetry.phase.value)
    for altitude in range(0, 3001, 250):
        sut.app.g_sensor.value = float(altitude)
        await cycles(1)
        if altitude == 1000:
            check(sut.app.g_telemetry.phase, "phase a 1000 ft").eq(Phase.Climb)

    await until(lambda: sut.app.g_telemetry.phase == Phase.Cruise, timeout=5)
    expect(sut.app.g_plan.payload.halves.lo, "altitude publiee").eq(3000)
    # La phase n'a fait que monter : jamais de retour en arriere.
    values = list(phases.values)
    expect(values, "suite des phases").satisfies(
        lambda v: all(a <= b for a, b in zip(v, v[1:])), "une suite croissante")


@scenario
async def conversion_metres(sut):
    """1000 m sont publies en pieds."""
    sut.app.g_sensor.unit = sut.testgen.Unit.Meters
    sut.app.g_sensor.value = 1000.0
    sut.app.g_sensor.valid = True
    await cycles(1)
    expect(sut.app.g_plan.payload.halves.lo, "altitude en pieds").near(3281, tol=1)


@scenario
async def compteur_de_cycles(sut):
    """Une variable globale scalaire se lit en direct : g_cycle avance."""
    debut = sut.app.g_cycle
    await cycles(3)
    expect(sut.app.g_cycle - debut, "cycles ecoules").eq(3)
