// Interface de plugin de source : d'ou viennent les trames. Un plugin ne
// connait aucun type du projet : il livre des trames completes de
// descriptor.frame_size() octets.
#pragma once
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include "raven/descriptor.h"

namespace raven {

struct Frame {
    uint64_t no = 0;                 // numero de trame du producteur
    uint64_t t_ns = 0;               // horodatage du producteur
    const unsigned char* data = nullptr;
    uint32_t size = 0;
};

using FrameHandler = std::function<void(const Frame&)>;

class ISource {
public:
    virtual ~ISource() = default;
    virtual std::string describe() const = 0;           // "shm:demo"
    // Livre toutes les trames disponibles, dans l'ordre. Renvoie leur nombre.
    // Ne bloque pas : l'appelant decide du rythme de scrutation.
    virtual size_t poll(const FrameHandler& on_frame) = 0;
    virtual bool connected() const = 0;
    virtual uint64_t lost() const = 0;                  // trames manquees
    virtual const std::string& error() const = 0;       // "" si tout va bien
};

// Fabrique a partir d'une specification "type:parametres", "shm:demo" par
// exemple. Renvoie nullptr si le type est inconnu. C'est ici qu'un nouveau
// plugin (tcp, multicast, fichier) s'enregistre.
std::unique_ptr<ISource> make_source(const std::string& spec, const Descriptor& d);

} // namespace raven
