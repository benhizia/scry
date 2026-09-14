// =============================================================================
//  Module Python 'sut', compile DANS l'application (build LEGACY_AUTOTEST).
//
//  C'est la seule partie propre au projet : elle dit quelles globales les
//  scenarios voient. Les types viennent des bindings generes par Scry, les
//  instances sont exposees par reference : aucune copie, un scenario qui
//  ecrit sut.sensor.value ecrit dans app::g_sensor.
// =============================================================================

#include "legacy_app.h"
#include "scry_pybind.generated.h"

// PYBIND11_EMBEDDED_MODULE : le header genere n'inclut que pybind11.h, pour
// servir aussi a un module .pyd classique.
#include <pybind11/embed.h>

namespace py = pybind11;

PYBIND11_EMBEDDED_MODULE(sut, m)
{
    scry::bind::register_types(m);

    const auto ref = py::return_value_policy::reference;
    m.attr("sensor") = py::cast(&app::g_sensor, ref);
    m.attr("target") = py::cast(&app::g_target, ref);
    m.attr("telemetry") = py::cast(&app::g_telemetry, ref);
    m.attr("plan") = py::cast(&app::g_plan, ref);
    m.def("cycle", [] { return app::g_cycle; }, "Numero du cycle en cours.");
}
