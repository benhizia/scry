// Cote visualiseur : connexion a raven.exe et miroir de son etat. raven-view
// ne garde aucune configuration propre : il affiche celle de raven.exe, qui
// survit aux deconnexions du visualiseur.
#pragma once
#include <cstdint>
#include <deque>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "raven/descriptor.h"
#include "raven/net.h"

namespace raven {

struct SentinelEvent {
    FieldRef ref;
    uint64_t frame = 0;
    double old_value = 0, new_value = 0;
    uint64_t count = 0;
};

struct Trace {
    std::deque<float> values;              // une valeur par trame
    uint64_t last_frame = 0;
};

// Une liaison telle que raven.exe la decrit, avec le sens de chacun de ses
// canaux. Le sens vient du montage, pas du descripteur : c'est 'links' qui le
// donne.
struct LinkInfo {
    int index = 0;
    std::string name, state, source;
    uint64_t frames = 0;
    bool current = false;
    // Par canal : son sens ("A>B", "B>A" ou vide) et son nom.
    std::map<int, std::pair<std::string, std::string>> channels;
};

class Client {
public:
    void set_address(const std::string& host, int port) { host_ = host; port_ = port; }
    // A appeler a chaque image : reconnexion, reception, analyse.
    void tick();
    void send(const std::string& cmd);
    // Champs visibles a l'ecran : raven.exe n'envoie que leurs valeurs.
    void set_watch(const std::vector<FieldRef>& refs);

    bool connected() const { return sock_.valid(); }
    bool ready() const { return connected() && has_desc_; }
    const Descriptor& desc() const { return desc_; }
    std::string address() const { return host_ + ":" + std::to_string(port_); }

    // Liaisons montees par raven.exe, rafraichies une fois par seconde.
    const std::vector<LinkInfo>& links() const { return links_; }
    const LinkInfo* current_link() const;
    // Sens d'un canal de la liaison courante, "" s'il n'en a pas.
    std::string channel_direction(int channel) const;
    void use_link(const std::string& name);

    // Miroir de la configuration de raven.exe.
    std::set<FieldRef> rec, sen, trc;
    bool trg_active = false;
    FieldRef trg_ref;
    std::string trg_op = "==";
    double trg_value = 0;
    std::string path;

    // Etat.
    std::string state = "?", message, last_error;
    uint64_t frames = 0, last = 0, lost = 0, rec_frames = 0, rec_bytes = 0, dropped = 0;
    bool source_ok = false;
    bool paused = false;                   // pause vue : valeurs affichees non rafraichies

    std::map<FieldRef, std::vector<unsigned char>> values;
    std::deque<SentinelEvent> events;      // les plus recents a la fin
    std::map<FieldRef, SentinelEvent> sentinel_last;
    std::map<FieldRef, Trace> traces;

    static const size_t kTraceLength = 1500;   // 30 s a 50 Hz
    static const size_t kEventLength = 500;

private:
    void handle(const std::string& line);

    std::string host_ = "127.0.0.1";
    int port_ = 47800;
    LineSocket sock_;
    double next_try_ = 0;
    Descriptor desc_;
    bool has_desc_ = false;
    bool in_desc_ = false, in_cfg_ = false;
    std::string desc_text_;
    std::vector<FieldRef> watch_;
    std::vector<LinkInfo> links_, links_building_;
    double next_links_ = 0;
};

} // namespace raven
