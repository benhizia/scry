// Plugin "mcast" : abonne multicast passif. RAVEN ecoute le groupe a cote des
// vrais consommateurs, sans rien leur retirer ; chaque datagramme est un
// message d'un canal du descripteur.
//
//   mcast:<groupe>:<port>[@iface][#canal][?seq=champ]
//
//   @iface   adresse de l'interface qui rejoint le groupe
//   #canal   canal du descripteur transporte (facultatif s'il n'y en a qu'un)
//   ?seq=    champ entier du canal qui numerote les messages : un saut dans
//            la numerotation est compte comme une perte. Sans lui, UDP ne dit
//            rien de ce qui manque.
#include <cstring>
#include <vector>

#include "raven/producer.h"      // now_ns
#include "raven/sockets.h"
#include "sources.h"

namespace raven {

class MulticastSource : public ISource {
public:
    MulticastSource(const std::string& arg, const Descriptor& d) : spec_(arg) {
        std::string rest = arg;
        const size_t q = rest.find("?seq=");
        if (q != std::string::npos) { seq_path_ = rest.substr(q + 5); rest.erase(q); }
        const size_t hash = rest.find('#');
        std::string channel;
        if (hash != std::string::npos) { channel = rest.substr(hash + 1); rest.erase(hash); }
        const size_t at = rest.find('@');
        if (at != std::string::npos) { iface_ = rest.substr(at + 1); rest.erase(at); }
        if (!net::Endpoint::parse(rest, group_) || group_.port == 0) {
            fatal_ = "groupe invalide : " + rest + " (attendu <groupe>:<port>)";
            return;
        }
        for (const ChannelDesc& c : d.channels())
            if (c.name == channel || (channel.empty() && d.channels().size() == 1)) ch_ = &c;
        if (!ch_) {
            fatal_ = channel.empty() ? "plusieurs canaux : preciser #canal" : "canal inconnu : " + channel;
            return;
        }
        if (!seq_path_.empty()) {
            const FieldRef r = d.find(ch_->name + "." + seq_path_);
            const FieldDesc* f = d.field(r);
            if (!f || (f->kind != Kind::Int && f->kind != Kind::UInt) || f->count != 1) {
                fatal_ = "champ de sequence invalide : " + seq_path_;
                return;
            }
            seq_ = f;
        }
        buf_.resize(65536);
    }

    std::string describe() const override { return "mcast:" + spec_; }
    bool connected() const override { return sock_.valid(); }
    uint64_t lost() const override { return lost_; }
    const std::string& error() const override { return fatal_.empty() ? error_ : fatal_; }

    size_t poll(const FrameHandler& on_frame) override {
        if (!fatal_.empty()) return 0;
        if (!sock_.valid() && !attach()) return 0;
        size_t n = 0;
        net::Endpoint from;
        // Attend au plus 1 ms le premier datagramme, puis vide ce qui est arrive.
        for (int wait = 1; n < 4096; wait = 0) {
            const long got = sock_.recv_from(buf_.data(), buf_.size(), from, wait);
            if (got <= 0) break;
            if (uint32_t(got) != ch_->size) {        // pas un message de ce canal
                ++malformed_;
                error_ = "datagramme de " + std::to_string(got) + " octets, attendu " +
                         std::to_string(ch_->size) + " (" + std::to_string(malformed_) + " ignores)";
                continue;
            }
            if (seq_) check_sequence(read_integer(*seq_, buf_.data() + seq_->offset));
            Frame f;
            f.no = ++received_;
            f.t_ns = now_ns();                        // heure de reception
            f.channel = ch_->id;
            f.data = buf_.data();
            f.size = ch_->size;
            on_frame(f);
            ++n;
        }
        return n;
    }

private:
    bool attach() {
        const uint64_t now = now_ns();
        if (now < retry_at_) return false;
        retry_at_ = now + 1000000000ull;              // une tentative par seconde
        if (!sock_.join(group_, iface_)) { error_ = sock_.error(); return false; }
        sock_.set_receive_buffer(8 << 20);            // absorbe les rafales
        error_.clear();
        return true;
    }

    void check_sequence(int64_t s) {
        if (has_seq_ && s > last_seq_ + 1) lost_ += uint64_t(s - last_seq_ - 1);
        if (!has_seq_ || s > last_seq_) last_seq_ = s;   // un doublon ou un retard ne recule pas
        has_seq_ = true;
    }

    std::string spec_, iface_, seq_path_, error_, fatal_;
    net::Endpoint group_;
    const ChannelDesc* ch_ = nullptr;
    const FieldDesc* seq_ = nullptr;
    net::MulticastSocket sock_;
    std::vector<unsigned char> buf_;
    uint64_t received_ = 0, lost_ = 0, malformed_ = 0, retry_at_ = 0;
    int64_t last_seq_ = 0;
    bool has_seq_ = false;
};

std::unique_ptr<ISource> make_mcast_source(const std::string& arg, const Descriptor& d) {
    return std::unique_ptr<ISource>(new MulticastSource(arg, d));
}

} // namespace raven
