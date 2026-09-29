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
Moteur g_moteur{};
Piste g_piste{};
std::vector<double> g_serie{1.0, 2.0};
std::vector<Repere> g_reperes{{1.0, 2.0}, {3.0, 4.0}};
// Memoire possedee par l'hote, visee par les paires pointeur + compteur.
static Repere s_bornes[3] = {{10.0, 20.0}, {11.0, 21.0}, {12.0, 22.0}};
static const double s_mesures[4] = {0.5, 1.5, 2.5, 3.5};
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
    cases::g_piste.gains = {1.0, 2.0, 3.0};
    cases::g_piste.reperes = {{1.0, 2.0}, {3.0, 4.0}};
    cases::g_piste.noms = {"nord", "sud"};
    cases::g_piste.allures = {cases::Speed::Slow, cases::Speed::Fast};
    cases::g_piste.bornes = cases::s_bornes;
    cases::g_piste.nb_bornes = 3;
    cases::g_piste.mesures = cases::s_mesures;
    cases::g_piste.nb_mesures = 4;
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
    std::printf("MOTEUR %g %d\n", cases::g_moteur.regime,
                static_cast<int>(cases::g_moteur.allure));
    std::printf("GAINS_N %zu\n", cases::g_piste.gains.size());
    std::printf("GAINS_V");
    for (double g : cases::g_piste.gains)
        std::printf(" %g", g);
    std::printf("\n");
    std::printf("REPERE0 %g %g\n", cases::g_piste.reperes[0].lat,
                cases::g_piste.reperes[0].lon);
    std::printf("NOMS %s %s\n", cases::g_piste.noms[0].c_str(), cases::g_piste.noms[1].c_str());
    std::printf("ALLURE1 %d\n", static_cast<int>(cases::g_piste.allures[1]));
    std::printf("BORNE1 %g %g\n", cases::s_bornes[1].lat, cases::s_bornes[1].lon);
    std::printf("SERIE");
    for (double v : cases::g_serie)
        std::printf(" %g", v);
    std::printf("\n");
    std::printf("REPERES_N %zu %g\n", cases::g_reperes.size(), cases::g_reperes[1].lat);
    return 0;
}
