// Scenario 06 de SwitchSpy : structs complexes. Imbrication, tableaux de
// structures, tableaux de scalaires, enum, chaine.
//
// Les drapeaux sont des ENTIERS MASQUES et non des champs de bits C++ : c'est
// ainsi que SwitchSpy les declarait, et c'est de toute facon ce que fait un
// protocole reel, ou la place de chaque bit est fixee par la specification et
// non par le compilateur. Le descripteur voit donc un uint32 ordinaire.
//
// Aucun static_assert de taille, comme pour les autres scenarios repris :
// c'est Scry qui verifie le layout.
#pragma once

#include <cstdint>

/// Flight phase of a leg
enum class LegPhase : uint8_t {
    Parked = 0,
    Taxi = 1,
    Climb = 2,
    Cruise = 7,          // valeurs non contigues : un decodage par index serait faux
    Descent = 11,
    Hold = 20
};

/// Header shared by every message of the link
struct MsgHeader {
    /// Message sequence number, strictly increasing
    uint64_t sequence;

    /// Emission time, nanoseconds since boot
    uint64_t emitted_ns;

    /// Identifier of the emitting unit
    uint16_t source_id;

    /// Protocol version
    uint8_t version;

    /// Padding to keep the layout explicit
    uint8_t reserved;
};

/// One leg of the commanded route
struct RouteLeg {
    /// Leg phase
    LegPhase phase;

    /// Padding to keep the layout explicit
    uint8_t reserved[3];

    /// Target altitude in feet
    int32_t altitude_ft;

    /// Target speed in knots, hundredths
    uint32_t speed_kt_e2;

    /// Leg duration in milliseconds
    uint32_t duration_ms;
};

/// Route command sent from the controller (A) to the flight unit (B)
struct ComplexCommand {
    /// Common header
    MsgHeader header;

    /// Callsign, NUL terminated
    char callsign[8];

    /// Commanded route, fixed size
    RouteLeg legs[4];

    /// Trim gains applied to each axis
    double gains[3];

    /// Fuel on board in kilograms
    float fuel_kg;

    /// Option flags, masked integer and not a C++ bitfield.
    /// bit 0: autopilot, bit 1: hold, bit 2: emergency, bits 8-15: squawk high
    uint32_t flags;
};

/// Acknowledgement sent from the flight unit (B) back to the controller (A)
struct ComplexReply {
    /// Common header, sequence echoes the acknowledged command
    MsgHeader header;

    /// Index of the leg currently flown
    uint8_t active_leg;

    /// Phase actually reached
    LegPhase phase;

    /// Padding to keep the layout explicit
    uint8_t reserved[2];

    /// Altitude reached in feet
    int32_t altitude_ft;

    /// Same mask as the command, as accepted
    uint32_t flags;
};
