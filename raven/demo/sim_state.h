// Headers du simulateur de démonstration : ce que RAVEN observe.
// Ils jouent le rôle des headers tiers d'un vrai simulateur.
#pragma once
#include <cstdint>

namespace demo {

enum class SimState : int32_t { Stopped = 0, Running = 1, Frozen = 2 };
enum class Phase : uint8_t { Ground, Climb, Cruise, Descent };

struct Position {
    double lat;          ///< [deg]
    double lon;          ///< [deg]
    float  alt;          ///< [ft]
};

struct FlightState {
    uint32_t cycle;
    Position pos;
    Phase    phase;
    bool     gear_down;
    float    fuel[4];    ///< [kg]
};

struct SimControl {
    SimState state;
    uint32_t tick_ms;
    int16_t  scenario;
};

} // namespace demo

extern demo::FlightState g_flight;
extern demo::SimControl  g_sim;
