// Sockets TCP minimales, Windows et POSIX : un serveur qui accepte un client,
// un client qui se connecte, et un echange par lignes de texte. Non bloquant.
#pragma once
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
    LineSocket(LineSocket&& o) noexcept : fd_(o.fd_), in_(std::move(o.in_)) { o.fd_ = -1; }
    LineSocket& operator=(LineSocket&& o) noexcept;
    ~LineSocket() { close(); }

    bool connect(const std::string& host, int port);
    bool valid() const { return fd_ >= 0; }
    void close();

    bool send(const std::string& text);            // tout ou rien ; false = coupe
    // Lignes completes recues ; attend au plus timeout_ms. false = coupe.
    bool receive(std::vector<std::string>& lines, int timeout_ms);

private:
    intptr_t fd_ = -1;
    std::string in_;
};

class Listener {
public:
    ~Listener() { close(); }
    bool listen(int port, bool loopback_only = true);
    // Client en attente, ou socket invalide ; attend au plus timeout_ms.
    LineSocket accept(int timeout_ms);
    void close();

private:
    intptr_t fd_ = -1;
};

bool net_init();   // WSAStartup sous Windows ; sans effet ailleurs

} // namespace raven
