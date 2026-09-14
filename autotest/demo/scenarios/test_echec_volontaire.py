"""Un scenario faux expres : il montre un echec dans le rapport, sans que
l'application s'arrete de tourner. Supprimer ce fichier pour une demo verte.
"""

from autotest import cycles, expect, scenario


@scenario(tags=["demo-echec"])
async def echec_volontaire(sut):
    sut.sensor.valid = True
    sut.sensor.value = 10.0
    await cycles(1)
    expect(sut.telemetry.phase, "phase").eq(sut.testgen.FlightPlan.Phase.Cruise)
