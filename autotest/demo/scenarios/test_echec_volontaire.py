"""Un scenario faux expres : il montre un echec dans le rapport, sans que
l'application s'arrete de tourner. Supprimer ce fichier pour une demo verte.
"""

from autotest import cycles, expect, scenario


@scenario(tags=["demo-echec"])
async def echec_volontaire(sut):
    sut.app.g_sensor.valid = True
    sut.app.g_sensor.value = 10.0
    await cycles(1)
    expect(sut.app.g_telemetry.phase, "phase").eq(sut.testgen.FlightPlan.Phase.Cruise)
