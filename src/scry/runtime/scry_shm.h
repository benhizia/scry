// =============================================================================
//  Scry - canal de memoire partagee, protocole seqlock.
//
//  Header autonome, C++17, sans dependance : a inclure dans l'application qui
//  publie ses donnees, dans le producteur de demonstration genere par
//  'scry producer', et dans tout lecteur C++. Le lecteur Python est
//  scry.runtime.shm, qui suit le meme protocole.
//
//  Segment : un en-tete de 128 octets, puis la charge utile, c'est-a-dire les
//  octets bruts d'une instance, lus ensuite par offset d'apres le modele.
//
//     offset  taille  champ
//          0       4  magic         'SCRY', 0x59524353 en little-endian
//          4       4  version       kVersion
//          8       4  header_size   128
//         12       4  payload_size  sizeof du type publie
//         16       8  sequence      compteur seqlock, impair pendant l'ecriture
//         24       8  timestamp_ns  horloge du producteur a la derniere publication
//         32      96  type_name     nom qualifie du type, termine par un zero
//
//  Seqlock : l'ecrivain rend la sequence impaire, copie la charge utile, puis
//  la rend paire. Le lecteur lit la sequence, copie, relit : si elle est
//  impaire ou a change, la copie est dechiree et il recommence. Aucun verrou,
//  l'ecrivain n'attend jamais le lecteur. Un seul ecrivain par segment.
//
//  Nom du segment : 'scry_moteur' par exemple, sans '/'. Sous POSIX il devient
//  '/scry_moteur' (shm_open), sous Windows un mapping de fichier nomme :
//  c'est ce qu'attend multiprocessing.shared_memory cote Python.
// =============================================================================
#pragma once

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace scry {
namespace shm {

constexpr std::uint32_t kMagic = 0x59524353u;  // "SCRY"
constexpr std::uint32_t kVersion = 1u;
constexpr std::size_t kTypeNameSize = 96;

struct Header
{
    std::uint32_t magic;
    std::uint32_t version;
    std::uint32_t header_size;
    std::uint32_t payload_size;
    std::atomic<std::uint64_t> sequence;
    std::uint64_t timestamp_ns;
    char type_name[kTypeNameSize];
};

// Le lecteur Python code ces offsets en dur : ils font partie du protocole.
static_assert(sizeof(std::atomic<std::uint64_t>) == 8, "atomic<uint64_t> de 8 octets requis");
static_assert(std::atomic<std::uint64_t>::is_always_lock_free, "atomic<uint64_t> sans verrou requis");
static_assert(offsetof(Header, sequence) == 16, "protocole Scry : sequence a l'offset 16");
static_assert(offsetof(Header, timestamp_ns) == 24, "protocole Scry : timestamp_ns a l'offset 24");
static_assert(offsetof(Header, type_name) == 32, "protocole Scry : type_name a l'offset 32");
static_assert(sizeof(Header) == 128, "protocole Scry : en-tete de 128 octets");

// -----------------------------------------------------------------------------
// Segment nomme, cree par l'ecrivain ou ouvert par un lecteur.
// -----------------------------------------------------------------------------
class Segment
{
public:
    Segment(const std::string& name, std::size_t size, bool create) : size_(size)
    {
        if (name.empty() || name.find('/') != std::string::npos)
            throw std::invalid_argument("scry::shm : nom de segment vide ou contenant '/'");
#if defined(_WIN32)
        if (create) {
            handle_ = CreateFileMappingA(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
                                         static_cast<DWORD>(static_cast<std::uint64_t>(size) >> 32),
                                         static_cast<DWORD>(size & 0xFFFFFFFFu), name.c_str());
        } else {
            handle_ = OpenFileMappingA(FILE_MAP_READ, FALSE, name.c_str());
        }
        if (handle_ == nullptr)
            throw std::runtime_error("scry::shm : mapping '" + name + "' indisponible, erreur " +
                                     std::to_string(GetLastError()));
        data_ = MapViewOfFile(handle_, create ? FILE_MAP_ALL_ACCESS : FILE_MAP_READ, 0, 0,
                              create ? size : 0);
        if (data_ == nullptr) {
            CloseHandle(handle_);
            throw std::runtime_error("scry::shm : MapViewOfFile a echoue, erreur " +
                                     std::to_string(GetLastError()));
        }
        if (!create) {
            MEMORY_BASIC_INFORMATION info{};
            VirtualQuery(data_, &info, sizeof(info));
            size_ = info.RegionSize;
        }
#else
        path_ = "/" + name;
        fd_ = shm_open(path_.c_str(), create ? (O_CREAT | O_RDWR) : O_RDONLY, 0666);
        if (fd_ < 0)
            throw std::runtime_error("scry::shm : shm_open('" + path_ + "') a echoue");
        if (create && ftruncate(fd_, static_cast<off_t>(size)) != 0) {
            close(fd_);
            throw std::runtime_error("scry::shm : ftruncate a echoue");
        }
        if (!create) {
            struct stat st {};
            fstat(fd_, &st);
            size_ = static_cast<std::size_t>(st.st_size);
        }
        data_ = mmap(nullptr, size_, create ? (PROT_READ | PROT_WRITE) : PROT_READ, MAP_SHARED,
                     fd_, 0);
        if (data_ == MAP_FAILED) {
            close(fd_);
            throw std::runtime_error("scry::shm : mmap a echoue");
        }
        owner_ = create;
#endif
    }

    ~Segment()
    {
#if defined(_WIN32)
        UnmapViewOfFile(data_);
        CloseHandle(handle_);
#else
        munmap(data_, size_);
        close(fd_);
        // Sous POSIX le segment survit au processus : l'ecrivain le retire.
        // Sous Windows il disparait avec le dernier handle.
        if (owner_)
            shm_unlink(path_.c_str());
#endif
    }

    Segment(const Segment&) = delete;
    Segment& operator=(const Segment&) = delete;

    void* data() const { return data_; }
    std::size_t size() const { return size_; }

private:
    std::size_t size_;
    void* data_ = nullptr;
#if defined(_WIN32)
    HANDLE handle_ = nullptr;
#else
    int fd_ = -1;
    std::string path_;
    bool owner_ = false;
#endif
};

// -----------------------------------------------------------------------------
// Ecrivain : un seul par segment.
//
//     scry::shm::Publisher pub("scry_moteur", sizeof(Moteur), "moteur::Etat");
//     pub.publish(etat);      // a chaque mise a jour
// -----------------------------------------------------------------------------
class Publisher
{
public:
    Publisher(const std::string& name, std::size_t payload_size, const char* type_name)
        : segment_(name, sizeof(Header) + payload_size, true), payload_size_(payload_size)
    {
        Header* h = header();
        h->magic = kMagic;
        h->version = kVersion;
        h->header_size = static_cast<std::uint32_t>(sizeof(Header));
        h->payload_size = static_cast<std::uint32_t>(payload_size);
        h->sequence.store(0, std::memory_order_relaxed);
        h->timestamp_ns = 0;
        std::memset(h->type_name, 0, kTypeNameSize);
        std::strncpy(h->type_name, type_name, kTypeNameSize - 1);
    }

    // Copie payload_size octets depuis data.
    void publish_bytes(const void* data)
    {
        Header* h = header();
        const std::uint64_t seq = h->sequence.load(std::memory_order_relaxed);
        h->sequence.store(seq + 1, std::memory_order_relaxed);   // impair : ecriture
        std::atomic_thread_fence(std::memory_order_release);
        std::memcpy(payload(), data, payload_size_);
        h->timestamp_ns = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count());
        h->sequence.store(seq + 2, std::memory_order_release);   // pair : stable
    }

    // Les octets de l'objet, tels quels : pointeurs et vtable compris, qui
    // n'ont de sens que dans ce processus. Le lecteur lit par offset.
    template <typename T>
    void publish(const T& object)
    {
        if (sizeof(T) != payload_size_)
            throw std::logic_error("scry::shm : sizeof du type publie != payload_size");
        publish_bytes(static_cast<const void*>(&object));
    }

    std::uint64_t sequence() const { return header()->sequence.load(std::memory_order_relaxed); }

private:
    Header* header() const { return static_cast<Header*>(segment_.data()); }
    std::uint8_t* payload() const
    {
        return static_cast<std::uint8_t*>(segment_.data()) + sizeof(Header);
    }

    Segment segment_;
    std::size_t payload_size_;
};

// -----------------------------------------------------------------------------
// Lecteur : copie coherente de la charge utile.
// -----------------------------------------------------------------------------
class Reader
{
public:
    explicit Reader(const std::string& name) : segment_(name, 0, false)
    {
        if (segment_.size() < sizeof(Header))
            throw std::runtime_error("scry::shm : segment trop petit pour un en-tete Scry");
        const Header* h = header();
        if (h->magic != kMagic)
            throw std::runtime_error("scry::shm : ce segment n'est pas un canal Scry");
        if (h->version != kVersion)
            throw std::runtime_error("scry::shm : version de protocole " +
                                     std::to_string(h->version) + " non geree");
        if (segment_.size() < h->header_size + std::size_t(h->payload_size))
            throw std::runtime_error("scry::shm : segment plus petit que sa charge annoncee");
    }

    std::size_t payload_size() const { return header()->payload_size; }
    const char* type_name() const { return header()->type_name; }
    std::uint64_t timestamp_ns() const { return header()->timestamp_ns; }

    // Copie la charge utile dans out, payload_size() octets. Retourne la
    // sequence de la copie, ou 0 si aucune copie coherente en max_tries
    // essais (ecrivain qui n'a encore rien publie, ou qui publie sans cesse).
    std::uint64_t snapshot(void* out, int max_tries = 100) const
    {
        const Header* h = header();
        for (int i = 0; i < max_tries; ++i) {
            const std::uint64_t before = h->sequence.load(std::memory_order_acquire);
            if (before == 0 || (before & 1u))
                continue;
            std::memcpy(out, payload(), h->payload_size);
            std::atomic_thread_fence(std::memory_order_acquire);
            if (h->sequence.load(std::memory_order_relaxed) == before)
                return before;
        }
        return 0;
    }

private:
    const Header* header() const { return static_cast<const Header*>(segment_.data()); }
    const std::uint8_t* payload() const
    {
        return static_cast<const std::uint8_t*>(segment_.data()) + header()->header_size;
    }

    Segment segment_;
};

}  // namespace shm
}  // namespace scry
