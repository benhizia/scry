// Plugins "tcp" et "udp" : RAVEN se place ENTRE deux equipements A et B, fait
// passer les messages, et en garde une copie.
//
//   tcp:<ecoute>|<vers>|<canal A>B>|<canal B>A>
//   udp:<ecoute>|<vers>|<canal A>B>|<canal B>A>
//
//   ecoute   ou A nous joint            : "0.0.0.0:8001" ou ":8001"
//   vers     ou nous joignons B         : "10.0.0.2:8002"
//   canaux   noms de canaux du descripteur, un par sens. Un sens laisse vide
//            n'est pas relaye : "tcp:...|...|cmd|" n'ecoute que A vers B.
//
// CE QUI GOUVERNE TOUTE LA CONCEPTION. Le transfert est la fonction vitale :
// si RAVEN le retarde, il ne se contente pas de mal observer, il degrade le
// systeme qu'il observe. Donc, dans cet ordre et jamais autrement :
//
//     recevoir  ->  transferer  ->  pousser une copie dans la file
//
// La copie part dans une FrameQueue sans verrou (raven/spsc.h), vidée par le
// fil d'acquisition. Le relais n'attend jamais le moteur, qui prend un mutex
// partage avec le visualiseur : sans la file, le temps de transfert entre deux
// equipements reels dependrait de ce que dessine une IHM.
//
// UN FIL PAR SENS, parce que recv bloque et que les deux sens sont
// independants : si A se tait une seconde, un fil unique serait plante dans
// son recv et ne relaierait pas ce que B envoie pendant ce temps. Un fil par
// sens rend cette independance structurelle au lieu de la maintenir a la main,
// et donne a chaque file un seul producteur, ce qui la laisse sans verrou.
//
// QUI FERME. Chaque socket TCP est lue par un fil et ecrite par l'autre. La
// regle est donc que personne ne ferme pendant une session : les deux fils
// n'utilisent que send_all_raw et recv_exact_raw, qui rapportent sans fermer.
// Le fil de supervision attend l'arret des deux, ferme, puis rouvre.
#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "raven/producer.h"      // now_ns
#include "raven/sockets.h"
#include "raven/spsc.h"
#include "sources.h"

namespace raven {
namespace {

// Profondeur de chaque file : de quoi absorber un hoquet du moteur sans
// grossir la memoire. A 1 kHz, 1024 trames laissent une seconde de retard.
constexpr std::size_t kSlots = 1024;
// Delai des attentes bloquantes. Assez court pour que l'arret soit franc,
// assez long pour ne pas tourner a vide.
constexpr int kWaitMs = 20;

struct Way {                             // un sens du relais
    Direction dir = Direction::None;
    const ChannelDesc* ch = nullptr;     // canal transporte
    std::unique_ptr<FrameQueue> queue;
    std::vector<unsigned char> out;      // tampon de sortie du consommateur
    std::atomic<uint64_t> relayed{0};    // messages effectivement transferes
    std::thread th;
    bool active() const { return ch != nullptr; }
};

class RelayBase : public ISource {
public:
    RelayBase(std::string kind, const std::string& arg, const Descriptor& d)
        : kind_(std::move(kind)), spec_(arg) {
        std::vector<std::string> parts = split(arg, '|');
        if (parts.size() != 4) {
            fatal_ = "attendu <ecoute>|<vers>|<canal A>B>|<canal B>A>, recu : " + arg;
            return;
        }
        if (!net::Endpoint::parse(parts[0], listen_)) {
            fatal_ = "adresse d'ecoute invalide : " + parts[0];
            return;
        }
        if (!net::Endpoint::parse(parts[1], forward_) || forward_.port == 0) {
            fatal_ = "adresse de destination invalide : " + parts[1];
            return;
        }
        ways_[0].dir = Direction::AtoB;
        ways_[1].dir = Direction::BtoA;
        for (int i = 0; i < 2; ++i) {
            if (parts[2 + i].empty()) continue;
            for (const ChannelDesc& c : d.channels())
                if (c.name == parts[2 + i]) ways_[i].ch = &c;
            if (!ways_[i].ch) { fatal_ = "canal inconnu : " + parts[2 + i]; return; }
        }
        if (!ways_[0].active() && !ways_[1].active()) {
            fatal_ = "aucun sens a relayer : nommer au moins un canal";
            return;
        }
        for (Way& w : ways_) {
            if (!w.active()) continue;
            w.queue.reset(new FrameQueue(kSlots, w.ch->size));
            w.out.resize(w.ch->size);
        }
    }

    ~RelayBase() override { shutdown(); }

    std::string describe() const override { return kind_ + ":" + spec_; }
    bool connected() const override { return up_.load(std::memory_order_relaxed); }

    // Trames d'OBSERVATION perdues : la file etait pleine, le moteur en
    // retard. Aucun message relaye n'est jamais perdu de ce fait.
    uint64_t lost() const override {
        uint64_t n = 0;
        for (const Way& w : ways_)
            if (w.queue) n += w.queue->dropped();
        return n;
    }

    const std::string& error() const override {
        if (!fatal_.empty()) return fatal_;
        std::lock_guard<std::mutex> l(em_);
        return error_;
    }

    size_t poll(const FrameHandler& on_frame) override {
        if (!fatal_.empty()) return 0;
        if (!started_) { started_ = true; supervisor_ = std::thread([this] { supervise(); }); }
        size_t n = 0;
        // Les deux sens a tour de role, pour qu'un flux rapide d'un cote
        // n'affame pas l'autre dans le journal.
        bool again = true;
        while (again && n < 4096) {
            again = false;
            for (Way& w : ways_) {
                if (!w.queue) continue;
                Frame f;
                if (!w.queue->pop(f, w.out.data())) continue;
                f.no = ++delivered_;
                on_frame(f);
                ++n;
                again = true;
            }
        }
        return n;
    }

    // Messages transferes par sens, pour les rapports et les tests.
    uint64_t relayed(Direction dir) const {
        for (const Way& w : ways_)
            if (w.dir == dir) return w.relayed.load(std::memory_order_relaxed);
        return 0;
    }

protected:
    // Ouverture d'une session. Attendre A n'est pas un echec : confondre les
    // deux ferait payer le delai de reprise a chaque tour d'attente, et une
    // connexion mettrait une demi-seconde a s'etablir pour rien.
    enum class Open { Ready, Waiting, Failed };
    virtual Open open_session() = 0;
    virtual void run_way(Way& w) = 0;
    virtual void close_session() = 0;

    void note(const std::string& text) {
        std::lock_guard<std::mutex> l(em_);
        error_ = text;
    }
    void clear_note() {
        std::lock_guard<std::mutex> l(em_);
        error_.clear();
    }

    void publish(Way& w, const unsigned char* data, uint32_t size) {
        w.queue->push(0, now_ns(), w.ch->id, w.dir, data, size);
    }

    bool session_alive() const { return alive_.load(std::memory_order_relaxed); }
    void end_session() { alive_.store(false, std::memory_order_relaxed); }
    bool stopping() const { return stop_.load(std::memory_order_relaxed); }

    static std::vector<std::string> split(const std::string& s, char sep) {
        std::vector<std::string> out(1);
        for (char c : s) {
            if (c == sep) out.push_back(std::string());
            else out.back().push_back(c);
        }
        return out;
    }

    std::string kind_, spec_, fatal_;
    net::Endpoint listen_, forward_;
    Way ways_[2];

private:
    void supervise() {
        while (!stopping()) {
            const Open opened = open_session();
            if (opened != Open::Ready) {
                close_session();
                if (opened == Open::Failed)
                    for (int i = 0; i < 50 && !stopping(); ++i)   // une tentative / 500 ms
                        std::this_thread::sleep_for(std::chrono::milliseconds(10));
                continue;
            }
            alive_.store(true, std::memory_order_relaxed);
            up_.store(true, std::memory_order_relaxed);
            clear_note();
            for (Way& w : ways_)
                if (w.active()) w.th = std::thread([this, &w] { run_way(w); });
            for (Way& w : ways_)
                if (w.th.joinable()) w.th.join();
            // Les deux sens sont arretes : personne ne touche plus aux
            // sockets, on peut fermer sans risque.
            up_.store(false, std::memory_order_relaxed);
            close_session();
        }
    }

    void shutdown() {
        stop_.store(true, std::memory_order_relaxed);
        end_session();
        if (supervisor_.joinable()) supervisor_.join();
    }

    mutable std::mutex em_;
    std::string error_;
    std::thread supervisor_;
    std::atomic<bool> stop_{false}, alive_{false}, up_{false};
    uint64_t delivered_ = 0;
    bool started_ = false;
};

// ------------------------------------------------------------------ TCP
// A nous joint, nous joignons B. Le flux n'a pas de frontieres : on le
// decoupe en messages de la taille du canal du sens, ce qui suppose un seul
// type de struct par sens. C'est la premiere etape prevue ; une table
// identifiant -> type viendra plus tard.
class TcpRelay : public RelayBase {
public:
    TcpRelay(const std::string& arg, const Descriptor& d) : RelayBase("tcp", arg, d) {}

protected:
    Open open_session() override {
        if (!server_.valid() && !server_.listen(listen_)) {
            note("ecoute impossible sur " + listen_.str() + " : " + server_.error());
            return Open::Failed;
        }
        note("en attente de A sur " + listen_.str());
        a_ = server_.accept(50);
        if (!a_.valid()) return Open::Waiting;        // A n'est pas encore la
        if (!b_.connect(forward_, 2000)) {
            note("B injoignable sur " + forward_.str() + " : " + b_.error());
            return Open::Failed;
        }
        return Open::Ready;
    }

    void run_way(Way& w) override {
        const net::TcpSocket& from = w.dir == Direction::AtoB ? a_ : b_;
        const net::TcpSocket& to = w.dir == Direction::AtoB ? b_ : a_;
        std::vector<unsigned char> buf(w.ch->size);
        while (session_alive() && !stopping()) {
            const net::Io got = from.recv_exact_raw(buf.data(), buf.size(), kWaitMs);
            if (got == net::Io::Timeout) continue;
            if (got == net::Io::Closed) {
                note(std::string(direction_name(w.dir)) + " : connexion rompue");
                end_session();                        // l'autre sens s'arrete aussi
                return;
            }
            // 1. transferer d'abord : c'est la fonction vitale.
            if (!to.send_all_raw(buf.data(), buf.size(), kWaitMs * 10)) {
                note(std::string(direction_name(w.dir)) + " : transfert impossible");
                end_session();
                return;
            }
            w.relayed.fetch_add(1, std::memory_order_relaxed);
            // 2. puis observer, sans jamais attendre le moteur.
            publish(w, buf.data(), uint32_t(buf.size()));
        }
    }

    void close_session() override {
        a_.close();
        b_.close();
    }

private:
    net::TcpListener server_;
    net::TcpSocket a_, b_;
};

// ------------------------------------------------------------------ UDP
// Sans connexion : on lie le port d'ecoute, et l'adresse de A est celle du
// premier datagramme recu. Une socket UDP est ici lue par un fil et ecrite par
// l'autre, comme en TCP, et pour la meme raison : recv_from bloque.
class UdpRelay : public RelayBase {
public:
    UdpRelay(const std::string& arg, const Descriptor& d) : RelayBase("udp", arg, d) {}

protected:
    Open open_session() override {
        if (!in_.bind(listen_)) {
            note("ecoute impossible sur " + listen_.str() + " : " + in_.error());
            return Open::Failed;
        }
        if (!out_.bind(net::Endpoint("0.0.0.0", 0))) {
            note("socket d'emission impossible : " + out_.error());
            return Open::Failed;
        }
        note("en attente d'un datagramme sur " + listen_.str());
        return Open::Ready;
    }

    void run_way(Way& w) override {
        std::vector<unsigned char> buf(w.ch->size ? w.ch->size : 1);
        net::Endpoint from;
        while (session_alive() && !stopping()) {
            if (w.dir == Direction::AtoB) {
                const long got = in_.recv_from(buf.data(), buf.size(), from, kWaitMs);
                if (got <= 0) continue;
                if (uint32_t(got) != w.ch->size) { ++malformed_; continue; }
                remember_a(from);
                if (out_.send_to(buf.data(), size_t(got), forward_) == got)
                    w.relayed.fetch_add(1, std::memory_order_relaxed);
                publish(w, buf.data(), uint32_t(got));
            } else {
                // B repond a la socket d'emission : c'est elle qu'on ecoute.
                const long got = out_.recv_from(buf.data(), buf.size(), from, kWaitMs);
                if (got <= 0) continue;
                if (uint32_t(got) != w.ch->size) { ++malformed_; continue; }
                net::Endpoint a;
                if (!peer_a(a)) continue;             // A ne s'est pas encore annonce
                if (in_.send_to(buf.data(), size_t(got), a) == got)
                    w.relayed.fetch_add(1, std::memory_order_relaxed);
                publish(w, buf.data(), uint32_t(got));
            }
        }
    }

    void close_session() override {
        in_.close();
        out_.close();
        std::lock_guard<std::mutex> l(am_);
        a_known_ = false;
    }

private:
    void remember_a(const net::Endpoint& e) {
        std::lock_guard<std::mutex> l(am_);
        if (!a_known_ || !(a_ == e)) { a_ = e; a_known_ = true; }
    }
    bool peer_a(net::Endpoint& out) const {
        std::lock_guard<std::mutex> l(am_);
        if (!a_known_) return false;
        out = a_;
        return true;
    }

    net::UdpSocket in_, out_;
    // L'adresse de A est ecrite par le fil A>B et lue par le fil B>A : un
    // Endpoint est une chaine et un entier, il faut donc un verrou. Il n'est
    // pris qu'une fois par datagramme, hors du chemin de transfert.
    mutable std::mutex am_;
    net::Endpoint a_;
    bool a_known_ = false;
    uint64_t malformed_ = 0;
};

} // namespace

std::unique_ptr<ISource> make_tcp_relay(const std::string& arg, const Descriptor& d) {
    return std::unique_ptr<ISource>(new TcpRelay(arg, d));
}

std::unique_ptr<ISource> make_udp_relay(const std::string& arg, const Descriptor& d) {
    return std::unique_ptr<ISource>(new UdpRelay(arg, d));
}

} // namespace raven
