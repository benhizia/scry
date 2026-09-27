# Ce que Scry génère pour RAVEN : qui fait quoi

> Étude, pas encore de code. Le pseudo-code C++ ci-dessous sert à fixer les
> responsabilités ; les noms, signatures et formats sont provisoires.
> Le contour fonctionnel complet est dans [RAVEN_CONTOUR.md](RAVEN_CONTOUR.md).

## 0. Recadrage

- **Scry est un outil de build.** Il est en Python pour deux raisons :
  pygccxml, qui n'a pas d'équivalent natif pour exploiter la sortie de
  castxml, et Jinja, qui rend la génération par gabarits peu coûteuse. Rien de
  Scry ne tourne à l'exécution.
- **Le visualiseur Python de Scry est une preuve de concept** : il montre
  qu'on peut afficher dans une IHM l'arbre issu d'une analyse castxml. Il
  n'est pas le visualiseur de RAVEN.
- **Les gabarits pybind11** servent la couche d'autotest : un moteur de script
  Python embarqué dans une application C++, dans l'esprit de Lua. C'est un
  sujet à part, limité à cette application.
- **RAVEN et tout ce que Scry génère pour lui sont en C++**, IHM comprise
  (imgui, affichage paresseux).

La philosophie reste la même : Scry a accès à tout (types, offsets, tailles,
enums, commentaires, variables globales), donc **tout ce qui peut se déduire
des headers est généré**. On n'écrit à la main que ce qui ne dépend pas du
projet.

---

## 1. Scry doit-il connaître les plugins de RAVEN ?

**Non.** Scry connaît le **contrat de données** de RAVEN, un header stable
écrit une fois dans RAVEN (`raven/descriptor.h`), mais pas ses plugins.

La frontière est entre le **quoi** et le **comment** :

| | Répond à | Porté par | Change quand |
|---|---|---|---|
| **Quoi** | quels canaux, quels types, quels champs, à quels offsets, quels noms, quelles unités | tables générées par Scry | un header du projet change |
| **Comment, où** | SHM, TCP, multicast, fichier, intermédiaire ; adresse, port, taille des tampons | plugins et configuration d'exécution de RAVEN | on change de banc, de liaison, de mode |

Le test qui tranche :

- *J'ajoute un plugin multicast.* Faut-il relancer Scry ? **Non.**
- *J'ajoute un champ dans une struct.* Faut-il relancer Scry ? **Oui**, et
  rien d'autre.
- *Je rejoue hier soir un enregistrement fait sur la SHM.* Faut-il
  recompiler ? **Non** : même exécutable, autre plugin choisi à l'exécution.

Si Scry connaissait les plugins, chaque nouveau transport imposerait une
évolution de Scry, et le même build ne pourrait plus enregistrer en direct
puis rejouer un fichier.

### Deux cas où un plugin a vraiment besoin du layout

Ils existent, mais se traitent toujours par des **données ou des fonctions
par type**, jamais par du code par plugin :

1. **Messages réseau dont l'en-tête est une struct du projet** (identifiant,
   longueur) : Scry génère une table `identifiant → type`. Le plugin TCP ou UDP
   la lit sans rien savoir des types eux-mêmes.
2. **Boutisme ou sérialisation champ par champ** entre machines hétérogènes :
   Scry génère un codec par type (`swap_bytes(FlightState&)`). N'importe quel
   plugin peut l'appeler.

---

## 2. Qui écrit quoi

```
                 écrit à la main, une fois          généré par Scry, par projet
               ┌──────────────────────────┐      ┌──────────────────────────────┐
  RAVEN        │ raven/descriptor.h       │◄─────│ sim_a.rvndesc                │
  (contrat)    │ raven/producer.h         │      │   tables types/champs/canaux │
               └──────────────────────────┘      │   chargé au démarrage        │
               ┌──────────────────────────┐      │ raven_codecs.gen.cpp (opt.)  │
  raven.exe    │ plugins : Shm, Tcp, Mcast│      └──────────────────────────────┘
  (générique)  │ File, Mitm ; Recorder,   │      ┌──────────────────────────────┐
               │ Sentinel, Relocator      │      │ raven_publish.gen.cpp        │
               └──────────────────────────┘      │   compilé dans le SIMULATEUR │
               ┌──────────────────────────┐      │   static_assert + collecte   │
  raven-view   │ ui::FieldTree, widgets,  │      └──────────────────────────────┘
  (générique)  │ lecteur .rvn             │
               └──────────────────────────┘
  Config       raven.toml : quel plugin, quelle adresse, quels tampons (exécution)
  Entrée Scry  headers + scry.ini [raven] + annotations dans les commentaires
```

- **Ce qu'écrit RAVEN ne connaît aucun type du projet.** Il ne manipule que
  des descripteurs et des octets.
- **Ce que génère Scry ne contient aucune logique de transport.** Ce sont des
  tables, des `static_assert` et des copies mémoire.

---

## 3. Le projet d'exemple

```cpp
// sim/etat.h : headers du simulateur (tiers ou maison)
struct Position {
    double lat;          ///< [deg]
    double lon;          ///< [deg]
    float  alt;          ///< [ft] @raven threshold=1.0
};

enum class Phase : uint8_t { Sol, Montee, Croisiere, Descente };

struct FlightState {
    uint32_t cycle;
    Position pos;
    Phase    phase;
    bool     gear_down;
    float    fuel[4];    ///< [kg]
};

struct Waypoint { double lat, lon; char name[8]; };

// Mémoire dispersée : chaque variable vit où l'éditeur de liens la met.
extern FlightState g_flight;
extern Waypoint    g_legs[64];

// Struct de pointeurs, regroupée en SHM (voir ETUDE_ACQUISITION.md § 1).
struct Bus {
    FlightState* flight;
    Waypoint*    legs;       ///< @raven count=leg_count
    uint16_t     leg_count;
};
extern Bus g_bus;
```

Ce qu'on donne à Scry en plus des headers :

```ini
; scry.ini
[raven]
; canal = racine : période attendue
channels = flight=g_flight:10ms, bus=g_bus
; annotations pour les headers tiers qu'on ne peut pas modifier
annotate = Bus::legs count=leg_count
```

Les annotations `@raven` passent par les commentaires de documentation, que
Scry relit déjà. Pour un header tiers non modifiable, la même annotation va
dans `scry.ini`.

---

## 4. Le contrat : `raven/descriptor.h` (RAVEN, à la main)

Ce header est **la seule chose que Scry doit connaître de RAVEN**. Il est
versionné ; les gabarits de Scry visent une version donnée.

```cpp
namespace raven {

constexpr uint32_t kDescriptorVersion = 1;

enum class Kind : uint8_t {
    Bool, Int, UInt, Float, Enum, Char,   // feuilles
    Struct, Array, Pointer, Padding       // composites et cas particuliers
};

struct FieldDesc {
    const char* name;        // "alt"
    const char* path;        // "pos.alt" : clé stable pour l'IHM et l'export
    Kind        kind;
    uint32_t    offset;      // depuis la racine du canal, en octets
    uint32_t    size;        // taille d'un élément
    uint32_t    count;       // 1, ou longueur du tableau
    uint8_t     bit_offset, bit_width;   // 0, 0 hors champ de bits
    int32_t     type_index;  // struct ou pointé, -1 sinon
    int32_t     enum_index;  // -1 si pas une enum
    int32_t     parent;      // index du champ parent, -1 pour la racine
    const char* unit;        // "ft", "" si aucune
    float       threshold;   // seuil de sentinelle, 0 = tout changement
    const char* doc;
};

struct PointerDesc {         // un membre pointeur à suivre (struct de pointeurs)
    uint32_t    field;       // index du FieldDesc pointeur
    int32_t     pointee_type;
    int32_t     count_field; // index du champ qui donne le nombre, -1 = 1
};

struct EnumDesc {
    const char* name;
    const std::pair<int64_t, const char*>* items;  uint32_t item_count;
};

struct TypeDesc {
    const char* name;        // "FlightState"
    uint32_t    size, align;
    uint64_t    layout_hash; // le même FNV-1a que scry verify
    const FieldDesc*   fields;   uint32_t field_count;
    const PointerDesc* pointers; uint32_t pointer_count;
};

enum class Placement : uint8_t {
    Contiguous,   // une région de SHM, offset connu
    Scattered     // collecté par le simulateur (raven_publish.gen.cpp)
};

struct ChannelDesc {
    uint16_t    id;
    const char* name;        // "flight"
    int32_t     type_index;
    Placement   placement;
    uint32_t    region_offset;  // dans la fenêtre SHM publiée
    uint32_t    size;
    uint32_t    period_us;      // attendue, pour détecter une trame manquante
};

struct Descriptor {
    uint32_t version = kDescriptorVersion;
    uint64_t schema_hash;       // empreinte de tout le descripteur
    const TypeDesc*    types;    uint32_t type_count;
    const EnumDesc*    enums;    uint32_t enum_count;
    const ChannelDesc* channels; uint32_t channel_count;

    // Pour l'enregistrer en tête de fichier, et le relire au rejeu.
    std::vector<uint8_t> serialize() const;
    static Descriptor deserialize(ByteView);   // tables possédées
};

} // namespace raven
```

---

## 5. Généré par Scry, côté RAVEN : le descripteur `.rvndesc`

Des données pures : aucun include des headers du projet. Scry les écrit dans
un fichier `sim_a.rvndesc` que `raven.exe` et `raven-view.exe` chargent au
démarrage ; aucun des deux n'est recompilé quand un header change (voir § 11).
Le contenu est montré ci-dessous sous forme de tables C++, pour la
lisibilité : c'est exactement ce que `Descriptor::deserialize` reconstruit en
mémoire.

```cpp
// Contenu de sim_a.rvndesc, vu comme des tables C++.
// GÉNÉRÉ PAR SCRY. Source : sim/etat.h, layout_hash vérifié.
#include <raven/descriptor.h>
namespace raven::gen {

static const std::pair<int64_t, const char*> kPhaseItems[] = {
    {0, "Sol"}, {1, "Montee"}, {2, "Croisiere"}, {3, "Descente"},
};
static const EnumDesc kEnums[] = { {"Phase", kPhaseItems, 4} };

static const FieldDesc kFlightStateFields[] = {
 // name        path          kind          off size cnt  b  b type enum par unit   seuil doc
  {"cycle",     "cycle",      Kind::UInt,     0,  4, 1,  0, 0, -1, -1, -1, "",    0.f, ""},
  {"pos",       "pos",        Kind::Struct,   8, 24, 1,  0, 0,  1, -1, -1, "",    0.f, ""},
  {"lat",       "pos.lat",    Kind::Float,    8,  8, 1,  0, 0, -1, -1,  1, "deg", 0.f, ""},
  {"lon",       "pos.lon",    Kind::Float,   16,  8, 1,  0, 0, -1, -1,  1, "deg", 0.f, ""},
  {"alt",       "pos.alt",    Kind::Float,   24,  4, 1,  0, 0, -1, -1,  1, "ft",  1.f, ""},
  {"phase",     "phase",      Kind::Enum,    32,  1, 1,  0, 0, -1,  0, -1, "",    0.f, ""},
  {"gear_down", "gear_down",  Kind::Bool,    33,  1, 1,  0, 0, -1, -1, -1, "",    0.f, ""},
  {"fuel",      "fuel",       Kind::Float,   36,  4, 4,  0, 0, -1, -1, -1, "kg",  0.f, ""},
};

static const FieldDesc kBusFields[] = {
  {"flight",    "flight",     Kind::Pointer,  0,  8, 1,  0, 0,  0, -1, -1, "", 0.f, ""},
  {"legs",      "legs",       Kind::Pointer,  8,  8, 1,  0, 0,  3, -1, -1, "", 0.f, ""},
  {"leg_count", "leg_count",  Kind::UInt,    16,  2, 1,  0, 0, -1, -1, -1, "", 0.f, ""},
};
static const PointerDesc kBusPointers[] = {
  {0, /*FlightState*/ 0, -1},
  {1, /*Waypoint*/    3, /*leg_count*/ 2},
};

static const TypeDesc kTypes[] = {
  {"FlightState", 56, 8, 0x9A3F0C21D4E6B781ull, kFlightStateFields, 8, nullptr, 0},
  {"Position",    24, 8, 0x1C44E0B2A97F3D10ull, /* ... */},
  {"Bus",         24, 8, 0x5E7D12AA03C4F9B6ull, kBusFields, 3, kBusPointers, 2},
  {"Waypoint",    24, 8, 0x77B0E3F15A2C8D49ull, /* ... */},
};

static const ChannelDesc kChannels[] = {
  {1, "flight", 0, Placement::Scattered, 0,  56, 10000},
  {2, "bus",    2, Placement::Scattered, 64, 24, 0},
};

extern const Descriptor kDescriptor = {
  kDescriptorVersion, 0xD1CE0F5EA11B00B5ull,
  kTypes, 4, kEnums, 1, kChannels, 2,
};

} // namespace raven::gen
```

Les unités et seuils viennent des commentaires `///< [ft] @raven threshold=1.0`
et les enums de leurs déclarations : rien n'est saisi à la main.

---

## 6. Généré par Scry, côté simulateur : `raven_publish.gen.cpp`

C'est la seule glue compilée **dans le simulateur**. Elle inclut les vrais
headers, donc c'est ici que le layout est vérifié par le vrai compilateur. Elle
s'appuie sur `raven/producer.h` : un petit header de RAVEN, sans dépendance,
qui gère la fenêtre SHM, le compteur de cycle et la signalisation de fin de
cycle.

```cpp
// GÉNÉRÉ PAR SCRY, ne pas modifier.
#include "sim/etat.h"
#include <raven/producer.h>

// 1. Le layout compilé est celui que décrit sim_a.rvndesc.
static_assert(sizeof(FlightState) == 56, "FlightState a changé : relancer scry");
static_assert(offsetof(FlightState, pos) + offsetof(Position, alt) == 24, "");
static_assert(offsetof(FlightState, gear_down) == 33, "");
static_assert(sizeof(Bus) == 24 && offsetof(Bus, leg_count) == 16, "");
// ... un static_assert par champ, comme scry verify

namespace raven::gen {

// 2. Collecte de fin de cycle : copie chaque zone dispersée dans l'emplacement
//    de sa trame, suit les pointeurs annotés et note leur base d'origine
//    (nécessaire au rejeu à froid, ETUDE_ACQUISITION.md § 2).
void publish(raven::ProducerWindow& w, uint64_t cycle)
{
    auto slot = w.begin_frame(cycle);              // fenêtre stable, seqlock

    slot.copy(/*channel*/ 1, &g_flight, sizeof(FlightState));

    const Bus& bus = g_bus;
    slot.copy(2, &bus, sizeof(Bus));
    slot.follow(2, /*field*/ 0, bus.flight, sizeof(FlightState));
    slot.follow(2, /*field*/ 1, bus.legs,
                sizeof(Waypoint) * bus.leg_count); // count=leg_count

    w.end_frame(slot);                             // signale « cycle complet »
}

} // namespace raven::gen
```

Côté simulateur, l'intégration tient en une ligne :

```cpp
// boucle 20 ms du simulateur, écrite à la main
void Simulateur::step() {
    modele_.calcule();
    raven::gen::publish(fenetre_raven_, ++cycle_);
}
```

Pour une mémoire **déjà contiguë** (une struct racine en SHM), `publish` se
réduit aux `static_assert` et à `end_frame` : il n'y a rien à copier.

---

## 7. RAVEN, à la main : l'interface de plugin

Les plugins reçoivent le descripteur pour les **tailles et identifiants de
canaux**, jamais pour les types. Ils produisent des trames brutes.

```cpp
namespace raven {

struct Frame {                 // la trame commune (ETUDE_SOURCES.md)
    uint16_t channel;
    uint64_t seq;              // détecte les pertes
    uint64_t t_source_ns, t_rx_ns;
    uint64_t layout_hash;      // refusée si différente du descripteur
    ByteView payload;          // + régions suivies (pointeurs) et leurs bases
};

class FrameSink {              // implémenté par le coeur : file sans verrou
public:
    virtual bool push(Frame&&) = 0;      // false = contre-pression
};

class ISource {
public:
    virtual ~ISource() = default;
    virtual const char* kind() const = 0;                 // "shm", "mcast"...
    virtual bool open(const Config&, const Descriptor&) = 0;
    virtual void run(FrameSink&, StopToken) = 0;          // son propre fil
    virtual SourceStats stats() const = 0;                // pertes, débit
};

class ShmSource       : public ISource { /* attend end_frame, copie la fenêtre */ };
class MulticastSource : public ISource { /* réassemble, contrôle seq */ };
class TcpSource       : public ISource { /* découpage longueur + en-tête */ };
class FileSource      : public ISource { /* rejeu : horloge d'origine, vitesse */ };
class MitmRelay       : public ISource { /* relaie d'abord, copie ensuite */ };

RAVEN_REGISTER_SOURCE("shm",   ShmSource);
RAVEN_REGISTER_SOURCE("mcast", MulticastSource);
RAVEN_REGISTER_SOURCE("file",  FileSource);

} // namespace raven
```

Le choix du plugin se fait à l'exécution :

```toml
# raven.toml : aucun type ici, uniquement le « comment »
[source]
kind = "mcast"
group = "239.1.2.3:5000"
[record]
path = "vol_2026-09-27.rvn"
buffer_mb = 512
```

---

## 8. RAVEN, à la main : le coeur générique

Tout ce qui suit est écrit **une fois** et fonctionne pour n'importe quel
projet, parce qu'il ne parcourt que des `FieldDesc`.

### Enregistreur : des fichiers qui se décrivent eux-mêmes

```cpp
class Recorder {
public:
    Recorder(const Descriptor& d, const RecordConfig& c) {
        file_.write_header(d.serialize());   // le descripteur en tête
    }
    void on_frame(const Frame& f) { file_.append(f); }   // chaque trame, sans perte
};
```

Un enregistrement contient son descripteur : il se relit dans dix ans sans le
build d'origine, et le `layout_hash` de chaque trame est vérifiable.

### Sentinelles : ne rater aucun booléen

```cpp
class SentinelEngine {
public:
    explicit SentinelEngine(const TypeDesc& t) {
        for (const FieldDesc& f : fields(t))
            switch (f.kind) {
            case Kind::Bool: case Kind::Enum: case Kind::Int: case Kind::UInt:
                exact_.push_back(&f);                   // tout changement
                break;
            case Kind::Float:
                if (f.threshold > 0) thresh_.push_back(&f);
                break;
            default: break;
            }
    }
    // Sur le fil d'analyse, à chaque trame : compare à la précédente et
    // accroche les changements, même s'ils ne vivent qu'une trame.
    void scan(ByteView prev, ByteView cur, ChangeLog& out);
};
```

### Rejeu à froid : relocation

```cpp
class Relocator {
public:
    // Réécrit chaque pointeur de la trame : ancienne base -> nouvelle base,
    // grâce aux PointerDesc et aux bases notées par publish().
    void rebase(const TypeDesc& t, MutableBytes frame,
                const BaseMap& recorded, const BaseMap& live);
};
```

### IHM imgui paresseuse : l'arbre se construit seul (dans `raven-view.exe`)

imgui est en mode immédiat : il ne garde aucun arbre de widgets et l'IHM est
redessinée à chaque image par des appels de fonction, avec des chaînes et des
valeurs connues à l'exécution. Une boucle sur le descripteur chargé suffit :
rien n'est à déclarer à la compilation.

```cpp
namespace raven::ui {

class FieldTree {
public:
    FieldTree(const Descriptor& d, const Snapshot& s) : d_(d), s_(s) {}

    void draw(const ChannelDesc& c) {
        draw_children(d_.types[c.type_index], /*parent*/ -1, s_.latest(c.id));
    }

private:
    void draw_children(const TypeDesc& t, int parent, ByteView frame) {
        for (int i = 0; i < int(t.field_count); ++i) {
            const FieldDesc& f = t.fields[i];
            if (f.parent != parent) continue;
            if (f.kind == Kind::Struct || f.count > 1) {
                if (ImGui::TreeNode(f.path, "%s", f.name)) {   // replié = rien décodé
                    draw_children(t, i, frame);
                    ImGui::TreePop();
                }
            } else {
                draw_leaf(f, frame);        // décode uniquement ce qui est visible
            }
        }
    }

    void draw_leaf(const FieldDesc& f, ByteView frame) {
        Value v = decode(f, frame);         // offset, taille, kind, bits
        if (f.enum_index >= 0) v = enum_name(d_.enums[f.enum_index], v);
        ImGui::Text("%s = %s %s", f.name, to_string(v).c_str(), f.unit);
        if (sentinels_.changed_recently(f)) highlight();   // un bool d'une trame reste visible
    }

    const Descriptor& d_;
    const Snapshot&   s_;               // dernière trame par canal, au mieux
    const SentinelIndex& sentinels_;
};

} // namespace raven::ui
```

L'IHM n'a besoin **d'aucune ligne propre au projet** : noms, chemins, unités,
enums, tableaux, adresses et seuils viennent du descripteur.

---

## 9. Deux exécutables : `raven.exe` et `raven-view.exe`

```
                     sim_a.rvndesc (Scry)
                      │             │
                      ▼             ▼
 simulateur ──SHM──► raven.exe ──────────────► raven-view.exe
 réseau ───────────►  acquérir      instantanés    arbre imgui paresseux
 fichier .rvn ─────►  vérifier      + journal      courbes, navigation
                      enregistrer   sentinelles    ▲
                      sentinelles   (SHM locale)   │
                      │                            │
                      └──────► vol.rvn ────────────┘  hors ligne
                               (descripteur en tête)
```

| | `raven.exe` | `raven-view.exe` |
|---|---|---|
| Rôle | enregistreur, sans IHM | visualiseur paresseux |
| Voit | **toutes** les trames | la dernière trame de chaque canal, au mieux |
| Sentinelles | les calcule (lui seul voit tout) | affiche leur journal |
| Charge | `.rvndesc` | `.rvndesc` en direct ; rien de plus pour un `.rvn` |
| Priorité | haute | normale, éventuellement sur un autre poste |
| S'il plante | l'enregistrement s'arrête : il doit être robuste | rien n'est perdu |

Le protocole local entre les deux, à spécifier :

```cpp
namespace raven::live {

struct LiveHeader {            // en tête de la SHM de publication
    uint32_t version;
    uint64_t schema_hash;      // le visualiseur refuse un .rvndesc différent
    uint64_t writer_heartbeat; // raven.exe vivant ?
    uint32_t channel_count;
    uint32_t journal_capacity;
};

struct LiveSlot {              // un par canal : dernière trame, seqlock
    std::atomic<uint64_t> seq;
    uint64_t t_source_ns;
    uint32_t size;
    uint8_t  payload[];        // taille donnée par ChannelDesc
};

struct SentinelEvent {         // anneau : le visualiseur rattrape s'il le peut
    uint64_t seq, t_ns;
    uint16_t channel;
    uint32_t field;            // index du FieldDesc
    uint64_t old_bits, new_bits;
};

class Publisher {              // dans raven.exe, fil de publication
public:
    void publish(const Frame&);           // écrase le slot du canal
    void event(const SentinelEvent&);     // n'attend jamais : anneau
};

class Subscriber {             // dans raven-view.exe
public:
    ByteView latest(uint16_t channel);    // copie cohérente, sinon réessaie
    size_t   drain_events(std::vector<SentinelEvent>& out); // signale les trous
};

} // namespace raven::live
```

---

## 10. Récapitulatif

| Artefact | Écrit par | Compilé dans | Connaît les types du projet ? | Change quand |
|---|---|---|---|---|
| `raven/descriptor.h`, `raven/producer.h` | RAVEN, à la main | RAVEN ; simulateur (`producer.h`) | non | le contrat évolue (versionné) |
| `sim_a.rvndesc` | **Scry** | aucun : chargé par `raven.exe` et `raven-view.exe` | sous forme de données | un header change |
| `raven_publish.gen.cpp` | **Scry** | simulateur | oui (inclut les headers) | un header ou la liste des canaux change |
| `raven_codecs.gen.cpp` (optionnel) | **Scry** | RAVEN, plugins réseau | oui, par type | un header change |
| Plugins `ISource` | RAVEN, à la main | `raven.exe` | non | on ajoute un transport |
| Recorder, Sentinel, Relocator, Publisher | RAVEN, à la main | `raven.exe` | non | jamais pour un nouveau projet |
| FieldTree, widgets, lecteur `.rvn`, Subscriber | RAVEN, à la main | `raven-view.exe` | non | jamais pour un nouveau projet |
| `raven.toml` | l'utilisateur | lu à l'exécution | non | on change de banc ou de mode |
| `scry.ini [raven]`, annotations `@raven` | l'utilisateur | lu par Scry | décrit les canaux | on ajoute un canal ou une unité |

**Ce que Scry doit apprendre** pour tenir ce rôle :

1. Lire la section `[raven]` et les annotations `@raven` (commentaires et
   `scry.ini`) : canaux, période, compteurs de pointeurs, unités, seuils.
2. Un jeu de gabarits `templates/raven/` qui vise une version de
   `raven/descriptor.h`.
3. Vérifier `raven_publish.gen.cpp` comme le reste (`scry verify` avec cl,
   g++ et clang++).
4. Refuser un pointeur sans compteur annoté plutôt que deviner.

C'est la piste D5 de [AMELIORATIONS.md](AMELIORATIONS.md), précisée.

---

## 11. À trancher

1. ~~Descripteur compilé ou chargé ?~~ **Tranché : chargé.** Scry génère
   `sim_a.rvndesc`, lu au démarrage par `raven.exe` et `raven-view.exe`. Le
   même exécutable sert tous les projets ; un header modifié impose seulement
   de relancer Scry. Le code de chargement existe de toute façon pour relire
   le descripteur en tête d'un `.rvn`, et le `layout_hash` de chaque trame
   couvre le risque d'un descripteur qui ne correspond pas.
2. **Où vit `raven/producer.h`** : dans RAVEN, vendu au simulateur, ou copié
   par Scry à côté de la glue ? Dans les deux cas, il doit rester un header
   seul, sans dépendance.
3. **Granularité des canaux** : une variable racine par canal, ou des
   sous-arbres (`g_flight.pos`) pour réduire le débit ?
4. **Annotations** : quel vocabulaire minimal (`count`, `unit`, `threshold`,
   `ignore`, `period`) et quelle priorité entre le commentaire et `scry.ini` ?
5. **Protocole local `raven::live`** : SHM seule, ou aussi le réseau pour un
   visualiseur distant ? Taille de l'anneau des sentinelles ?
6. **Codecs réseau** : nécessaires seulement s'il existe une machine de
   boutisme différent ou un protocole non « struct brute ». À confirmer avant
   de les générer.
