#pragma once
//
// test_structs.h — jeu d'essai pour un parseur / générateur de code C++.
//
// Contenu :
//   1. Vec3           POD trivial, aucun piège
//   2. SensorSample   scalaires typés, enum externe, tableau C, champs de bits
//   3. Waypoint       composition non imbriquée, conteneurs std, auto-référence
//   4. FlightPlan     imbrication profonde : enum + struct + struct dans struct,
//                     union nommée, struct anonyme, pointeur de fonction,
//                     membre statique constexpr
//   5. TelemetryFrame héritage + virtuel, template imbriqué, std::variant,
//                     alias de type, membre mutable
//
// Standard : C++17.
//

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace testgen {

// ---------------------------------------------------------------------------
// 1. POD trivial
// ---------------------------------------------------------------------------
struct Vec3
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

using Position = Vec3;   // alias de type sur une struct

// ---------------------------------------------------------------------------
// 2. Scalaires, enum non imbriquée, tableau C, champs de bits
// ---------------------------------------------------------------------------
enum class Unit : std::uint8_t
{
    Meters,
    Feet,
    NauticalMiles
};

struct SensorSample
{
    std::uint64_t timestamp_ns = 0;
    double        value        = 0.0;
    Unit          unit         = Unit::Meters;
    char          label[32]    = {};

    bool          valid      : 1;
    bool          calibrated : 1;
    std::uint8_t  quality    : 6;
};

// ---------------------------------------------------------------------------
// 3. Composition non imbriquée : réutilise les types déclarés plus haut
// ---------------------------------------------------------------------------
struct Waypoint
{
    std::string           name;
    Position              position;
    std::vector<Vec3>     approach_path;
    std::optional<double> altitude_ft;
    const Waypoint*       next = nullptr;   // auto-référence par pointeur
};

// ---------------------------------------------------------------------------
// 4. Imbrication profonde
// ---------------------------------------------------------------------------
struct FlightPlan
{
    enum class Phase : int
    {
        Preflight,
        Taxi,
        Climb,
        Cruise,
        Descent,
        Landed
    };

    struct Leg
    {
        struct alignas(16) Constraint     // imbrication de niveau 2
        {
            double min_altitude_ft = 0.0;
            double max_altitude_ft = 0.0;
            bool   mandatory       = false;
        };

        Waypoint   from;
        Waypoint   to;
        Constraint constraint;
        Phase      phase = Phase::Cruise;
    };

    union Payload                          // union nommée imbriquée
    {
        std::uint32_t raw;
        struct
        {
            std::uint16_t lo;
            std::uint16_t hi;
        } halves;
    };

    static constexpr std::size_t kMaxLegs = 16;

    std::string                            callsign;
    std::array<Leg, kMaxLegs>              legs;
    std::size_t                            leg_count = 0;
    std::map<std::string, Leg::Constraint> named_constraints;
    Payload                                payload{};

    void (*on_phase_change)(Phase) = nullptr;   // pointeur de fonction membre

    struct                                       // struct anonyme
    {
        double lat;
        double lon;
    } origin;
};

// ---------------------------------------------------------------------------
// Support pour 5. : namespace imbriqué + template
// ---------------------------------------------------------------------------
namespace detail {

template <typename T, std::size_t N>
struct RingBuffer
{
    using value_type = T;
    static constexpr std::size_t capacity = N;

    std::array<T, N> data{};
    std::size_t      head = 0;
    bool             full = false;

    void push(const T& v)
    {
        data[head] = v;
        head       = (head + 1) % N;
        if (head == 0)
            full = true;
    }

    const T& at(std::size_t i) const { return data[(head + i) % N]; }
};

}  // namespace detail

struct ISerializable
{
    virtual ~ISerializable() = default;
    virtual std::size_t byte_size() const = 0;
    virtual void        reset() {}
};

// ---------------------------------------------------------------------------
// 5. Héritage, virtuel, variant, template instancié
// ---------------------------------------------------------------------------
struct TelemetryFrame final : public ISerializable
{
    using Value   = std::variant<int, double, std::string, Vec3>;
    using History = detail::RingBuffer<SensorSample, 8>;

    struct Channel
    {
        std::string id;
        Value       last;
        History     history;
    };

    std::vector<Channel>  channels;
    FlightPlan::Phase     phase        = FlightPlan::Phase::Preflight;
    mutable std::uint32_t access_count = 0;

    std::size_t byte_size() const override
    {
        ++access_count;
        return channels.size() * sizeof(Channel);
    }

    void reset() override
    {
        channels.clear();
        phase = FlightPlan::Phase::Preflight;
    }
};

// Instanciation explicite : rend le template visible pour un parseur qui ne
// voit que les types réellement instanciés (castxml / pygccxml).
template struct detail::RingBuffer<SensorSample, 8>;

}  // namespace testgen