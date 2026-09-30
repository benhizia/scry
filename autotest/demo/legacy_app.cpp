// =============================================================================
//  Faux programme legacy sequence, pour la demo d'autotest embarque.
//
//  Chaque cycle : acquisition, metier, puis l'etape autotest si l'application
//  est compilee avec LEGACY_AUTOTEST. Sans elle, aucune dependance a Python :
//  c'est le binaire de production.
// =============================================================================

#include "legacy_app.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>

#if LEGACY_AUTOTEST
#include "autotest_embed.h"
#endif

namespace app {

testgen::SensorSample   g_sensor{};
testgen::Waypoint       g_target{};
testgen::TelemetryFrame g_telemetry{};
testgen::FlightPlan     g_plan{};
unsigned                g_cycle = 0;

void acquisition()
{
    // En vrai : lecture des capteurs. En autotest, les scenarios les remplacent.
}

void metier()
{
    using Phase = testgen::FlightPlan::Phase;

    const double feet = g_sensor.unit == testgen::Unit::Meters ? g_sensor.value * 3.28084
                                                                : g_sensor.value;
    const double target = g_target.position.z;

    Phase phase;
    if (!g_sensor.valid)
        phase = Phase::Preflight;
    else if (feet < 50.0)
        phase = Phase::Taxi;
    else if (feet < target - 100.0)
        phase = Phase::Climb;
    else if (feet > target + 100.0)
        phase = Phase::Descent;
    else
        phase = Phase::Cruise;

    g_telemetry.phase = phase;
    ++g_telemetry.access_count;
    g_plan.payload.halves.lo =
        static_cast<std::uint16_t>(std::clamp(feet + 0.5, 0.0, 65535.0));
    g_plan.payload.halves.hi = g_sensor.quality;
}

}  // namespace app

#if LEGACY_AUTOTEST
static std::wstring env(const char* name)
{
    const char* value = std::getenv(name);
    return value ? std::wstring(value, value + std::strlen(value)) : std::wstring();
}
#endif

int main(int argc, char** argv)
{
#if LEGACY_AUTOTEST
    autotest::HostConfig cfg;
    cfg.venv = env("AUTOTEST_VENV");
    cfg.paths = {L"" AUTOTEST_PYTHON_DIR};
    cfg.scenarios = AUTOTEST_SCENARIOS_DIR;
    cfg.tick_budget_ms = 5.0;
    // '--watch' : mise au point. L'application ne s'arrete plus, les scenarios
    // rejouent a chaque enregistrement d'un fichier. Tout autre argument est un
    // filtre sur le nom ou les tags des scenarios.
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--watch") == 0)
            cfg.watch = true;
        else
            cfg.select = argv[i];
    }
    autotest::Host host(cfg);
    if (cfg.watch)
        std::printf("veille : modifiez un scenario, il rejoue. Ctrl+C pour sortir.\n");
#else
    (void)argc;
    (void)argv;
#endif

    for (;;) {
        ++app::g_cycle;
        app::acquisition();
        app::metier();
#if LEGACY_AUTOTEST
        if (!host.tick())       // l'etape autotest : le metier a fini ce cycle
            return host.exit_code();
        // En veille, la boucle ne s'arrete jamais : lui donner sa cadence
        // plutot que de bruler un coeur pour rien.
        if (cfg.watch)
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
#else
        if (app::g_cycle == 10) {
            std::printf("10 cycles, phase %d\n", static_cast<int>(app::g_telemetry.phase));
            return 0;
        }
#endif
    }
}
