// Lecteur de fichier INI, repris de SwitchSpy et reduit a ce dont RAVEN a
// besoin : des sections, des cles, des valeurs. Rien d'autre.
//
//   # commentaire, ou ;
//   [link.principal]
//   type    = tcp
//   listen  = 0.0.0.0:8001     # un commentaire en bout de ligne compte aussi
//   forward = 10.0.0.2:8002
//
// L'ordre des sections est celui du fichier : un fichier de configuration se
// relit, et l'ordre y porte du sens pour celui qui l'ecrit.
#pragma once
#include <string>
#include <vector>

namespace raven {

class Ini {
public:
    bool load(const std::string& path, std::string& error);
    bool parse(const std::string& text, std::string& error);

    bool has(const std::string& section) const;
    // "" si la cle manque, 'fallback' si on en veut une autre.
    std::string get(const std::string& section, const std::string& key,
                    const std::string& fallback = std::string()) const;
    // Noms complets des sections, dans l'ordre du fichier.
    std::vector<std::string> sections() const;
    // Sections dont le nom commence par 'prefix', nom complet garde :
    // sections_with("link.") rend {"link.principal", "link.secours"}.
    std::vector<std::string> sections_with(const std::string& prefix) const;

private:
    struct Section {
        std::string name;
        std::vector<std::pair<std::string, std::string>> entries;
    };
    const Section* find(const std::string& name) const;
    std::vector<Section> sections_;
};

} // namespace raven
