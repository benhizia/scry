// =============================================================================
//  autotest_embed.h : interpreteur Python embarque pour l'etape autotest d'une
//  application sequencee. Header-only, ecrit a la main, independant de Scry.
//
//  Usage, dans l'application :
//
//      #include "autotest_embed.h"
//
//      autotest::HostConfig cfg;
//      cfg.venv      = L"X:\\projet\\.venv";           // runtime Python (numpy...)
//      cfg.paths     = {L"X:\\projet\\autotest\\python"};
//      cfg.scenarios = "X:/projet/scenarios";
//      autotest::Host host(cfg);                        // une fois, au demarrage
//
//      for (;;) {                                       // le sequenceur
//          acquisition();
//          metier();
//          if (!host.tick())                            // l'etape autotest
//              return host.exit_code();
//      }
//
//  Le module Python 'sut' (PYBIND11_EMBEDDED_MODULE) est genere par Scry :
//  scry_module.generated.cpp, qui expose tous les types et toutes les
//  variables globales des headers, par reference.
//
//  Garanties :
//    - tick() ne laisse jamais sortir d'exception : une erreur Python arrete
//      l'autotest, pas l'application ;
//    - tout se passe dans le thread appelant, celui du sequenceur : aucune
//      concurrence avec le code metier ;
//    - les objets Python sont detruits avant l'interpreteur.
// =============================================================================
#pragma once

#include <pybind11/embed.h>

#include <cstdio>
#include <exception>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace autotest {

namespace py = pybind11;

struct HostConfig
{
    // Venv qui porte le runtime (numpy, etc.). Son python.exe sert
    // d'executable de reference : Python lit alors pyvenv.cfg et active le venv.
    // Vide : installation Python par defaut.
    std::wstring venv;
    // Ajoutes en tete de sys.path : runtime autotest, aides de test...
    std::vector<std::wstring> paths;
    // Dossier des scenarios test_*.py.
    std::string scenarios = "scenarios";
    // Rapport JUnit, vide pour ne pas en ecrire.
    std::string report = "autotest-report.xml";
    // Filtre sur le nom ou les tags des scenarios, vide pour tout lancer.
    std::string select;
    // Duree maximale d'un tick en millisecondes, 0 pour ne pas surveiller.
    // Un tick plus long est compte dans le rapport (slow_ticks).
    double tick_budget_ms = 0.0;
    // Arreter les scenarios au premier echec.
    bool stop_on_failure = false;
};

class Host
{
public:
    explicit Host(const HostConfig& cfg)
    {
        PyConfig config;
        PyConfig_InitPythonConfig(&config);
        config.install_signal_handlers = 0;  // l'application garde ses handlers
        if (!cfg.venv.empty()) {
#if defined(_WIN32)
            const std::wstring exe = cfg.venv + L"\\Scripts\\python.exe";
#else
            const std::wstring exe = cfg.venv + L"/bin/python";
#endif
            const PyStatus status = PyConfig_SetString(&config, &config.executable, exe.c_str());
            if (PyStatus_Exception(status)) {
                PyConfig_Clear(&config);
                throw std::runtime_error("autotest : venv invalide");
            }
        }
        interpreter_ = std::make_unique<py::scoped_interpreter>(&config, 0, nullptr, false);

        py::object sys_path = py::module_::import("sys").attr("path");
        for (auto it = cfg.paths.rbegin(); it != cfg.paths.rend(); ++it)
            sys_path.attr("insert")(0, *it);

        py::object report = cfg.report.empty() ? py::object(py::none()) : py::str(cfg.report);
        py::object select = cfg.select.empty() ? py::object(py::none()) : py::str(cfg.select);
        runner_ = py::module_::import("autotest").attr("Runner")(
            cfg.scenarios, py::arg("report") = report, py::arg("select") = select,
            py::arg("tick_budget_ms") = cfg.tick_budget_ms,
            py::arg("stop_on_failure") = cfg.stop_on_failure);
    }

    ~Host()
    {
        runner_ = py::object();  // avant l'interpreteur
        interpreter_.reset();
    }

    Host(const Host&) = delete;
    Host& operator=(const Host&) = delete;

    // L'etape autotest d'un cycle. Retourne false quand tous les scenarios sont
    // termines, ou apres une erreur Python non rattrapee.
    bool tick() noexcept
    {
        if (finished_)
            return false;
        try {
            finished_ = !runner_.attr("tick")().cast<bool>();
        } catch (const py::error_already_set& e) {
            std::fprintf(stderr, "[autotest] erreur Python : %s\n", e.what());
            broken_ = finished_ = true;
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[autotest] erreur : %s\n", e.what());
            broken_ = finished_ = true;
        }
        return !finished_;
    }

    bool finished() const { return finished_; }

    // 0 : tout est passe ; 1 : au moins un scenario en echec ; 2 : erreur de
    // l'autotest lui-meme.
    int exit_code() const
    {
        if (broken_)
            return 2;
        try {
            return runner_.attr("exit_code").cast<int>() == 0 ? 0 : 1;
        } catch (...) {
            return 2;
        }
    }

private:
    std::unique_ptr<py::scoped_interpreter> interpreter_;
    py::object runner_;
    bool finished_ = false;
    bool broken_ = false;
};

}  // namespace autotest
