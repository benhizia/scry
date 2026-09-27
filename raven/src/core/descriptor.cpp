#include "raven/descriptor.h"

#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

namespace raven {

const char* kind_name(Kind k) {
    switch (k) {
    case Kind::Bool: return "bool";
    case Kind::Int: return "int";
    case Kind::UInt: return "uint";
    case Kind::Float: return "float";
    case Kind::Enum: return "enum";
    case Kind::Pointer: return "pointer";
    case Kind::Struct: return "struct";
    default: return "other";
    }
}

static bool parse_kind(const std::string& s, Kind& k) {
    static const char* names[] = {"bool", "int", "uint", "float", "enum", "pointer", "struct", "other"};
    for (int i = 0; i < 8; ++i)
        if (s == names[i]) { k = Kind(i); return true; }
    return false;
}

const char* EnumDesc::name_of(int64_t v) const {
    for (const auto& it : items)
        if (it.value == v) return it.name.c_str();
    return nullptr;
}

// Reste de la ligne apres les champs deja lus, sans l'espace de tete.
static std::string rest(std::istringstream& in) {
    std::string r;
    std::getline(in, r);
    size_t i = r.find_first_not_of(' ');
    return i == std::string::npos ? std::string() : r.substr(i);
}

bool Descriptor::parse(const std::string& text, std::string& error) {
    *this = Descriptor();
    text_ = text;
    std::istringstream all(text);
    std::string line;
    int lineno = 0;
    bool ended = false;
    ChannelDesc* ch = nullptr;
    auto fail = [&](const char* why) {
        error = "ligne " + std::to_string(lineno) + " : " + why + " : " + line;
        return false;
    };
    while (std::getline(all, line)) {
        ++lineno;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        std::istringstream in(line);
        std::string tag;
        in >> tag;
        if (tag == "rvndesc") {
            int v = 0;
            in >> v;
            if (v != 1) return fail("version non geree");
        } else if (tag == "schema") {
            std::string h;
            in >> h;
            schema_ = std::strtoull(h.c_str(), nullptr, 16);
        } else if (tag == "frame_size") {
            in >> frame_size_;
        } else if (tag == "enum") {
            int id = 0, n = 0;
            in >> id >> n;
            if (id != int(enums_.size())) return fail("identifiant d'enum inattendu");
            enums_.push_back(EnumDesc{rest(in), {}});
        } else if (tag == "item") {
            if (enums_.empty()) return fail("item hors enum");
            EnumItem it;
            in >> it.value;
            it.name = rest(in);
            enums_.back().items.push_back(it);
        } else if (tag == "channel") {
            ChannelDesc c;
            int n = 0;
            in >> c.id >> c.frame_offset >> c.size >> n;
            c.name = rest(in);
            if (in.fail() || c.id != int(channels_.size())) return fail("canal invalide");
            channels_.push_back(c);
            ch = &channels_.back();
        } else if (tag == "field") {
            if (!ch) return fail("champ hors canal");
            FieldDesc f;
            int idx = 0;
            std::string kind, unit;
            in >> idx >> f.parent >> kind >> f.offset >> f.size >> f.count >> f.enum_id >> unit;
            f.path = rest(in);
            if (in.fail() && f.path.empty()) return fail("champ incomplet");
            if (idx != int(ch->fields.size())) return fail("index de champ inattendu");
            if (!parse_kind(kind, f.kind)) return fail("nature inconnue");
            if (f.parent >= idx) return fail("parent apres l'enfant");
            if (f.enum_id >= int(enums_.size())) return fail("enum inconnue");
            if (f.offset + f.bytes() > ch->size) return fail("champ hors du canal");
            f.unit = unit == "-" ? "" : unit;
            size_t dot = f.path.rfind('.');
            f.name = dot == std::string::npos ? f.path : f.path.substr(dot + 1);
            if (f.parent >= 0) ch->fields[size_t(f.parent)].children.push_back(idx);
            else ch->roots.push_back(idx);
            ch->fields.push_back(f);
        } else if (tag == "end") {
            ended = true;
            break;
        } else {
            return fail("enregistrement inconnu");
        }
    }
    if (!ended) { error = "descripteur tronque : 'end' absent"; return false; }
    for (const auto& c : channels_)
        if (c.frame_offset + c.size > frame_size_) { error = "canal hors trame : " + c.name; return false; }
    return true;
}

bool Descriptor::load(const std::string& path, std::string& error) {
    std::ifstream f(path, std::ios::binary);
    if (!f) { error = "impossible d'ouvrir " + path; return false; }
    std::stringstream ss;
    ss << f.rdbuf();
    return parse(ss.str(), error);
}

const ChannelDesc* Descriptor::channel(int id) const {
    return id >= 0 && id < int(channels_.size()) ? &channels_[size_t(id)] : nullptr;
}

const FieldDesc* Descriptor::field(FieldRef r) const {
    const ChannelDesc* c = channel(r.channel);
    return c && r.field >= 0 && r.field < int(c->fields.size()) ? &c->fields[size_t(r.field)] : nullptr;
}

const EnumDesc* Descriptor::enum_of(const FieldDesc& f) const {
    return f.enum_id >= 0 && f.enum_id < int(enums_.size()) ? &enums_[size_t(f.enum_id)] : nullptr;
}

uint32_t Descriptor::frame_offset(FieldRef r) const {
    return channel(r.channel)->frame_offset + field(r)->offset;
}

std::string Descriptor::full_path(FieldRef r) const {
    const ChannelDesc* c = channel(r.channel);
    const FieldDesc* f = field(r);
    return c && f ? c->name + "." + f->path : std::string("?");
}

FieldRef Descriptor::find(const std::string& full) const {
    for (const auto& c : channels_) {
        if (full.compare(0, c.name.size() + 1, c.name + ".") != 0) continue;
        const std::string p = full.substr(c.name.size() + 1);
        for (size_t i = 0; i < c.fields.size(); ++i)
            if (c.fields[i].path == p) return FieldRef{c.id, int(i)};
    }
    return FieldRef{};
}

std::vector<FieldRef> Descriptor::leaves() const {
    std::vector<FieldRef> out;
    for (const auto& c : channels_)
        for (size_t i = 0; i < c.fields.size(); ++i)
            if (c.fields[i].is_leaf() && c.fields[i].kind != Kind::Other)
                out.push_back(FieldRef{c.id, int(i)});
    return out;
}

int64_t read_integer(const FieldDesc& f, const unsigned char* p, uint32_t index) {
    p += size_t(f.size) * index;
    uint64_t u = 0;
    std::memcpy(&u, p, f.size <= 8 ? f.size : 8);
    const bool is_signed = f.kind == Kind::Int || f.kind == Kind::Enum;
    if (is_signed && f.size < 8) {
        const uint64_t sign = uint64_t(1) << (8 * f.size - 1);
        if (u & sign) u |= ~((sign << 1) - 1);
    }
    return int64_t(u);
}

double read_number(const FieldDesc& f, const unsigned char* p, uint32_t index) {
    if (f.kind == Kind::Float) {
        const unsigned char* q = p + size_t(f.size) * index;
        if (f.size == 4) { float v; std::memcpy(&v, q, 4); return v; }
        if (f.size == 8) { double v; std::memcpy(&v, q, 8); return v; }
        return 0.0;                              // long double : non gere
    }
    if (f.kind == Kind::UInt || f.kind == Kind::Pointer)
        return double(uint64_t(read_integer(f, p, index)));
    return double(read_integer(f, p, index));
}

std::string format_number(const Descriptor& d, const FieldDesc& f, double v) {
    char buf[64];
    switch (f.kind) {
    case Kind::Bool:
        return v != 0.0 ? "true" : "false";
    case Kind::Enum:
        if (const EnumDesc* e = d.enum_of(f))
            if (const char* n = e->name_of(int64_t(v))) return n;
        std::snprintf(buf, sizeof buf, "%" PRId64 " (?)", int64_t(v));
        return buf;
    case Kind::Float:
        std::snprintf(buf, sizeof buf, "%.6g", v);
        return buf;
    case Kind::Pointer:
        std::snprintf(buf, sizeof buf, "0x%" PRIx64, uint64_t(v));
        return buf;
    default:
        std::snprintf(buf, sizeof buf, "%.0f", v);
        return buf;
    }
}

std::string format_value(const Descriptor& d, const FieldDesc& f, const unsigned char* p,
                         uint32_t index) {
    if (f.kind == Kind::Int || f.kind == Kind::UInt) {
        char buf[32];
        const int64_t v = read_integer(f, p, index);
        if (f.kind == Kind::UInt) std::snprintf(buf, sizeof buf, "%" PRIu64, uint64_t(v));
        else std::snprintf(buf, sizeof buf, "%" PRId64, v);
        return buf;
    }
    return format_number(d, f, read_number(f, p, index));
}

} // namespace raven
