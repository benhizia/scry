#include "raven/ini.h"

#include <cstdio>

namespace raven {
namespace {

std::string trim(const std::string& s) {
    std::size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r')) --b;
    return s.substr(a, b - a);
}

// Retire un commentaire de fin de ligne. Un '#' ou un ';' entre guillemets
// n'en est pas un : une valeur a parfaitement le droit d'en contenir.
std::string strip_comment(const std::string& s) {
    bool quoted = false;
    for (std::size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '"') quoted = !quoted;
        else if (!quoted && (s[i] == '#' || s[i] == ';')) return s.substr(0, i);
    }
    return s;
}

std::string unquote(const std::string& s) {
    if (s.size() >= 2 && s.front() == '"' && s.back() == '"') return s.substr(1, s.size() - 2);
    return s;
}

} // namespace

bool Ini::load(const std::string& path, std::string& error) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) { error = "fichier illisible : " + path; return false; }
    std::string text;
    char buf[4096];
    std::size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) text.append(buf, n);
    std::fclose(f);
    if (!parse(text, error)) {
        error = path + " : " + error;
        return false;
    }
    return true;
}

bool Ini::parse(const std::string& text, std::string& error) {
    sections_.clear();
    std::size_t start = 0;
    int line_no = 0;
    while (start <= text.size()) {
        const std::size_t end = text.find('\n', start);
        const std::string raw = text.substr(start, (end == std::string::npos ? text.size() : end) - start);
        start = end == std::string::npos ? text.size() + 1 : end + 1;
        ++line_no;

        const std::string line = trim(strip_comment(raw));
        if (line.empty()) continue;

        if (line.front() == '[') {
            if (line.back() != ']' || line.size() < 3) {
                error = "ligne " + std::to_string(line_no) + " : section mal formee : " + line;
                return false;
            }
            Section s;
            s.name = trim(line.substr(1, line.size() - 2));
            if (s.name.empty()) {
                error = "ligne " + std::to_string(line_no) + " : section sans nom";
                return false;
            }
            sections_.push_back(s);
            continue;
        }
        const std::size_t eq = line.find('=');
        if (eq == std::string::npos) {
            error = "ligne " + std::to_string(line_no) + " : ni section ni cle = valeur : " + line;
            return false;
        }
        if (sections_.empty()) {
            error = "ligne " + std::to_string(line_no) + " : cle hors de toute section : " + line;
            return false;
        }
        const std::string key = trim(line.substr(0, eq));
        if (key.empty()) {
            error = "ligne " + std::to_string(line_no) + " : cle vide";
            return false;
        }
        sections_.back().entries.push_back(
            std::make_pair(key, unquote(trim(line.substr(eq + 1)))));
    }
    return true;
}

const Ini::Section* Ini::find(const std::string& name) const {
    for (const Section& s : sections_)
        if (s.name == name) return &s;
    return nullptr;
}

bool Ini::has(const std::string& section) const { return find(section) != nullptr; }

std::string Ini::get(const std::string& section, const std::string& key,
                     const std::string& fallback) const {
    const Section* s = find(section);
    if (!s) return fallback;
    for (const auto& e : s->entries)
        if (e.first == key) return e.second;
    return fallback;
}

std::vector<std::string> Ini::sections() const {
    std::vector<std::string> out;
    for (const Section& s : sections_) out.push_back(s.name);
    return out;
}

std::vector<std::string> Ini::sections_with(const std::string& prefix) const {
    std::vector<std::string> out;
    for (const Section& s : sections_)
        if (s.name.compare(0, prefix.size(), prefix) == 0) out.push_back(s.name);
    return out;
}

} // namespace raven
