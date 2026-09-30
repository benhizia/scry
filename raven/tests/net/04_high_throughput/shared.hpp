// Repris de SwitchSpy (InterfaceInspector). Le static_assert d'origine
// annoncait une taille fausse sur x86-64 (44 et 72 au lieu de 48 et 64) : il
// est retire, la taille est verifiee par Scry.
#pragma once

#include <cstdint>

/// High-frequency market data tick
struct MarketTick {
    /// Symbol identifier (e.g., stock ticker hash)
    uint64_t symbol_id;

    /// Tick sequence number
    uint64_t sequence;

    /// Exchange timestamp in nanoseconds
    uint64_t timestamp_ns;

    /// Bid price in hundredths of cents (e.g., 1234567 = $123.4567)
    uint64_t bid_price_e4;

    /// Ask price in hundredths of cents
    uint64_t ask_price_e4;

    /// Bid size (shares)
    uint32_t bid_size;

    /// Ask size (shares)
    uint32_t ask_size;

    /// Last trade price
    uint64_t last_price_e4;

    /// Last trade size
    uint32_t last_size;

    /// Trade flags (bit 0: is_trade, bit 1: is_quote, bit 2: is_halted)
    uint8_t flags;

    /// Market phase (1=Pre-market, 2=Open, 3=Close, 4=After-hours)
    uint8_t market_phase;

    /// Padding for alignment
    uint16_t padding;
};

