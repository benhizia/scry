// Registre interne des plugins de source. Chaque plugin fournit sa fabrique ;
// make_source() (source.h) choisit selon le prefixe de la specification.
#pragma once
#include <memory>
#include <string>

#include "raven/ini.h"
#include "raven/source.h"

namespace raven {

std::unique_ptr<ISource> make_shm_source(const std::string& arg, const Descriptor& d);
std::unique_ptr<ISource> make_mcast_source(const std::string& arg, const Descriptor& d);
std::unique_ptr<ISource> make_tcp_relay(const std::string& arg, const Descriptor& d);
std::unique_ptr<ISource> make_udp_relay(const std::string& arg, const Descriptor& d);

// Traduit une section [link.x] en specification de source ("tcp:...|...").
bool link_spec(const Ini& ini, const std::string& section, std::string& spec,
               std::string& error);

} // namespace raven
