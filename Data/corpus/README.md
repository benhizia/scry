# Corpus de headers d'essai

Rejoué par `tests/test_corpus.py` avec le vrai castxml et le vrai g++, avec et
sans membres non publics. Pour chaque header : le parsing réussit, les
assertions d'ABI compilent, et, si Dear ImGui est dans `third_party/imgui`, le
header ImGui généré compile en `-Wall -Wextra -Werror`, se lie, et ses
fonctions de rendu s'exécutent en headless.

## Origine

`01` à `10` et `test_*` viennent d'InterfaceInspector (dossier `test/`), la
première tentative de Scry. Ils y étaient traités par castxml, Doxygen et un
programme C++ compilé à la volée. `11_constructeurs.hpp` est propre à Scry.

## Modifications par rapport à l'original

Les headers d'origine n'étaient pas autonomes : ils compilaient sous macOS
grâce aux inclusions transitives de libc++, pas avec libstdc++ ni avec la STL
de MSVC. Ils ont été complétés, sans toucher aux types :

| Header | Modification |
|---|---|
| `04_templates.hpp` | `#include <string>` |
| `07_static_friends.hpp` | `static const double PI` devient `static constexpr double PI` : un initialiseur dans la classe pour un `static const double` est une extension de clang (`-Wstatic-float-init`), refusée par gcc et MSVC |
| `08_operators_raii.hpp` | `#include <string>`, `#include <sys/types.h>` pour `ssize_t` (POSIX, donc ce header ne compile pas sous MSVC) |
| `09_interfaces_patterns.hpp` | `#include <mutex>`, `#include <string>` |
| `10_modern_cpp.hpp` | `#include <atomic>`, `#include <mutex>`, `#include <string>` |

## Ce que le corpus a révélé dans Scry

- `include_non_public = true` produisait un header d'ABI qui ne compilait
  nulle part : `offsetof` sur un membre privé est interdit hors de la classe.
  Le modèle porte maintenant l'accès de chaque membre (`Field.access`), et les
  membres non publics sont exclus des `offsetof`.
- Le visualiseur natif construisait une instance de chaque type. Pour un type
  dont le constructeur par défaut est déclaré dans le header mais défini dans
  la bibliothèque du tiers, il ne se liait plus. `Struct.inline_constructible`
  le détecte via castxml, récursivement sur les bases et les membres.
- Le C++ généré produisait des avertissements `unused` sur une structure sans
  membre visible.
