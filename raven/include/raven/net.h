// Sockets TCP minimales, Windows et POSIX : un serveur qui accepte un client,
// un client qui se connecte, et un echange par lignes de texte. Non bloquant.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace raven {

class LineSocket {
public:
    LineSocket() = default;
    explicit LineSocket(intptr_t fd) : fd_(fd) {}
    LineSocket(const LineSocket&) = delete;
    LineSocket& operator=(const LineSocket&) = delete;
    LineSocket(LineSocket&& o) noexcept
        : fd_(o.fd_), in_(std::move(o.in_)), out_(std::move(o.out_)),
          sent_(o.sent_), dropped_(o.dropped_) { o.fd_ = -1; }
    LineSocket& operator=(LineSocket&& o) noexcept;
    ~LineSocket() { close(); }

    bool connect(const std::string& host, int port);
    bool valid() const { return fd_ >= 0; }
    void close();

    bool send(const std::string& text);            // tout ou rien ; false = coupe
    // Lignes completes recues ; attend au plus timeout_ms. false = coupe.
    bool receive(std::vector<std::string>& lines, int timeout_ms);

    // Publication sans jamais bloquer l'appelant. Le texte part tout de suite
    // s'il tient dans le tampon du systeme, sinon il attend dans la file de
    // sortie, que flush() vide au fil des tours de boucle.
    //
    // droppable : une mise a jour periodique, qu'on abandonne quand la file
    // est pleine. Le visualiseur affiche un ETAT, il rattrapera a la mise a
    // jour suivante ; l'enregistrement, lui, est un journal et ne perd rien.
    // Une reponse a une commande n'est jamais abandonnee.
    bool queue(const std::string& text, bool droppable = false);
    bool flush();                                  // false = coupe
    std::size_t pending() const { return out_.size() - sent_; }
    std::size_t dropped() const { return dropped_; }

    static constexpr std::size_t kMaxOutbox = 1u << 20;   // 1 Mio

private:
    intptr_t fd_ = -1;
    std::string in_;
    std::string out_;          // file de sortie, deja serialisee
    std::size_t sent_ = 0;     // octets de out_ deja partis
    std::size_t dropped_ = 0;  // mises a jour abandonnees
};

class Listener {
public:
    ~Listener() { close(); }
    bool listen(int port, bool loopback_only = true);   // port 0 : le systeme choisit
    int port() const;                                  // port reellement ecoute, ou -1
    // Client en attente, ou socket invalide ; attend au plus timeout_ms.
    LineSocket accept(int timeout_ms);
    void close();

private:
    intptr_t fd_ = -1;
};

bool net_init();   // WSAStartup sous Windows ; sans effet ailleurs

} // namespace raven
