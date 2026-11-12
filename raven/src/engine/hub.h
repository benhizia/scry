// Plusieurs liaisons dans un seul raven.exe : un descripteur, une source, un
// moteur et un fil d'acquisition par liaison, et un visualiseur qui les voit
// toutes.
//
// POURQUOI UN MOTEUR PAR LIAISON, et non un moteur a plusieurs descripteurs.
// Un champ se designe par un FieldRef, c'est-a-dire un canal et un champ. Un
// moteur unique aurait demande une troisieme coordonnee, la liaison, dans le
// FieldRef, donc dans le protocole texte, dans le visualiseur, dans
// l'en-tete du .rvn, dans les sentinelles et dans le declencheur : tout ce
// qui touche a un champ. Un moteur par liaison ne change rien a tout cela, et
// donne en prime a chaque liaison son propre declencheur, son propre
// enregistrement et ses propres sentinelles -- ce qui est bien ce que l'on
// veut, une liaison etant un sujet independant.
//
// LE PROTOCOLE RESTE COMPATIBLE. Deux commandes s'ajoutent :
//
//   links            une ligne 'link <i> <nom> <etat> <source>' par liaison
//   use <i|nom>      choisit la liaison dont on parle ensuite
//
// Toute autre commande s'adresse a la liaison choisie, la premiere par
// defaut. Avec une seule liaison, le dialogue est donc exactement celui
// d'avant : un visualiseur qui ignore 'links' et 'use' continue de marcher.
#pragma once
#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "engine.h"
#include "raven/descriptor.h"
#include "raven/ini.h"
#include "raven/source.h"

namespace raven {

// Ce qu'il faut pour monter une liaison : un nom, un descripteur, une source.
struct LinkConfig {
    std::string name;          // "principal"
    std::string desc_path;     // fichier .rvndesc
    std::string source;        // "tcp:...|...|...|..." ou "shm:demo"
    std::string record_path;   // modele de nom du .rvn, vide = defaut du moteur
};

// Lit les sections [link.x] d'un raven.ini. 'only' limite a une liaison.
// 'default_desc' sert aux sections qui ne portent pas de cle 'desc'.
bool load_links(const Ini& ini, const std::string& only, const std::string& default_desc,
                std::vector<LinkConfig>& out, std::string& error);

class Hub {
public:
    ~Hub();

    // Monte toutes les liaisons. En cas d'echec, aucune n'est demarree.
    bool start(const std::vector<LinkConfig>& configs, std::string& error);
    void stop();

    std::size_t size() const { return links_.size(); }
    // Resume d'une ligne par liaison, pour le journal de demarrage.
    std::string summary() const;

    // Protocole : 'links' et 'use' sont traites ici, le reste est delegue a la
    // liaison choisie.
    std::string command(const std::string& line);
    std::string updates();
    // Ferme proprement un enregistrement en cours sur chaque liaison.
    void stop_all_recordings();

private:
    struct Link {
        LinkConfig cfg;
        std::unique_ptr<Descriptor> desc;
        std::unique_ptr<ISource> source;
        std::unique_ptr<Engine> engine;
        std::thread th;
    };

    std::string links_block() const;
    Link* selected();

    std::vector<std::unique_ptr<Link>> links_;
    std::atomic<bool> stop_{false};
    mutable std::mutex m_;
    std::size_t current_ = 0;
};

} // namespace raven
