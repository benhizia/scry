#include "raven/sockets.h"

#include <cstdlib>

#include "net_platform.h"

namespace raven {
namespace net {

using namespace detail;

bool init() {
#ifdef _WIN32
    WSADATA w;
    return WSAStartup(MAKEWORD(2, 2), &w) == 0;
#else
    return true;
#endif
}

bool Endpoint::parse(const std::string& text, Endpoint& out) {
    const size_t colon = text.rfind(':');
    const std::string host = colon == std::string::npos ? "" : text.substr(0, colon);
    const std::string port = colon == std::string::npos ? text : text.substr(colon + 1);
    char* end = nullptr;
    const long p = std::strtol(port.c_str(), &end, 10);
    if (port.empty() || *end != '\0' || p < 0 || p > 65535) return false;
    out.host = host.empty() ? "0.0.0.0" : host;
    out.port = uint16_t(p);
    return true;
}

// Adresse IPv4 d'un point de terminaison ; resout les noms.
static bool to_sockaddr(const Endpoint& e, sockaddr_in& a) {
    std::memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(e.port);
    if (e.host.empty() || e.host == "0.0.0.0") { a.sin_addr.s_addr = htonl(INADDR_ANY); return true; }
    if (inet_pton(AF_INET, e.host.c_str(), &a.sin_addr) == 1) return true;
    addrinfo hints, *res = nullptr;
    std::memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_INET;
    if (getaddrinfo(e.host.c_str(), nullptr, &hints, &res) != 0 || !res) return false;
    a.sin_addr = reinterpret_cast<sockaddr_in*>(res->ai_addr)->sin_addr;
    freeaddrinfo(res);
    return true;
}

static Endpoint from_sockaddr(const sockaddr_in& a) {
    char buf[INET_ADDRSTRLEN] = "";
    inet_ntop(AF_INET, const_cast<in_addr*>(&a.sin_addr), buf, sizeof buf);
    return Endpoint(buf, ntohs(a.sin_port));
}

// ---------------------------------------------------------------- Socket

Socket& Socket::operator=(Socket&& o) noexcept {
    if (this != &o) {
        close();
        fd_ = o.fd_;
        error_ = std::move(o.error_);
        o.fd_ = -1;
    }
    return *this;
}

void Socket::close() {
    if (fd_ >= 0) RV_CLOSE(fd_);
    fd_ = -1;
}

bool Socket::open(int type) {
    close();
    error_.clear();
    fd_ = intptr_t(socket(AF_INET, type, 0));
    if (fd_ < 0) { fd_ = -1; return fail("socket"); }
    return true;
}

bool Socket::fail(const char* what) {
    error_ = error_text(what);
    close();
    return false;
}

uint16_t Socket::local_port() const {
    sockaddr_in a;
    socklen_t len = sizeof a;
    if (fd_ < 0 || getsockname(fd_, reinterpret_cast<sockaddr*>(&a), &len) != 0) return 0;
    return ntohs(a.sin_port);
}

// ------------------------------------------------------------- TcpSocket

bool TcpSocket::connect(const Endpoint& to, int timeout_ms) {
    sockaddr_in a;
    if (!to_sockaddr(to, a)) { error_ = "adresse inconnue : " + to.host; return false; }
    if (!open(SOCK_STREAM)) return false;
    set_nonblocking(fd_);
    if (::connect(fd_, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) {
        // Connexion non bloquante : on attend qu'elle aboutisse ou echoue,
        // au lieu de la laisser "en cours" sans suivi.
        if (!in_progress()) return fail("connect");
        if (!wait_writable(fd_, timeout_ms)) { error_ = "delai de connexion ecoule"; close(); return false; }
        int err = 0;
        socklen_t len = sizeof err;
        getsockopt(fd_, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&err), &len);
        if (err != 0) { error_ = "connexion refusee (erreur " + std::to_string(err) + ")"; close(); return false; }
    }
    no_delay(fd_);
    return true;
}

long TcpSocket::send(const void* data, size_t size) {
    if (fd_ < 0) return -1;
    const int n = ::send(fd_, static_cast<const char*>(data), int(size), RV_NOSIGNAL);
    if (n < 0 && would_block()) return 0;
    if (n < 0) { fail("send"); return -1; }
    return n;
}

bool TcpSocket::send_all(const void* data, size_t size, int timeout_ms) {
    const char* p = static_cast<const char*>(data);
    while (size > 0) {
        const long n = send(p, size);
        if (n < 0) return false;
        if (n == 0 && !wait_writable(fd_, timeout_ms)) { error_ = "envoi bloque"; return false; }
        p += n;
        size -= size_t(n);
    }
    return true;
}

long TcpSocket::recv(void* buf, size_t size, int timeout_ms) {
    if (fd_ < 0) return -1;
    if (!wait_readable(fd_, timeout_ms)) return 0;
    const int n = ::recv(fd_, static_cast<char*>(buf), int(size), 0);
    if (n < 0 && would_block()) return 0;
    if (n == 0) { error_ = "fermee par le pair"; close(); return -1; }
    if (n < 0) { fail("recv"); return -1; }
    return n;
}

bool TcpSocket::recv_all(void* buf, size_t size, int timeout_ms) {
    char* p = static_cast<char*>(buf);
    while (size > 0) {
        const long n = recv(p, size, timeout_ms);
        if (n <= 0) return false;
        p += n;
        size -= size_t(n);
    }
    return true;
}

Endpoint TcpSocket::peer() const {
    sockaddr_in a;
    socklen_t len = sizeof a;
    if (fd_ < 0 || getpeername(fd_, reinterpret_cast<sockaddr*>(&a), &len) != 0) return Endpoint();
    return from_sockaddr(a);
}

// ----------------------------------------------------------- TcpListener

bool TcpListener::listen(const Endpoint& at, int backlog) {
    sockaddr_in a;
    if (!to_sockaddr(at, a)) { error_ = "adresse inconnue : " + at.host; return false; }
    if (!open(SOCK_STREAM)) return false;
    int one = 1;
    setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&one), sizeof one);
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) return fail("bind");
    if (::listen(fd_, backlog) != 0) return fail("listen");
    return true;
}

TcpSocket TcpListener::accept(int timeout_ms, Endpoint* peer) {
    if (fd_ < 0 || !wait_readable(fd_, timeout_ms)) return TcpSocket();
    sockaddr_in a;
    socklen_t len = sizeof a;
    const intptr_t c = intptr_t(::accept(fd_, reinterpret_cast<sockaddr*>(&a), &len));
    if (c < 0) return TcpSocket();
    no_delay(c);
    set_nonblocking(c);
    if (peer) *peer = from_sockaddr(a);
    return TcpSocket(c);
}

// ------------------------------------------------------------- UdpSocket

bool UdpSocket::bind(const Endpoint& at) {
    sockaddr_in a;
    if (!to_sockaddr(at, a)) { error_ = "adresse inconnue : " + at.host; return false; }
    if (!open(SOCK_DGRAM)) return false;
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) return fail("bind");
    set_nonblocking(fd_);
    return true;
}

long UdpSocket::send_to(const void* data, size_t size, const Endpoint& to) {
    if (fd_ < 0) return -1;
    sockaddr_in a;
    if (!to_sockaddr(to, a)) { error_ = "adresse inconnue : " + to.host; return -1; }
    const int n = ::sendto(fd_, static_cast<const char*>(data), int(size), 0,
                           reinterpret_cast<sockaddr*>(&a), sizeof a);
    if (n < 0 && would_block()) return 0;
    if (n < 0) { error_ = error_text("sendto"); return -1; }   // UDP : on garde la socket
    return n;
}

long UdpSocket::recv_from(void* buf, size_t size, Endpoint& from, int timeout_ms) {
    if (fd_ < 0) return -1;
    if (!wait_readable(fd_, timeout_ms)) return 0;
    sockaddr_in a;
    socklen_t len = sizeof a;
    const int n = ::recvfrom(fd_, static_cast<char*>(buf), int(size), 0,
                             reinterpret_cast<sockaddr*>(&a), &len);
    if (n < 0 && would_block()) return 0;
    if (n < 0) { error_ = error_text("recvfrom"); return -1; }
    from = from_sockaddr(a);
    return n;
}

bool UdpSocket::set_receive_buffer(int bytes) {
    return fd_ >= 0 && setsockopt(fd_, SOL_SOCKET, SO_RCVBUF, reinterpret_cast<const char*>(&bytes),
                                  sizeof bytes) == 0;
}

// ------------------------------------------------------- MulticastSocket

bool MulticastSocket::join(const Endpoint& group, const std::string& iface) {
    ip_mreq mreq;
    std::memset(&mreq, 0, sizeof mreq);
    if (inet_pton(AF_INET, group.host.c_str(), &mreq.imr_multiaddr) != 1) {
        error_ = "groupe multicast invalide : " + group.host;
        return false;
    }
    mreq.imr_interface.s_addr = htonl(INADDR_ANY);
    if (!iface.empty() && inet_pton(AF_INET, iface.c_str(), &mreq.imr_interface) != 1) {
        error_ = "interface invalide : " + iface;
        return false;
    }
    if (!open(SOCK_DGRAM)) return false;
    // Plusieurs abonnes du meme poste sur le meme port : RAVEN espionne sans
    // prendre la place des vrais consommateurs.
    int one = 1;
    setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&one), sizeof one);
#ifdef SO_REUSEPORT
    setsockopt(fd_, SOL_SOCKET, SO_REUSEPORT, reinterpret_cast<const char*>(&one), sizeof one);
#endif
    sockaddr_in a;
    std::memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(group.port);
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) return fail("bind");
    if (setsockopt(fd_, IPPROTO_IP, IP_ADD_MEMBERSHIP, reinterpret_cast<const char*>(&mreq), sizeof mreq) != 0)
        return fail("IP_ADD_MEMBERSHIP");
    set_nonblocking(fd_);
    group_ = group;
    iface_ = iface;
    joined_ = true;
    return true;
}

void MulticastSocket::leave() {
    if (joined_ && fd_ >= 0) {
        ip_mreq mreq;
        std::memset(&mreq, 0, sizeof mreq);
        inet_pton(AF_INET, group_.host.c_str(), &mreq.imr_multiaddr);
        mreq.imr_interface.s_addr = htonl(INADDR_ANY);
        if (!iface_.empty()) inet_pton(AF_INET, iface_.c_str(), &mreq.imr_interface);
        setsockopt(fd_, IPPROTO_IP, IP_DROP_MEMBERSHIP, reinterpret_cast<const char*>(&mreq), sizeof mreq);
    }
    joined_ = false;
}

bool MulticastSocket::open_sender(const Endpoint& group, const std::string& iface, int ttl,
                                  bool loopback) {
    if (!bind(Endpoint("0.0.0.0", 0))) return false;
    // int, et non octet : Windows attend un DWORD, Linux accepte les deux.
    const int t = ttl, l = loopback ? 1 : 0;
    if (setsockopt(fd_, IPPROTO_IP, IP_MULTICAST_TTL, reinterpret_cast<const char*>(&t), sizeof t) != 0)
        return fail("IP_MULTICAST_TTL");
    if (setsockopt(fd_, IPPROTO_IP, IP_MULTICAST_LOOP, reinterpret_cast<const char*>(&l), sizeof l) != 0)
        return fail("IP_MULTICAST_LOOP");
    if (!iface.empty()) {
        in_addr addr;
        if (inet_pton(AF_INET, iface.c_str(), &addr) != 1) { error_ = "interface invalide : " + iface; return false; }
        if (setsockopt(fd_, IPPROTO_IP, IP_MULTICAST_IF, reinterpret_cast<const char*>(&addr), sizeof addr) != 0)
            return fail("IP_MULTICAST_IF");
    }
    group_ = group;
    iface_ = iface;
    return true;
}

long MulticastSocket::send(const void* data, size_t size) {
    return send_to(data, size, group_);
}

} // namespace net
} // namespace raven
