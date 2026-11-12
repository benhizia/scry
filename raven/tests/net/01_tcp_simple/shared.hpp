// Scenario 01 de SwitchSpy : relais TCP simple, integrite des structs.
// Deux types, un par sens : A envoie des commandes, B repond des acquittements.
// Comme pour les scenarios 03 et 04, aucun static_assert de taille : ceux
// d'origine annoncaient des tailles fausses sur x86-64, et c'est Scry qui
// verifie le layout.
#pragma once

#include <cstdint>

/// Command sent from the controller (A) to the switch (B)
struct SwitchCommand {
    /// Command sequence number, strictly increasing
    uint64_t sequence;

    /// Issue time, nanoseconds since boot
    uint64_t issued_ns;

    /// Target port on the switch
    uint16_t port_id;

    /// Requested action (0: query, 1: enable, 2: disable, 3: reset)
    uint8_t action;

    /// Priority, 0 is highest
    uint8_t priority;

    /// Requested rate limit in kbit/s, 0 for unlimited
    uint32_t rate_limit_kbps;

    /// Opaque payload, meaning depends on the action
    uint8_t payload[16];
};

/// Acknowledgement sent from the switch (B) back to the controller (A)
struct SwitchAck {
    /// Sequence number of the command being acknowledged
    uint64_t sequence;

    /// Completion time, nanoseconds since boot
    uint64_t completed_ns;

    /// Result code (0: ok, 1: rejected, 2: busy, 3: unknown port)
    uint8_t result;

    /// Port state after the command (bit 0: up, bit 1: limited)
    uint8_t port_state;

    /// Padding to keep the layout explicit
    uint8_t reserved[2];

    /// Measured throughput in kbit/s at the time of completion
    uint32_t throughput_kbps;
};
