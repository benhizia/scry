#include "sources.h"

namespace raven {

std::unique_ptr<ISource> make_source(const std::string& spec, const Descriptor& d) {
    const size_t colon = spec.find(':');
    const std::string type = spec.substr(0, colon);
    const std::string arg = colon == std::string::npos ? "" : spec.substr(colon + 1);
    if (type == "shm") return make_shm_source(arg, d);
    if (type == "mcast") return make_mcast_source(arg, d);
    if (type == "tcp") return make_tcp_relay(arg, d);
    if (type == "udp") return make_udp_relay(arg, d);
    return nullptr;
}

} // namespace raven
