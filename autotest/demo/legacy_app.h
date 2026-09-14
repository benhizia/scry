// Faux programme legacy, sequence : acquisition, metier, autotest.
// Ses interfaces sont des structs existantes (Data/test_structs_complexe.h),
// que ni l'application ni l'autotest ne modifient.
#pragma once

#include "test_structs_complexe.h"

namespace app {

// Entrees : ce que positionnent les scenarios.
extern testgen::SensorSample g_sensor;     // mesure d'altitude
extern testgen::Waypoint     g_target;     // consigne : position.z en pieds

// Sorties : ce que verifient les scenarios.
extern testgen::TelemetryFrame g_telemetry; // phase de vol, compteur de cycles
extern testgen::FlightPlan     g_plan;      // payload.halves.lo : altitude publiee

extern unsigned g_cycle;

void acquisition();
void metier();

}  // namespace app
