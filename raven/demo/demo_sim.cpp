// Simulateur de demonstration : boucle de 20 ms, publie ses variables globales
// par la glue generee par 'scry raven'. Deroule un scenario en boucle :
// arret 2 s, vol 10 s (montee, croisiere, descente), gel 2 s.
//
//   demo_sim [--name demo] [--seconds 0]
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>

#include "raven_publish.gen.h"

demo::FlightState g_flight;
demo::SimControl  g_sim;

int main(int argc, char** argv) {
    std::string name = "demo";
    double seconds = 0;                       // 0 : sans fin
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string a = argv[i];
        if (a == "--name") name = argv[i + 1];
        else if (a == "--seconds") seconds = std::atof(argv[i + 1]);
    }
    raven::Producer producer;
    if (!raven_gen::open(producer, name.c_str())) {
        std::fprintf(stderr, "memoire partagee '%s' impossible a creer\n", name.c_str());
        return 1;
    }
    std::printf("demo_sim : publie sur '%s' toutes les 20 ms\n", name.c_str());
    std::fflush(stdout);

    using clock = std::chrono::steady_clock;
    const auto period = std::chrono::milliseconds(20);
    auto next = clock::now();
    const uint32_t scenario_cycles = 700;     // 14 s
    for (uint32_t cycle = 0; seconds <= 0 || cycle * 0.02 < seconds; ++cycle) {
        const uint32_t c = cycle % scenario_cycles;
        const double t = c * 0.02;
        g_sim.tick_ms = cycle * 20;
        g_sim.scenario = int16_t(cycle / scenario_cycles);
        g_sim.state = t < 2 ? demo::SimState::Stopped
                    : t < 12 ? demo::SimState::Running : demo::SimState::Frozen;

        g_flight.cycle = cycle;
        if (g_sim.state == demo::SimState::Running) {
            const double tf = t - 2;              // 0..10 s de vol
            g_flight.phase = tf < 3 ? demo::Phase::Climb : tf < 7 ? demo::Phase::Cruise
                                                                  : demo::Phase::Descent;
            g_flight.pos.alt = float(tf < 3 ? tf * 3000 : tf < 7 ? 9000 : (10 - tf) * 3000);
            g_flight.pos.lat = 48.85 + tf * 0.01;
            g_flight.pos.lon = 2.35 + tf * 0.02 + 0.001 * std::sin(tf);
            for (int k = 0; k < 4; ++k) g_flight.fuel[k] = float(5000 - tf * 40 - k);
            // Un booleen qui ne vit qu'une trame : c'est ce que les sentinelles
            // doivent attraper.
            g_flight.gear_down = tf < 1 || tf > 9 || c == 400;
        } else if (g_sim.state == demo::SimState::Stopped) {
            g_flight = demo::FlightState();
            g_flight.cycle = cycle;
            g_flight.gear_down = true;
            for (int k = 0; k < 4; ++k) g_flight.fuel[k] = float(5000 - k);
        }
        raven_gen::publish(producer);

        next += period;
        std::this_thread::sleep_until(next);
    }
    return 0;
}
