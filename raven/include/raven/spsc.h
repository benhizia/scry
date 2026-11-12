// File de trames a UN producteur et UN consommateur, sans verrou.
//
// Pourquoi elle existe : un relais doit recevoir un message, le transferer a
// l'autre equipement, puis en pousser une copie au moteur. Ces trois actes
// n'ont pas la meme importance. Le transfert est la fonction vitale : si RAVEN
// le retarde, il ne se contente pas de mal observer, il degrade le systeme
// qu'il observe. Or Engine::on_frame prend un mutex, partage avec le fil de
// controle et le visualiseur. Appeler le moteur depuis le fil de relais ferait
// donc dependre le temps de transfert de ce que fait l'IHM.
//
// Le relais depose donc ici et repart ; le moteur consomme a son rythme. Quand
// le moteur prend du retard, la file se remplit et l'on perd des trames
// d'OBSERVATION, qui se comptent et s'affichent, comme les pertes de l'anneau
// SHM. On ne perd jamais un message relaye.
//
// Un producteur, un consommateur : c'est la consequence du fil par sens, et
// c'est ce qui permet de s'en tenir a deux indices atomiques, sans verrou, donc
// sans inversion de priorite ni attente non bornee.
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

#include "raven/source.h"

namespace raven {

// C4324 : MSVC previent que la structure est completee a cause d'alignas.
// C'est precisement ce qu'on lui demande, pour que les deux compteurs ne
// partagent pas une ligne de cache.
#if defined(_MSC_VER)
#pragma warning(push)
#pragma warning(disable : 4324)
#endif

class FrameQueue {
public:
    // 'slots' est arrondi a la puissance de deux superieure : l'index se
    // calcule alors par un masque, sans division sur le chemin chaud.
    // 'payload' est la taille du plus grand message attendu.
    FrameQueue(std::size_t slots, std::size_t payload)
        : mask_(round_up(slots) - 1), payload_(payload),
          meta_(round_up(slots)), bytes_(round_up(slots) * payload) {}

    std::size_t capacity() const { return mask_ + 1; }
    std::size_t payload() const { return payload_; }

    // --- cote producteur ---------------------------------------------------
    // false quand la file est pleine ou le message trop grand : la trame est
    // perdue et comptee, et l'appelant continue. Ne bloque jamais.
    bool push(uint64_t no, uint64_t t_ns, int channel, Direction dir,
              const void* data, std::size_t size) {
        if (size > payload_) { ++dropped_; return false; }
        const std::size_t head = head_.load(std::memory_order_relaxed);
        // acquire : voir la progression du consommateur avant de conclure.
        if (head - tail_.load(std::memory_order_acquire) > mask_) { ++dropped_; return false; }
        const std::size_t i = head & mask_;
        Meta& m = meta_[i];
        m.no = no;
        m.t_ns = t_ns;
        m.channel = channel;
        m.dir = dir;
        m.size = uint32_t(size);
        std::memcpy(bytes_.data() + i * payload_, data, size);
        // release : la trame est entierement ecrite avant d'etre annoncee.
        head_.store(head + 1, std::memory_order_release);
        return true;
    }

    // --- cote consommateur -------------------------------------------------
    // Copie la charge utile dans 'out', qui doit accepter payload() octets, et
    // y fait pointer f.data. La copie evite au consommateur de devoir rendre
    // la place avant d'avoir fini de lire.
    bool pop(Frame& f, unsigned char* out) {
        const std::size_t tail = tail_.load(std::memory_order_relaxed);
        if (tail == head_.load(std::memory_order_acquire)) return false;
        const std::size_t i = tail & mask_;
        const Meta& m = meta_[i];
        f.no = m.no;
        f.t_ns = m.t_ns;
        f.channel = m.channel;
        f.dir = m.dir;
        f.size = m.size;
        f.data = out;
        std::memcpy(out, bytes_.data() + i * payload_, m.size);
        tail_.store(tail + 1, std::memory_order_release);
        return true;
    }

    // Trames d'observation perdues faute de place. Le producteur seul l'ecrit.
    uint64_t dropped() const { return dropped_.load(std::memory_order_relaxed); }
    std::size_t size() const {
        return head_.load(std::memory_order_acquire) - tail_.load(std::memory_order_acquire);
    }
    bool empty() const { return size() == 0; }

private:
    struct Meta {
        uint64_t no = 0, t_ns = 0;
        int channel = -1;
        Direction dir = Direction::None;
        uint32_t size = 0;
    };

    static std::size_t round_up(std::size_t n) {
        std::size_t p = 1;
        while (p < n) p <<= 1;
        return p < 2 ? 2 : p;
    }

    // Les deux indices sont montants et ne reviennent jamais en arriere : leur
    // difference donne l'occupation sans cas particulier au recouvrement.
    // alignas : sans cela les deux compteurs partageraient une ligne de cache,
    // et chaque publication invaliderait la ligne lue par l'autre fil.
    alignas(64) std::atomic<std::size_t> head_{0};
    alignas(64) std::atomic<std::size_t> tail_{0};
    alignas(64) std::atomic<uint64_t> dropped_{0};
    std::size_t mask_;
    std::size_t payload_;
    std::vector<Meta> meta_;
    std::vector<unsigned char> bytes_;
};

#if defined(_MSC_VER)
#pragma warning(pop)
#endif

} // namespace raven
