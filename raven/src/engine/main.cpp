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
#include "hub.h"
#include "raven/ini.h"
#include "raven/net.h"
#include "sources.h"

using namespace raven;

static std::atomic<bool> g_stop(false);
static void on_signal(int) { g_stop = true; }

static void usage() {
    std::printf("usage : raven --desc <fichier.rvndesc> [--source shm:<nom>] [--port 47800]\n"
                "        raven --link <raven.ini>[#<liaison>] [--desc <defaut.rvndesc>]\n"
                "\n"
                "Sans #liaison, toutes les sections [link.x] du fichier sont montees ;\n"
                "le visualiseur passe de l'une a l'autre avec 'use <indice|nom>'.\n");
}

int main(int argc, char** argv) {
    std::string desc_path, source_spec, ini_arg;
    int port = 47800;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--desc" && i + 1 < argc) desc_path = argv[++i];
        else if (a == "--source" && i + 1 < argc) source_spec = argv[++i];
        else if (a == "--link" && i + 1 < argc) ini_arg = argv[++i];
        else if (a == "--port" && i + 1 < argc) port = std::atoi(argv[++i]);
        else { usage(); return 2; }
    }

    // Deux facons de decrire ce que l'on observe, qui aboutissent a la meme
    // chose : une liste de liaisons. Une seule source reste une liaison.
    std::vector<LinkConfig> links;
    std::string err;
    if (!ini_arg.empty()) {
        std::string path = ini_arg, only;
        const std::size_t hash = ini_arg.find('#');
        if (hash != std::string::npos) {
            path = ini_arg.substr(0, hash);
            only = ini_arg.substr(hash + 1);
        }
        Ini ini;
        if (!ini.load(path, err)) { std::fprintf(stderr, "%s\n", err.c_str()); return 1; }
        if (!load_links(ini, only, desc_path, links, err)) {
            std::fprintf(stderr, "%s : %s\n", path.c_str(), err.c_str());
            return 1;
        }
    } else {
        if (desc_path.empty()) { usage(); return 2; }
        LinkConfig c;
        c.name = "principal";
        c.desc_path = desc_path;
        c.source = source_spec.empty() ? "shm:raven" : source_spec;
        links.push_back(c);
    }

    net_init();
    Listener listener;
    if (!listener.listen(port)) { std::fprintf(stderr, "port %d indisponible\n", port); return 1; }
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    Hub hub;
    if (!hub.start(links, err)) { std::fprintf(stderr, "%s\n", err.c_str()); return 1; }
    std::printf("raven : %zu liaison(s), port %d\n%s", hub.size(), port,
                hub.summary().c_str());
    std::fflush(stdout);

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
            hub.command("watch");                     // plus personne ne regarde
            std::printf("visualiseur deconnecte\n");
            std::fflush(stdout);
            continue;
        }
        // Reponses aux commandes : jamais abandonnees. Mises a jour : le
        // visualiseur affiche un etat, on saute un lot plutot que d'attendre.
        for (const std::string& l : lines) client.queue(hub.command(l));
        const auto now = std::chrono::steady_clock::now();
        if (now >= next_update) {                     // ~20 mises a jour par seconde
            client.queue(hub.updates(), true);
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
    hub.stop_all_recordings();                        // ferme chaque .rvn en cours
    hub.stop();
    std::printf("raven : arret\n");
    return 0;
}
