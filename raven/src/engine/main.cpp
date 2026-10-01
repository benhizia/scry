// raven.exe : l'enregistreur. Sans IHM : il se pilote depuis raven-view, qui
// peut se connecter et se deconnecter a tout moment sans rien interrompre.
//
//   raven --desc demo.rvndesc [--source shm:demo] [--port 47800]
#include <atomic>
#include <chrono>
#include <cstddef>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

#include <vector>

#include "engine.h"
#include "raven/ini.h"
#include "raven/net.h"
#include "sources.h"

using namespace raven;

static std::atomic<bool> g_stop(false);
static void on_signal(int) { g_stop = true; }

static void usage() {
    std::printf("usage : raven --desc <fichier.rvndesc> [--source shm:<nom>] [--port 47800]\n"
                "        raven --desc <fichier.rvndesc> --link <raven.ini>[#<liaison>]\n");
}

// --link <fichier.ini>[#<nom>] : la source vient d'une section [link.<nom>].
// Sans nom, il doit y avoir exactement une liaison dans le fichier : choisir
// a la place de l'utilisateur serait pire que de le lui demander.
static bool spec_from_ini(const std::string& arg, std::string& spec) {
    std::string path = arg, wanted;
    const std::size_t hash = arg.find('#');
    if (hash != std::string::npos) { path = arg.substr(0, hash); wanted = arg.substr(hash + 1); }

    Ini ini;
    std::string err;
    if (!ini.load(path, err)) { std::fprintf(stderr, "%s\n", err.c_str()); return false; }
    const std::vector<std::string> links = ini.sections_with("link.");
    if (links.empty()) {
        std::fprintf(stderr, "%s : aucune section [link.<nom>]\n", path.c_str());
        return false;
    }
    if (wanted.empty() && links.size() > 1) {
        std::fprintf(stderr, "%s : %zu liaisons, preciser laquelle avec --link %s#<nom>\n",
                     path.c_str(), links.size(), path.c_str());
        for (const std::string& l : links) std::fprintf(stderr, "  %s\n", l.c_str() + 5);
        return false;
    }
    const std::string section = wanted.empty() ? links[0] : "link." + wanted;
    if (!link_spec(ini, section, spec, err)) {
        std::fprintf(stderr, "%s\n", err.c_str());
        return false;
    }
    return true;
}

int main(int argc, char** argv) {
    std::string desc_path, source_spec = "shm:raven";
    int port = 47800;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--desc" && i + 1 < argc) desc_path = argv[++i];
        else if (a == "--source" && i + 1 < argc) source_spec = argv[++i];
        else if (a == "--link" && i + 1 < argc) {
            if (!spec_from_ini(argv[++i], source_spec)) return 1;
        }
        else if (a == "--port" && i + 1 < argc) port = std::atoi(argv[++i]);
        else { usage(); return 2; }
    }
    if (desc_path.empty()) { usage(); return 2; }

    Descriptor desc;
    std::string err;
    if (!desc.load(desc_path, err)) { std::fprintf(stderr, "descripteur : %s\n", err.c_str()); return 1; }
    auto source = make_source(source_spec, desc);
    if (!source) { std::fprintf(stderr, "source inconnue : %s\n", source_spec.c_str()); return 1; }

    net_init();
    Listener listener;
    if (!listener.listen(port)) { std::fprintf(stderr, "port %d indisponible\n", port); return 1; }
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);
    std::printf("raven : %s, %zu canaux, trame de %u octets, source %s, port %d\n",
                desc_path.c_str(), desc.channels().size(), desc.frame_size(),
                source->describe().c_str(), port);
    std::fflush(stdout);

    Engine engine(desc);

    // Fil d'acquisition : scrute la source et passe chaque trame au moteur.
    std::thread acquisition([&] {
        while (!g_stop) {
            const size_t n = source->poll([&](const Frame& f) { engine.on_frame(f); });
            engine.set_source(source->connected(), source->lost(), source->error());
            if (n == 0) std::this_thread::sleep_for(std::chrono::microseconds(500));
        }
    });

    // Fil principal : un visualiseur a la fois, qui peut aller et venir.
    LineSocket client;
    auto next_update = std::chrono::steady_clock::now();
    auto next_report = next_update;
    std::size_t dropped_signale = 0;
    while (!g_stop) {
        if (!client.valid()) {
            client = listener.accept(200);
            if (client.valid()) std::printf("visualiseur connecte\n"), std::fflush(stdout);
            continue;
        }
        std::vector<std::string> lines;
        if (!client.receive(lines, 20)) {
            engine.command("watch");                  // plus personne ne regarde
            std::printf("visualiseur deconnecte\n");
            std::fflush(stdout);
            continue;
        }
        // Reponses aux commandes : jamais abandonnees. Mises a jour : le
        // visualiseur affiche un etat, on saute un lot plutot que d'attendre.
        for (const std::string& l : lines) client.queue(engine.command(l));
        const auto now = std::chrono::steady_clock::now();
        if (now >= next_update) {                     // ~20 mises a jour par seconde
            client.queue(engine.updates(), true);
            next_update = now + std::chrono::milliseconds(50);
        }
        if (!client.flush()) continue;
        if (client.dropped() != dropped_signale && now >= next_report) {
            std::printf("visualiseur lent : %llu lot(s) de mises a jour abandonne(s)\n",
                        (unsigned long long)client.dropped());
            std::fflush(stdout);
            dropped_signale = client.dropped();
            next_report = now + std::chrono::seconds(1);
        }
    }
    engine.command("stop");                           // ferme proprement un .rvn en cours
    acquisition.join();
    std::printf("raven : arret, %llu trames recues\n", (unsigned long long)engine.frames());
    return 0;
}
