#pragma once
//
// pybind_cases.h : cas couverts par les bindings pybind11 generes et absents
// des headers d'essai de Data/, plus des variables globales de chaque nature.
// Utilise par tests/test_pybind_embed.py, qui les definit dans un hote C++
// (tests/cpp/pybind_host.cpp) et les modifie depuis Python embarque.
//

#include <array>
#include <cstdint>

#include "test_structs_complexe.h"

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

/// Une base documentee.
struct Base
{
    int base_value;   // valeur portee par la base
    double weight;
};

// Heritage : les membres de la base s'atteignent depuis la derivee.
struct Child : Base
{
    int extra;
};

// Membre prive : jamais nomme par les bindings, meme avec include_non_public.
class Hidden
{
    int secret_ = 5;

public:
    int shown = 1;
};

// Variables globales : exposees par reference dans le module embarque.
extern Sample g_sample;                 // structure : vue
extern Sample* g_current;               // pointeur : vue sur l'objet pointe, ou None
extern Speed g_speed;                   // enum
extern double g_gains[3];               // tableau numerique : vue numpy
extern char g_callsign[8];              // chaine
extern const int g_version;             // constante : lecture seule
extern testgen::FlightPlan g_plan;      // structure avec STL, tableaux de structs
extern testgen::SensorSample g_sensors[4];  // tableau de structures
static int s_internal = 0;              // static : jamais expose
extern Child g_child;                   // enfant documente
extern Hidden g_hidden;

namespace inner {
extern std::uint32_t g_ticks;           // namespace imbrique : sut.cases.inner
}

}  // namespace cases
