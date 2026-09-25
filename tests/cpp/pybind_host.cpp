// Hote de test : une application qui embarque Python et le module genere par
// Scry (scry_module.generated.cpp). Utilise par tests/test_pybind_embed.py.
//
//   pybind_host script.py
//
// Execute le script, puis ecrit sur stdout les octets de g_sample et de
// g_plan en hexadecimal, et quelques globales : le test les relit aux
// offsets du modele. Ce que Python a ecrit doit s'y trouver.
#include "pybind_cases.h"

#include <pybind11/embed.h>

#include <cstdio>

namespace cases {
Sample g_sample{};
Sample* g_current = nullptr;
Speed g_speed = Speed::Off;
double g_gains[3] = {1.0, 2.0, 3.0};
char g_callsign[8] = "F-GKXA";
const int g_version = 42;
testgen::FlightPlan g_plan{};
testgen::SensorSample g_sensors[4]{};
Child g_child{};
Hidden g_hidden{};
namespace inner {
std::uint32_t g_ticks = 0;
}
}  // namespace cases

namespace py = pybind11;

static void hex(const char* label, const void* data, std::size_t size)
{
    std::printf("%s ", label);
    const unsigned char* p = static_cast<const unsigned char*>(data);
    for (std::size_t i = 0; i < size; ++i)
        std::printf("%02x", p[i]);
    std::printf("\n");
}

int main(int argc, char** argv)
{
    if (argc < 2)
        return 2;
    py::scoped_interpreter guard;
    // Pointeur change cote C++ avant le script : Python doit le suivre.
    cases::g_current = &cases::g_sample;
    try {
        py::eval_file(argv[1]);
    } catch (const py::error_already_set& e) {
        std::printf("ERREUR %s\n", e.what());
        return 1;
    }
    std::fflush(stdout);
    hex("SAMPLE", &cases::g_sample, sizeof(cases::g_sample));
    hex("SENSOR2", &cases::g_sensors[2], sizeof(cases::g_sensors[2]));
    std::printf("SPEED %d\n", static_cast<int>(cases::g_speed));
    std::printf("GAINS %g %g %g\n", cases::g_gains[0], cases::g_gains[1], cases::g_gains[2]);
    std::printf("CALLSIGN %s\n", cases::g_callsign);
    std::printf("TICKS %u\n", cases::inner::g_ticks);
    std::printf("CHILD %d %g %d\n", cases::g_child.base_value, cases::g_child.weight,
                cases::g_child.extra);
    std::printf("PLAN %s %d %u\n", cases::g_plan.callsign.c_str(),
                static_cast<int>(cases::g_plan.legs[2].phase), cases::g_plan.payload.raw);
    return 0;
}
