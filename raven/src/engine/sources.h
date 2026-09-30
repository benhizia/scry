// Registre interne des plugins de source. Chaque plugin fournit sa fabrique ;
// make_source() (source.h) choisit selon le prefixe de la specification.
#pragma once
#include <memory>
#include <string>

#include "raven/source.h"

namespace raven {

std::unique_ptr<ISource> make_shm_source(const std::string& arg, const Descriptor& d);
std::unique_ptr<ISource> make_mcast_source(const std::string& arg, const Descriptor& d);

} // namespace raven
