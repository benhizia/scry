// Details de plateforme communs aux sockets de RAVEN (net.cpp, sockets.cpp).
// Interne : n'est pas installe avec les headers publics.
#pragma once
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>

#ifdef _WIN32
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  ifndef NOMINMAX
#    define NOMINMAX
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
namespace detail {

inline bool wait_fd(intptr_t fd, int timeout_ms, bool write) {
    fd_set set;
    FD_ZERO(&set);
    FD_SET((unsigned)fd, &set);
    timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    return select(int(fd + 1), write ? nullptr : &set, write ? &set : nullptr, nullptr, &tv) > 0;
}
inline bool wait_readable(intptr_t fd, int timeout_ms) { return wait_fd(fd, timeout_ms, false); }
inline bool wait_writable(intptr_t fd, int timeout_ms) { return wait_fd(fd, timeout_ms, true); }

inline void set_nonblocking(intptr_t fd) {
#ifdef _WIN32
    u_long mode = 1;
    ioctlsocket(fd, FIONBIO, &mode);
#else
    const int flags = fcntl(int(fd), F_GETFL, 0);
    fcntl(int(fd), F_SETFL, (flags < 0 ? 0 : flags) | O_NONBLOCK);
#endif
}

inline int last_error() {
#ifdef _WIN32
    return WSAGetLastError();
#else
    return errno;
#endif
}

inline bool would_block() {
    const int e = last_error();
#ifdef _WIN32
    return e == WSAEWOULDBLOCK;
#else
    return e == EAGAIN || e == EWOULDBLOCK || e == EINTR;
#endif
}

inline bool in_progress() {
    const int e = last_error();
#ifdef _WIN32
    return e == WSAEWOULDBLOCK || e == WSAEINPROGRESS;
#else
    return e == EINPROGRESS;
#endif
}

inline void no_delay(intptr_t fd) {
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof one);
}

inline std::string error_text(const char* what) {
    return std::string(what) + " (erreur " + std::to_string(last_error()) + ")";
}

} // namespace detail
} // namespace raven
