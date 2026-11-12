// Sockets de donnees du mode reseau : TCP, UDP et multicast, Windows et POSIX.
// Reprises des connexions de SwitchSpy (InterfaceInspector), renommees et
// simplifiees : une socket appartient a un seul fil, donc ni mutex ni rappels ;
// toutes les attentes ont un delai ; aucune n'a de singleton.
//
// Conventions de retour, partout :
//   > 0  octets transferes
//   0    rien pour l'instant (delai ecoule ou envoi qui bloquerait)
//   -1   socket fermee ou en erreur : voir error()
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>

namespace raven {
namespace net {

bool init();                     // WSAStartup sous Windows ; sans effet ailleurs

struct Endpoint {
    std::string host;            // adresse IPv4 ou nom
    uint16_t port = 0;

    Endpoint() = default;
    Endpoint(std::string h, uint16_t p) : host(std::move(h)), port(p) {}
    // "192.168.1.10:8001", ":8001" ou "8001" (hote 0.0.0.0).
    static bool parse(const std::string& text, Endpoint& out);
    std::string str() const { return host + ":" + std::to_string(port); }
    bool operator==(const Endpoint& o) const { return host == o.host && port == o.port; }
};

// Descripteur possede, deplacable, ferme a la destruction.
class Socket {
public:
    Socket() = default;
    Socket(const Socket&) = delete;
    Socket& operator=(const Socket&) = delete;
    Socket(Socket&& o) noexcept : fd_(o.fd_), error_(std::move(o.error_)) { o.fd_ = -1; }
    Socket& operator=(Socket&& o) noexcept;
    ~Socket() { close(); }

    bool valid() const { return fd_ >= 0; }
    void close();
    const std::string& error() const { return error_; }
    uint16_t local_port() const;               // 0 si inconnue
    intptr_t native() const { return fd_; }

protected:
    explicit Socket(intptr_t fd) : fd_(fd) {}
    bool open(int type);                        // SOCK_STREAM ou SOCK_DGRAM
    bool fail(const char* what);                // note l'erreur, ferme, false
    intptr_t fd_ = -1;
    std::string error_;
};

// Resultat d'une entree-sortie du chemin partage, ou l'on ne peut pas se
// contenter de "-1 quelque chose a casse" : un delai ecoule et une connexion
// fermee demandent deux conduites differentes.
enum class Io { Ok, Timeout, Closed };

class TcpSocket : public Socket {
public:
    TcpSocket() = default;
    // Connexion suivie jusqu'au bout : reussie, refusee ou delai ecoule.
    bool connect(const Endpoint& to, int timeout_ms);
    long send(const void* data, size_t size);  // non bloquant
    bool send_all(const void* data, size_t size, int timeout_ms);
    long recv(void* buf, size_t size, int timeout_ms);
    // Lit exactement 'size' octets (un message de taille connue), ou false.
    bool recv_all(void* buf, size_t size, int timeout_ms);
    Endpoint peer() const;

    // --- chemin d'un relais : deux fils, une seule socket ------------------
    // Un relais a un fil par sens. Chaque socket est alors LUE par un fil et
    // ECRITE par l'autre, ce que le systeme accepte sans reserve. Ce que le
    // systeme n'accepte pas, c'est que l'un ferme la socket sous les pieds de
    // l'autre, ni que les deux ecrivent error_ en meme temps.
    //
    // Ces deux methodes ne ferment donc rien et ne touchent pas a error_ :
    // elles rapportent, et c'est tout. La regle qui en decoule, et que le
    // relais applique, est simple : PENDANT une session, personne ne ferme ;
    // c'est le fil de supervision qui ferme, entre deux sessions, une fois les
    // fils de sens arretes.
    bool send_all_raw(const void* data, size_t size, int timeout_ms) const;
    // Lit un message entier. Timeout seulement si RIEN n'est arrive : un
    // message commence est attendu jusqu'au bout, car le decouper n'aurait
    // aucun sens.
    Io recv_exact_raw(void* buf, size_t size, int timeout_ms) const;

private:
    friend class TcpListener;
    explicit TcpSocket(intptr_t fd) : Socket(fd) {}
};

class TcpListener : public Socket {
public:
    bool listen(const Endpoint& at, int backlog = 4);   // port 0 : choisi par le systeme
    // Client en attente, ou socket invalide apres timeout_ms.
    TcpSocket accept(int timeout_ms, Endpoint* peer = nullptr);
};

class UdpSocket : public Socket {
public:
    bool bind(const Endpoint& at);                     // port 0 : choisi par le systeme
    long send_to(const void* data, size_t size, const Endpoint& to);
    long recv_from(void* buf, size_t size, Endpoint& from, int timeout_ms);
    // Tampon de reception du systeme : un abonne qui suit un flux rapide doit
    // absorber les rafales pendant qu'il traite. false si refuse.
    bool set_receive_buffer(int bytes);
    // Plus grande charge utile d'un datagramme sans fragmentation IP sur un
    // reseau Ethernet (MTU 1500 - 20 IP - 8 UDP).
    static constexpr size_t kSafePayload = 1472;
};

// Abonnement a un groupe multicast, et emission vers ce groupe.
class MulticastSocket : public UdpSocket {
public:
    ~MulticastSocket() { leave(); }
    // Rejoint 'group' (239.x.y.z:port). 'iface' : adresse de l'interface,
    // vide pour laisser le systeme choisir. Plusieurs abonnes du meme poste
    // peuvent ecouter le meme port (SO_REUSEADDR, SO_REUSEPORT).
    bool join(const Endpoint& group, const std::string& iface = "");
    void leave();
    // Cote emetteur : interface de sortie, duree de vie, bouclage local.
    bool open_sender(const Endpoint& group, const std::string& iface = "", int ttl = 1,
                     bool loopback = true);
    long send(const void* data, size_t size);          // vers le groupe
    const Endpoint& group() const { return group_; }

private:
    Endpoint group_;
    std::string iface_;
    bool joined_ = false;
};

} // namespace net
} // namespace raven
