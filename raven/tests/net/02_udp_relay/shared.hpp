// Scenario 02 de SwitchSpy : relais UDP, integrite verifiee par CRC32 sur
// chaque message. Sans connexion, rien ne garantit ni l'ordre ni l'arrivee :
// le numero de sequence dit ce qui manque, le CRC dit ce qui est abime.
// Aucun static_assert de taille, pour la meme raison que les autres
// scenarios : c'est Scry qui verifie le layout.
#pragma once

#include <cstdint>

/// Sensor reading broadcast from the field unit (A) towards the collector (B)
struct SensorReading {
    /// Reading sequence number, strictly increasing
    uint64_t sequence;

    /// Acquisition time, nanoseconds since boot
    uint64_t sampled_ns;

    /// Sensor identifier
    uint32_t sensor_id;

    /// Measured value, thousandths of the sensor unit
    int32_t value_e3;

    /// Sensor unit (0: none, 1: celsius, 2: bar, 3: rpm)
    uint8_t unit;

    /// Quality, 0 to 100
    uint8_t quality;

    /// Status flags (bit 0: valid, bit 1: saturated, bit 2: calibrating)
    uint8_t flags;

    /// Padding to keep the layout explicit
    uint8_t reserved;

    /// CRC32 of every byte of this struct before this field
    uint32_t crc32;
};

/// Setpoint sent back from the collector (B) to the field unit (A)
struct SensorSetpoint {
    /// Sequence number of the reading this answers
    uint64_t sequence;

    /// Sensor the setpoint applies to
    uint32_t sensor_id;

    /// Requested sampling period in microseconds
    uint32_t period_us;

    /// CRC32 of every byte of this struct before this field
    uint32_t crc32;

    /// Padding to keep the layout explicit
    uint32_t reserved;
};
