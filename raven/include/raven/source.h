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

// Sens d'un message relaye. Sans objet pour une source qui observe sans
// s'interposer : un anneau SHM ou un abonne multicast ne connaissent pas de
// sens, et laissent None.
enum class Direction : uint8_t { None = 0, AtoB = 1, BtoA = 2 };
const char* direction_name(Direction d);            // "", "A>B", "B>A"

struct Frame {
    uint64_t no = 0;                 // numero de trame du producteur
    uint64_t t_ns = 0;               // horodatage du producteur
    // -1 : trame complete, de descriptor.frame_size() octets (anneau SHM).
    // >= 0 : message d'un seul canal, de la taille de ce canal (reseau).
    int channel = -1;
    Direction dir = Direction::None;
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
    // Sens que porte un canal. None par defaut : une source qui observe sans
    // s'interposer n'en connait pas. Un relais, lui, sait quel canal va de A
    // vers B, et c'est ce qui permet au visualiseur de nommer ses onglets.
    virtual Direction channel_direction(int channel) const { (void)channel; return Direction::None; }
};

// Fabrique a partir d'une specification "type:parametres". Renvoie nullptr
// si le type est inconnu. Plugins disponibles (src/engine/sources.cpp) :
//   shm:<nom>                                    anneau du simulateur
//   mcast:<groupe>:<port>[@iface][#canal][?seq=champ]
//                                                abonne multicast passif
//   tcp:<ecoute>|<vers>|<canal A>B>|<canal B>A>  relais TCP, RAVEN entre A et B
//   udp:<ecoute>|<vers>|<canal A>B>|<canal B>A>  relais UDP
std::unique_ptr<ISource> make_source(const std::string& spec, const Descriptor& d);

} // namespace raven
