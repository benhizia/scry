// Descripteur .rvndesc genere par 'scry raven' : ce que RAVEN sait des types
// du projet, et rien d'autre. Aucun type du simulateur n'est compile dans RAVEN.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace raven {

enum class Kind : uint8_t { Bool, Int, UInt, Float, Enum, Pointer, Struct, Other };

const char* kind_name(Kind k);

struct EnumItem { int64_t value; std::string name; };

struct EnumDesc {
    std::string name;
    std::vector<EnumItem> items;
    const char* name_of(int64_t v) const;          // nullptr si inconnue
};

struct FieldDesc {
    int         parent = -1;       // index dans ChannelDesc::fields, -1 = racine
    Kind        kind = Kind::Other;
    uint32_t    offset = 0;        // depuis le debut du canal
    uint32_t    size = 0;          // taille d'un element
    uint32_t    count = 1;         // > 1 pour un tableau de scalaires
    int         enum_id = -1;
    std::string unit;              // "" si aucune
    std::string path;              // "pos.alt"
    std::string name;              // "alt" (dernier segment du chemin)
    std::vector<int> children;

    bool is_leaf() const { return kind != Kind::Struct; }
    uint32_t bytes() const { return size * count; }
};

struct ChannelDesc {
    int         id = 0;
    std::string name;              // "g_flight"
    uint32_t    frame_offset = 0;  // position du canal dans la trame
    uint32_t    size = 0;
    std::vector<FieldDesc> fields;
    std::vector<int> roots;        // champs de premier niveau
};

// Designe un champ : canal et index du champ dans ce canal.
struct FieldRef {
    int channel = -1;
    int field = -1;
    bool valid() const { return channel >= 0 && field >= 0; }
    bool operator==(const FieldRef& o) const { return channel == o.channel && field == o.field; }
    bool operator<(const FieldRef& o) const {
        return channel != o.channel ? channel < o.channel : field < o.field;
    }
};

class Descriptor {
public:
    // Analyse le texte d'un .rvndesc ; en cas d'erreur, renvoie false et
    // renseigne 'error' avec la ligne fautive.
    bool parse(const std::string& text, std::string& error);
    bool load(const std::string& path, std::string& error);

    const std::string& text() const { return text_; }   // tel que charge
    uint64_t schema() const { return schema_; }
    uint32_t frame_size() const { return frame_size_; }
    const std::vector<ChannelDesc>& channels() const { return channels_; }
    const std::vector<EnumDesc>& enums() const { return enums_; }

    const ChannelDesc* channel(int id) const;
    const FieldDesc* field(FieldRef r) const;
    const EnumDesc* enum_of(const FieldDesc& f) const;

    // Position d'un champ (element 0) dans la trame complete.
    uint32_t frame_offset(FieldRef r) const;
    // "g_flight.pos.alt"
    std::string full_path(FieldRef r) const;
    // Recherche par chemin complet ; FieldRef invalide si absent.
    FieldRef find(const std::string& full_path) const;
    // Toutes les feuilles, dans l'ordre du descripteur.
    std::vector<FieldRef> leaves() const;

private:
    std::string text_;
    uint64_t schema_ = 0;
    uint32_t frame_size_ = 0;
    std::vector<ChannelDesc> channels_;
    std::vector<EnumDesc> enums_;
};

// Lecture d'un element de champ feuille depuis des octets bruts (petit-boutiste,
// comme le simulateur). 'p' pointe sur le debut du champ.
double  read_number(const FieldDesc& f, const unsigned char* p, uint32_t index = 0);
int64_t read_integer(const FieldDesc& f, const unsigned char* p, uint32_t index = 0);
// Texte affichable : "Running", "true", "12.5", "0x7ff..." ; l'enum en texte.
std::string format_value(const Descriptor& d, const FieldDesc& f,
                         const unsigned char* p, uint32_t index = 0);
std::string format_number(const Descriptor& d, const FieldDesc& f, double v);

} // namespace raven
