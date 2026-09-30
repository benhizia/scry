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

// Methodes : ce qui fait passer un script de « reposer des variables » a
// « piloter ». Toutes definies dans la classe, donc liables sans la
// bibliotheque du tiers.
struct Moteur
{
    double regime = 0.0;
    Speed  allure = Speed::Off;

    /// Remet le moteur a l'arret.
    void   couper() { regime = 0.0; allure = Speed::Off; }
    void   pousser(double delta, int repetitions = 1)
    {
        for (int i = 0; i < repetitions; ++i)
            regime += delta;
    }
    double marge(double plafond) const { return plafond - regime; }
    void   choisir(Speed v) { allure = v; }
    Speed  choisie() const { return allure; }
    // Surcharge : seule la signature exacte les distingue.
    int    calibrer(int pas) { return pas; }
    int    calibrer(double pas) { return static_cast<int>(pas); }
    static int version() { return 7; }
    // Vue sur un membre : ecrire dedans doit ecrire dans le moteur.
    Sample& echantillon() { return vu_; }
    // Non liees, chacune pour une raison differente, dite en commentaire dans
    // le header genere.
    virtual int virtuelle() { return 1; }
    int declaree();                       // definie dans aucune unite

private:
    Sample vu_{};
    int    cachee() { return 1; }         // privee : innommable hors de la classe
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
extern Moteur g_moteur;

namespace inner {
extern std::uint32_t g_ticks;           // namespace imbrique : sut.cases.inner
}

// Fonctions libres. Definies ici, donc liables sans la bibliotheque du tiers.
inline void remettre_a_zero() { g_sample.from = 0; g_sample.speed = Speed::Off; }

/// Applique une allure et rend le regime resultant.
inline double appliquer(Moteur& m, Speed v, double delta = 2.5)
{
    m.choisir(v);
    m.pousser(delta);
    return m.regime;
}

inline Moteur&     moteur_courant() { return g_moteur; }
inline const char* etiquette() { return "cases"; }
inline int         additionner(int a, int b) { return a + b; }
inline double      additionner(double a, double b) { return a + b; }
double             compute_trim(const Sample& s);   // declaree seulement : non liee
inline int         journaliser(const char* f, ...) { (void)f; return 0; }  // variadique

namespace util {
inline int doubler(int v) { return 2 * v; }
}  // namespace util

}  // namespace cases
