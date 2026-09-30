// Repris de SwitchSpy (InterfaceInspector). Le static_assert d'origine
// annoncait une taille fausse sur x86-64 (44 et 72 au lieu de 48 et 64) : il
// est retire, la taille est verifiee par Scry.
#pragma once

#include <cstdint>

/// Broadcast telemetry data for distributed monitoring
struct TelemetryBroadcast {
    /// Source identifier (unique per sensor node)
    uint32_t source_id;

    /// Broadcast sequence number
    uint64_t sequence;

    /// Unix timestamp in milliseconds
    uint64_t timestamp_ms;

    /// GPS latitude in millionths of degrees
    int32_t latitude_e6;

    /// GPS longitude in millionths of degrees
    int32_t longitude_e6;

    /// Altitude in meters
    int16_t altitude_m;

    /// Speed in cm/s
    uint16_t speed_cms;

    /// Heading in degrees (0-359)
    uint16_t heading_deg;

    /// Battery voltage in millivolts
    uint16_t battery_mv;

    /// Signal strength in dBm
    int8_t signal_dbm;

    /// Number of satellites
    uint8_t satellite_count;

    /// Status flags (bit 0: GPS fix, bit 1: Low battery, bit 2: Emergency)
    uint8_t status_flags;

    /// Padding for alignment
    uint8_t padding;
};

