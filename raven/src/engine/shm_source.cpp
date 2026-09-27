// Plugin "shm" : lit l'anneau publie par la glue generee (producer.h).
#include <atomic>
#include <cstring>
#include <vector>

#include "raven/producer.h"
#include "raven/source.h"

namespace raven {

class ShmSource : public ISource {
public:
    ShmSource(std::string name, const Descriptor& d) : name_(std::move(name)), desc_(d) {}

    std::string describe() const override { return "shm:" + name_; }
    bool connected() const override { return hdr_ != nullptr; }
    uint64_t lost() const override { return lost_; }
    const std::string& error() const override { return error_; }

    size_t poll(const FrameHandler& on_frame) override {
        if (!hdr_ && !attach()) return 0;
        const uint64_t published = hdr_->published.load(std::memory_order_acquire);
        if (published < last_) {                     // producteur relance
            last_ = 0;
        }
        if (last_ == 0 && published > 0) last_ = published - 1;   // on commence au present
        size_t n = 0;
        const uint64_t slots = hdr_->slot_count;
        if (published > last_ + slots) {             // trop de retard : trames ecrasees
            lost_ += published - last_ - slots;
            last_ = published - slots;
        }
        for (uint64_t k = last_ + 1; k <= published; ++k) {
            if (!copy_slot(k)) { ++lost_; continue; }
            Frame f;
            f.no = k;
            f.t_ns = t_ns_;
            f.data = buf_.data();
            f.size = uint32_t(buf_.size());
            on_frame(f);
            ++n;
        }
        if (published != last_) idle_since_ = now_ns();
        last_ = published;
        // Plus rien depuis une seconde : le simulateur a peut-etre ete relance
        // sur un nouveau segment. On se detache pour rouvrir au prochain appel.
        if (n == 0 && now_ns() - idle_since_ > 1000000000ull) {
            shm_.close();
            hdr_ = nullptr;
            error_ = "plus de trames : reconnexion";
        }
        return n;
    }

private:
    bool attach() {
        // Ouvre d'abord l'en-tete seul pour connaitre la taille de l'anneau.
        SharedMemory probe;
        if (!probe.open(name_, sizeof(RingHeader))) { error_ = "en attente du simulateur"; return false; }
        const auto* h = static_cast<const RingHeader*>(probe.data());
        if (std::memcmp(h->magic, kRingMagic, sizeof(kRingMagic)) != 0) { error_ = "anneau non initialise"; return false; }
        if (h->schema_hash != desc_.schema()) {
            error_ = "schema different du .rvndesc : relancer scry raven";
            return false;
        }
        if (h->frame_size != desc_.frame_size()) { error_ = "taille de trame differente"; return false; }
        const size_t bytes = ring_bytes(h->frame_size, h->slot_count);
        probe.close();
        if (!shm_.open(name_, bytes)) { error_ = "ouverture de l'anneau impossible"; return false; }
        hdr_ = static_cast<RingHeader*>(shm_.data());
        buf_.assign(hdr_->frame_size, 0);
        last_ = 0;
        idle_since_ = now_ns();
        error_.clear();
        return true;
    }

    // Copie coherente de la trame k, ou false si elle a ete reecrite.
    bool copy_slot(uint64_t k) {
        auto* base = reinterpret_cast<unsigned char*>(hdr_ + 1);
        auto* s = reinterpret_cast<SlotHeader*>(base + size_t(k % hdr_->slot_count) * hdr_->slot_stride);
        const uint64_t s1 = s->seq.load(std::memory_order_acquire);
        if (s1 & 1) return false;
        std::memcpy(buf_.data(), s + 1, buf_.size());
        const uint64_t no = s->frame_no;
        t_ns_ = s->t_ns;
        std::atomic_thread_fence(std::memory_order_acquire);
        return s->seq.load(std::memory_order_relaxed) == s1 && no == k;
    }

    std::string name_;
    const Descriptor& desc_;
    SharedMemory shm_;
    RingHeader* hdr_ = nullptr;
    std::vector<unsigned char> buf_;
    uint64_t last_ = 0, lost_ = 0, t_ns_ = 0, idle_since_ = 0;
    std::string error_;
};

std::unique_ptr<ISource> make_source(const std::string& spec, const Descriptor& d) {
    const size_t colon = spec.find(':');
    const std::string type = spec.substr(0, colon);
    const std::string arg = colon == std::string::npos ? "" : spec.substr(colon + 1);
    if (type == "shm") return std::unique_ptr<ISource>(new ShmSource(arg, d));
    return nullptr;
}

} // namespace raven
