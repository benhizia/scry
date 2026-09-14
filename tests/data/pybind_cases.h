#pragma once
//
// pybind_cases.h : cas couverts par les bindings pybind11 generes et absents
// des headers d'essai de Data/. Utilise par tests/test_pybind_build.py.
//

#include <array>
#include <cstdint>

namespace cases {

// Valeurs non contigues : un decodage par index serait faux.
enum class Speed : std::uint8_t
{
    Off  = 0,
    Slow = 3,
    Fast = 10,
    Max  = 255
};

struct Sample
{
    double               values[4];   // tableau numerique 1D : vue numpy
    std::int16_t         grid[2][3];  // tableau 2D : vue numpy (2, 3)
    std::array<float, 3> vec;         // std::array numerique
    Speed                speed;       // enum a valeurs non contigues
    std::uint32_t        mode  : 3;   // champs de bits dans une meme unite
    std::uint32_t        armed : 1;
    std::uint32_t        level : 12;
    char                 tag[8];      // chaine : 7 caracteres au plus
    int                  from;        // mot-cle Python : from_

    union                             // union anonyme : membres promus
    {
        std::uint32_t raw;
        float         as_float;
    };

    struct                            // struct anonyme, membre nomme
    {
        std::uint16_t lo;
        std::uint16_t hi;
    } pair;
};

}  // namespace cases
