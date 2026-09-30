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
//  Mise au point : avec cfg.watch = true, l'autotest ne se declare jamais
//  termine. Il surveille la date des fichiers de scenarios et rejoue une passe
//  des qu'un seul change ; host.reload() force la meme chose tout de suite. On
//  corrige un scenario et il rejoue dans la seconde, le simulateur gardant son
//  etat. C'est l'application qui decide alors quand s'arreter.
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
    // Un tick plus long est compte dans le rapport (slow_ticks), qui porte de
    // toute facon l'histogramme des durees et le pire cas.
    double tick_budget_ms = 0.0;
    // Sur depassement, echantillonner le tick SUIVANT avec cProfile et joindre
    // les fonctions les plus couteuses au rapport. Une fois par scenario. On ne
    // peut pas profiler le passe ; le tick suivant execute presque toujours le
    // meme code que le fautif.
    bool profile_slow = false;
    // Couper un scenario apres N ticks hors budget, 0 pour ne jamais couper.
    // Un scenario qui decale le cycle a chaque tour ne sert plus a rien.
    int max_slow_ticks = 0;
    // Arreter les scenarios au premier echec.
    bool stop_on_failure = false;
    // Veille : au lieu de se declarer termine, l'autotest surveille la date des
    // fichiers de scenarios et rejoue une passe des qu'un seul change. tick()
    // ne retourne alors jamais false, et c'est l'application qui decide quand
    // s'arreter. Pour mettre un scenario au point sans relancer le simulateur.
    bool watch = false;
    // Espacement des stat() du disque, en cycles de l'application.
    int watch_every = 25;
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
            py::arg("stop_on_failure") = cfg.stop_on_failure,
            py::arg("watch") = cfg.watch, py::arg("watch_every") = cfg.watch_every,
            py::arg("profile_slow") = cfg.profile_slow,
            py::arg("max_slow_ticks") = cfg.max_slow_ticks);
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

    // Relit les scenarios et repart d'une passe neuve, sans attendre que la
    // veille le remarque. A brancher sur ce que l'on veut : une touche, une
    // commande reseau, un fichier temoin. Le simulateur garde son etat.
    // Retourne false si le rechargement a echoue, auquel cas l'autotest est
    // arrete comme apres n'importe quelle erreur Python.
    bool reload() noexcept
    {
        try {
            runner_.attr("reload")();
            finished_ = false;
            return true;
        } catch (const py::error_already_set& e) {
            std::fprintf(stderr, "[autotest] rechargement impossible : %s\n", e.what());
            broken_ = finished_ = true;
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[autotest] rechargement impossible : %s\n", e.what());
            broken_ = finished_ = true;
        }
        return false;
    }

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
