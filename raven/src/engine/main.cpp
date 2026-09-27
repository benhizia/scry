// raven.exe : l'enregistreur. Sans IHM : il se pilote depuis raven-view, qui
// peut se connecter et se deconnecter a tout moment sans rien interrompre.
//
//   raven --desc demo.rvndesc [--source shm:demo] [--port 47800]
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

#include "engine.h"
#include "raven/net.h"

using namespace raven;

static std::atomic<bool> g_stop(false);
static void on_signal(int) { g_stop = true; }

static void usage() {
    std::printf("usage : raven --desc <fichier.rvndesc> [--source shm:<nom>] [--port 47800]\n");
}

int main(int argc, char** argv) {
    std::string desc_path, source_spec = "shm:raven";
    int port = 47800;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--desc" && i + 1 < argc) desc_path = argv[++i];
        else if (a == "--source" && i + 1 < argc) source_spec = argv[++i];
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
        for (const std::string& l : lines) client.send(engine.command(l));
        const auto now = std::chrono::steady_clock::now();
        if (now >= next_update) {                     // ~20 mises a jour par seconde
            client.send(engine.updates());
            next_update = now + std::chrono::milliseconds(50);
        }
    }
    engine.command("stop");                           // ferme proprement un .rvn en cours
    acquisition.join();
    std::printf("raven : arret, %llu trames recues\n", (unsigned long long)engine.frames());
    return 0;
}
