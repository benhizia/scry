#include "raven/net.h"

#include <cerrno>
#include <cstring>

#ifdef _WIN32
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  include <winsock2.h>
#  include <ws2tcpip.h>
typedef int socklen_t;
#  define RV_CLOSE closesocket
#  define RV_NOSIGNAL 0
#else
#  include <arpa/inet.h>
#  include <fcntl.h>
#  include <netdb.h>
#  include <netinet/in.h>
#  include <netinet/tcp.h>
#  include <sys/select.h>
#  include <sys/socket.h>
#  include <unistd.h>
#  define RV_CLOSE ::close
#  define RV_NOSIGNAL MSG_NOSIGNAL
#endif

namespace raven {

bool net_init() {
#ifdef _WIN32
    WSADATA w;
    return WSAStartup(MAKEWORD(2, 2), &w) == 0;
#else
    return true;
#endif
}

static bool wait_writable(intptr_t fd, int timeout_ms) {
    fd_set set;
    FD_ZERO(&set);
    FD_SET((unsigned)fd, &set);
    timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    return select(int(fd + 1), nullptr, &set, nullptr, &tv) > 0;
}

static bool wait_readable(intptr_t fd, int timeout_ms) {
    fd_set set;
    FD_ZERO(&set);
    FD_SET((unsigned)fd, &set);
    timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    return select(int(fd + 1), &set, nullptr, nullptr, &tv) > 0;
}

// Sans cela, un visualiseur qui ne lit plus remplirait le tampon TCP et
// figerait raven dans ::send, commandes comprises : plus moyen d'arreter un
// enregistrement.
static void set_nonblocking(intptr_t fd) {
#ifdef _WIN32
    u_long mode = 1;
    ioctlsocket(fd, FIONBIO, &mode);
#else
    const int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, (flags < 0 ? 0 : flags) | O_NONBLOCK);
#endif
}

static bool would_block() {
#ifdef _WIN32
    return WSAGetLastError() == WSAEWOULDBLOCK;
#else
    return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR;
#endif
}

static void no_delay(intptr_t fd) {
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof one);
}

LineSocket& LineSocket::operator=(LineSocket&& o) noexcept {
    if (this != &o) {
        close();
        fd_ = o.fd_;
        in_ = std::move(o.in_);
        out_ = std::move(o.out_);
        sent_ = o.sent_;
        dropped_ = o.dropped_;
        o.fd_ = -1;
    }
    return *this;
}

void LineSocket::close() {
    if (fd_ >= 0) RV_CLOSE(fd_);
    fd_ = -1;
    in_.clear();
    out_.clear();
    sent_ = 0;
}

bool LineSocket::connect(const std::string& host, int port) {
    close();
    addrinfo hints, *res = nullptr;
    std::memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &res) != 0) return false;
    intptr_t fd = intptr_t(socket(res->ai_family, res->ai_socktype, res->ai_protocol));
    if (fd >= 0 && ::connect(fd, res->ai_addr, socklen_t(res->ai_addrlen)) == 0) {
        fd_ = fd;
        no_delay(fd_);
    } else if (fd >= 0) {
        RV_CLOSE(fd);
    }
    freeaddrinfo(res);
    return valid();
}

// Envoi bloquant, pour le cote visualiseur : ses commandes sont minuscules.
bool LineSocket::send(const std::string& text) {
    size_t done = 0;
    while (valid() && done < text.size()) {
        const int n = ::send(fd_, text.data() + done, int(text.size() - done), RV_NOSIGNAL);
        if (n < 0 && would_block()) {
            if (!wait_writable(fd_, 1000)) continue;
            continue;
        }
        if (n <= 0) { close(); return false; }
        done += size_t(n);
    }
    return valid();
}

bool LineSocket::queue(const std::string& text, bool droppable) {
    if (!valid()) return false;
    if (droppable && pending() + text.size() > kMaxOutbox) {
        ++dropped_;            // le visualiseur ne suit pas : on saute ce lot
        return flush();
    }
    if (sent_ > 0 && sent_ == out_.size()) { out_.clear(); sent_ = 0; }
    out_ += text;
    return flush();
}

bool LineSocket::flush() {
    while (valid() && sent_ < out_.size()) {
        const int n = ::send(fd_, out_.data() + sent_, int(out_.size() - sent_), RV_NOSIGNAL);
        if (n < 0 && would_block()) return true;      // on reprendra au tour suivant
        if (n <= 0) { close(); return false; }
        sent_ += size_t(n);
    }
    if (sent_ > 0) { out_.clear(); sent_ = 0; }
    return valid();
}

bool LineSocket::receive(std::vector<std::string>& lines, int timeout_ms) {
    if (!valid()) return false;
    while (wait_readable(fd_, timeout_ms)) {
        char buf[65536];
        const int n = ::recv(fd_, buf, sizeof buf, 0);
        // La socket est non bloquante : select peut annoncer lisible sans que
        // rien n'arrive. Ce n'est pas une coupure.
        if (n < 0 && would_block()) break;
        if (n <= 0) { close(); return false; }
        in_.append(buf, size_t(n));
        timeout_ms = 0;                       // vider ce qui est deja arrive
    }
    size_t start = 0, nl;
    while ((nl = in_.find('\n', start)) != std::string::npos) {
        lines.push_back(in_.substr(start, nl - start));
        start = nl + 1;
    }
    in_.erase(0, start);
    return true;
}

bool Listener::listen(int port, bool loopback_only) {
    close();
    intptr_t fd = intptr_t(socket(AF_INET, SOCK_STREAM, 0));
    if (fd < 0) return false;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&one), sizeof one);
    sockaddr_in a;
    std::memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(uint16_t(port));
    a.sin_addr.s_addr = htonl(loopback_only ? INADDR_LOOPBACK : INADDR_ANY);
    if (bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0 || ::listen(fd, 4) != 0) {
        RV_CLOSE(fd);
        return false;
    }
    fd_ = fd;
    return true;
}

LineSocket Listener::accept(int timeout_ms) {
    if (fd_ < 0 || !wait_readable(fd_, timeout_ms)) return LineSocket();
    intptr_t c = intptr_t(::accept(fd_, nullptr, nullptr));
    if (c >= 0) {
        no_delay(c);
        set_nonblocking(c);    // raven publie sans jamais attendre le visualiseur
    }
    return LineSocket(c);
}

int Listener::port() const {
    if (fd_ < 0) return -1;
    sockaddr_in a;
    socklen_t len = sizeof a;
    if (getsockname(fd_, reinterpret_cast<sockaddr*>(&a), &len) != 0) return -1;
    return int(ntohs(a.sin_port));
}

void Listener::close() {
    if (fd_ >= 0) RV_CLOSE(fd_);
    fd_ = -1;
}

} // namespace raven
