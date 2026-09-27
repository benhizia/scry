// Anneau de trames en memoire partagee : le contrat entre le simulateur et
// raven.exe. Header seul, sans dependance, inclus par la glue generee.
//
// Le simulateur ecrit la trame n dans l'emplacement n % slots, puis publie n.
// raven.exe lit toutes les trames de sa derniere lue jusqu'a la derniere
// publiee : un retard de moins de 'slots' trames ne perd rien, au-dela chaque
// trame manquante est comptee. Chaque emplacement porte un compteur de sequence
// (impair pendant l'ecriture) pour detecter une lecture pendant une reecriture.
#pragma once
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <string>

#include "shm.h"

namespace raven {

constexpr char     kRingMagic[8] = {'R', 'A', 'V', 'E', 'N', 'R', 'G', '1'};
constexpr uint32_t kRingVersion  = 1;

struct RingHeader {
    char     magic[8];
    uint32_t version;
    uint32_t slot_count;
    uint64_t schema_hash;        // doit egaler celui du .rvndesc
    uint32_t frame_size;
    uint32_t slot_stride;        // SlotHeader + frame_size, arrondi a 64
    std::atomic<uint64_t> published;   // numero de la derniere trame, 0 = aucune
    uint8_t  pad[64 - 40];
};
static_assert(sizeof(RingHeader) == 64, "RingHeader");

struct SlotHeader {
    std::atomic<uint64_t> seq;   // impair : ecriture en cours
    uint64_t frame_no;           // numero de la trame contenue
    uint64_t t_ns;               // horodatage du producteur (horloge monotone)
    uint64_t pad;
};
static_assert(sizeof(SlotHeader) == 32, "SlotHeader");

inline uint32_t slot_stride(uint32_t frame_size) {
    return (uint32_t(sizeof(SlotHeader)) + frame_size + 63u) & ~63u;
}
inline size_t ring_bytes(uint32_t frame_size, uint32_t slots) {
    return sizeof(RingHeader) + size_t(slot_stride(frame_size)) * slots;
}
inline uint64_t now_ns() {
    return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}

// Cote simulateur.
class Producer {
public:
    bool create(const std::string& name, uint64_t schema, uint32_t frame_size, uint32_t slots) {
        if (!shm_.create(name, ring_bytes(frame_size, slots))) return false;
        std::memset(shm_.data(), 0, shm_.size());
        hdr_ = static_cast<RingHeader*>(shm_.data());
        hdr_->version = kRingVersion;
        hdr_->slot_count = slots;
        hdr_->schema_hash = schema;
        hdr_->frame_size = frame_size;
        hdr_->slot_stride = slot_stride(frame_size);
        std::memcpy(hdr_->magic, kRingMagic, sizeof(kRingMagic));   // en dernier : pret
        return true;
    }

    unsigned char* begin_frame() {
        next_ = hdr_->published.load(std::memory_order_relaxed) + 1;
        slot_ = slot(next_);
        slot_->seq.fetch_add(1, std::memory_order_acq_rel);          // impair
        std::atomic_thread_fence(std::memory_order_release);
        return reinterpret_cast<unsigned char*>(slot_ + 1);
    }

    void end_frame() {
        slot_->frame_no = next_;
        slot_->t_ns = now_ns();
        slot_->seq.fetch_add(1, std::memory_order_release);          // pair
        hdr_->published.store(next_, std::memory_order_release);
    }

    uint64_t published() const { return hdr_ ? hdr_->published.load() : 0; }

private:
    SlotHeader* slot(uint64_t n) {
        auto* base = reinterpret_cast<unsigned char*>(hdr_ + 1);
        return reinterpret_cast<SlotHeader*>(base + size_t(n % hdr_->slot_count) * hdr_->slot_stride);
    }

    SharedMemory shm_;
    RingHeader* hdr_ = nullptr;
    SlotHeader* slot_ = nullptr;
    uint64_t next_ = 0;
};

} // namespace raven
