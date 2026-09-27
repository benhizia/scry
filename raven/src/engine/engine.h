// Moteur de raven.exe : recoit chaque trame, applique la configuration
// (champs enregistres, declencheur, sentinelles, traces) et produit les mises a
// jour pour le visualiseur. Il ne sait rien du transport : les trames arrivent
// par on_frame(), les commandes par command(), en texte.
//
// Protocole texte avec le visualiseur, une ligne par message. Un champ est
// designe par "canal:champ" (indices du descripteur).
//
//   visualiseur -> raven            raven -> visualiseur
//   hello                           desc_begin / <.rvndesc> / desc_end
//   watch c:f c:f ...               cfg_begin / rec|sen|trc|trg|path ... / cfg_end
//   rec c:f 0|1   rec_all 0|1       st <etat> cle=valeur ... msg=<texte>
//   sen c:f 0|1   sen_reset         v c:f <hex>             (champs observes)
//   trc c:f 0|1                     s c:f <trame> <ancien> <nouveau> <nombre>
//   trg off | trg c:f <op> <val>    t c:f <trame> <valeur>  (chaque trame)
//   path <fichier>  arm  stop       ok | err <message>
#pragma once
#include <cstdint>
#include <deque>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>

#include "raven/descriptor.h"
#include "raven/rvn.h"
#include "raven/source.h"

namespace raven {

enum class RecState { Idle, Armed, Recording };
const char* rec_state_name(RecState s);

struct Trigger {
    bool active = false;
    FieldRef ref;
    std::string op = "==";          // == != < <= > >=
    double value = 0.0;
    bool eval(const Descriptor& d, const unsigned char* frame) const;
    std::string text(const Descriptor& d) const;
};

std::string ref_str(FieldRef r);                 // "0:4"
bool parse_ref(const std::string& s, FieldRef& r);

class Engine {
public:
    explicit Engine(const Descriptor& d);

    // Fil d'acquisition : une trame complete.
    void on_frame(const Frame& f);
    // Etat de la source, rafraichi par le fil d'acquisition.
    void set_source(bool connected, uint64_t lost, const std::string& error);

    // Fil de controle : execute une commande, renvoie les lignes de reponse.
    std::string command(const std::string& line);
    // Messages a envoyer depuis le dernier appel : etat, valeurs observees,
    // evenements des sentinelles, echantillons des traces.
    std::string updates();

    RecState state() const;
    uint64_t frames() const;

private:
    std::string config_block() const;
    std::string status_line() const;
    void start_recording(const Frame& f);
    void stop_recording(const std::string& why);

    const Descriptor& d_;
    mutable std::mutex m_;

    // Configuration, pilotee par le visualiseur.
    std::set<FieldRef> rec_, sen_, trc_;
    std::vector<FieldRef> watch_;
    Trigger trigger_;
    std::string path_ = "raven_%t.rvn";

    // Etat.
    RecState state_ = RecState::Idle;
    RvnWriter writer_;
    std::vector<unsigned char> latest_;
    uint64_t frames_ = 0, last_no_ = 0;
    bool src_connected_ = false;
    uint64_t src_lost_ = 0;
    std::string src_error_, message_;

    struct Sentinel {
        std::vector<unsigned char> prev;
        uint64_t count = 0;
    };
    std::map<FieldRef, Sentinel> sentinels_;
    std::deque<std::string> events_;             // messages 's' et 't' en attente
    uint64_t dropped_ = 0;
};

} // namespace raven
