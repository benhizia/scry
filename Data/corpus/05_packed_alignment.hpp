#pragma once
#include <cstdint>

/// Structure with explicit alignment
struct alignas(16) AlignedStruct {
    // 64-bit integer
    int64_t large_value;
    
    // 32-bit float
    float precision_value;
    
    // 16-bit short
    int16_t small_value;
    
    // 8-bit char
    char flag;
};

/// Packed structure to minimize size
struct __attribute__((packed)) PackedStruct {
    // Mixed data types without padding
    uint8_t type_id;
    uint32_t data_value;
    uint16_t checksum;
    uint8_t flags;
    uint64_t timestamp;
};

/// Structure with explicit member alignment
struct MixedAlignment {
    // Normal alignment
    int normal_int;
    
    // Explicitly aligned member
    alignas(32) double aligned_double;
    
    // Array with specific alignment
    alignas(8) char buffer[16];
    
    // Bitfield members
    uint32_t flag1 : 1;
    uint32_t flag2 : 1;
    uint32_t reserved : 6;
    uint32_t value : 24;
};

/// Union for memory layout testing
union DataUnion {
    // Different interpretations of same memory
    uint64_t as_int;
    double as_double;
    struct {
        uint32_t low;
        uint32_t high;
    } as_parts;
    uint8_t as_bytes[8];
};