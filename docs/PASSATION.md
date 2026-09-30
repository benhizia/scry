# Passation : où en est le projet, ce qui reste à faire

> Rapport écrit pour reprendre le travail avec Claude Code en local. État au
> 30 septembre 2026, `main` = `1a7d25a` (PR 1 à 8 fusionnées). La vérification
> Windows que ce rapport demandait en premier a été faite en local le même
> jour : voir § 1.3.

## 1. Où on en est

### 1.1 Scry (outil de build, Python)

Fait et fusionné : parsing castxml + pygccxml, modèle plat, génération C++
(`static_assert`, introspection), `scry verify` (cl, g++, clang++), héritage,
commentaires de documentation, diff de modèles JSON, canal SHM de démonstration
(`scry producer`, `scry watch`), bindings pybind11 et interpréteur Python
embarqué pour l'autotest, filtrage des types, `scry raven` (descripteur
`.rvndesc` et glue de publication, `--channel` pour une variable, `--struct`
pour une struct transportée par le réseau). Depuis le 30 septembre 2026, l'axe
Python embarqué est **clos pour l'essentiel** : les **fonctions du header**
appelables depuis Python (B1), les **vues sur `std::vector`** et sur les paires
pointeur + compteur (B2), le **rechargement à chaud** des scénarios (B3), le
**budget de temps par tick** avec histogramme et profil (B5), et la **liste
blanche d'écriture** (B6). Un script embarqué pilote désormais l'application au
lieu de reposer des variables, sait ce qu'il coûte, n'écrit que là où on l'y
autorise, et se corrige sans relancer le simulateur.

### 1.2 RAVEN (acquisition, enregistrement, visualisation, C++)

| Brique | État | Où |
|---|---|---|
| Logiciel minimal : `raven` (enregistreur sans IHM), `raven-view` (ImGui paresseux), `raven-cat`, `demo_sim` | fait | `raven/`, voir `raven/README.md` |
| Source SHM (anneau de 64 trames, pertes comptées) | fait | `src/engine/shm_source.cpp`, `include/raven/producer.h` |
| Couche réseau `raven::net` (TCP, UDP, multicast) | fait (étape 1 de la reprise SwitchSpy) | `include/raven/sockets.h`, `src/core/sockets.cpp` |
| Écoute passive multicast (plugin `mcast`) | fait (étape 2) | `src/engine/mcast_source.cpp` |
| Registre des plugins de source | fait | `src/engine/sources.cpp` |
| Format `.rvn` version 2 (canal par enregistrement ; v1 relue) | fait | `src/core/rvn.cpp` |

Tests qui passent sous Linux : `raven_tests`, `raven_net_tests`,
`raven_mcast_tests` (CTest), `tests/test_raven_gen.py`,
`tests/test_raven_e2e.py`, et toute la suite Scry (`pytest`).

### 1.3 Windows et MSVC : fait, et ce qui reste à éprouver

Le cloud ne pouvait que compiler avec mingw, sans rien exécuter (pas de wine).
C'était le premier point à vérifier en local. **Fait le 30 septembre 2026**,
sans aucun écart à corriger :

```
MSVC 19.44.35216 · Visual Studio 17 2022 · x64 · Windows SDK 10.0.26100
```

| Vérification | Résultat |
|---|---|
| Construction | toutes les cibles, `raven-view` (Win32 + DirectX 11) et `demo_sim` comprises ; descripteurs des scénarios générés par `scry raven --struct` |
| `raven_tests` | passé, 0,04 s |
| `raven_net_tests` | passé, 1,14 s |
| `raven_mcast_tests` | passé, 6,11 s |
| `test_raven_e2e.py`, `test_raven_gen.py` | 8 tests passés, sur les binaires MSVC |
| Avertissements | **aucun** en `/W4`, reconstruction propre, cœur et visualiseur (ImGui compris) |
| Suite Scry complète | 291 tests passés ce jour-là, 330 après la fusion de B1 et B2, chiffres rejoués |

Les commandes, avec les deux pièges du poste :

```
cmake -S raven -B build/raven-msvc -G "Visual Studio 17 2022" -A x64 ^
      -DPython3_EXECUTABLE=<racine>/.venv/Scripts/python.exe
cmake --build build/raven-msvc --config Release -- -m
ctest --test-dir build/raven-msvc -C Release --output-on-failure
set RAVEN_BUILD_DIR=<racine>\build\raven-msvc
pytest tests/test_raven_e2e.py tests/test_raven_gen.py
```

- `Python3_EXECUTABLE` doit désigner le venv : `raven_mcast_tests` fait appeler
  `scry raven` par CMake, ce qui demande pygccxml et castxml. Sans cela,
  `find_package(Python3)` prend l'interpréteur système, qui ne les a pas.
- `RAVEN_BUILD_DIR` sert à viser un dossier de build autre que `build/raven`.
  `tests/test_raven_e2e.py` prend sinon le premier `build/raven*` qui contient
  un `raven.exe` : garder un seul dossier de build complet évite de tester une
  construction partielle par mégarde.

**Ce que cela ne prouve pas.** Tout s'est joué en boucle locale, sur une seule
machine : le multicast est passé par `127.0.0.1`, pas par une carte réseau ni
un commutateur. Un `IP_MULTICAST_IF` sur la mauvaise interface, ou un TTL trop
court, ne se verraient pas. Pour les couvrir il faut deux postes, ou au moins
forcer l'interface sur la carte physique. À rejouer aussi après l'étape 3, qui
ajoute des fils et une file SPSC : c'est là que Windows diverge le plus
souvent.

## 2. InterfaceInspector : ce qui a été comparé, ce qui reste à reprendre

| Branche d'InterfaceInspector | Analysée | Repris dans Scry/RAVEN | Reste |
|---|---|---|---|
| `master` (`bda7c24`) : métadonnées castxml + Doxygen en JSON, tests de headers, petit IPC SHM | oui, au début | vérification d'ABI sous gcc et clang, commentaires de documentation relus dans le header, corpus de tests de headers, idées sur l'héritage et le packing | rien d'important |
| `claude/describe-selected-011CUvmX5APbfMHaiMR4Xf68` (`3185a25`) : **SwitchSpy**, relais réseau + IHM ImGui. PR 1 d'InterfaceInspector ouverte, non fusionnée | oui | étapes 1 (sockets) et 2 (multicast) | étapes 3 à 6, ci-dessous |

L'analyse complète, avec la correspondance des classes et des noms, est dans
[RAVEN_REPRISE_SWITCHSPY.md](RAVEN_REPRISE_SWITCHSPY.md). En résumé,
SwitchSpy apporte des briques (sockets, moniteur de flux, journal, mesures de
performance, six scénarios de test) mais **son relais n'a jamais été câblé**
(`main.cpp` s'arrête sur un `TODO`).

Pour relire SwitchSpy en local :

```
cd InterfaceInspector
git fetch origin
git worktree add ../switchspy origin/claude/describe-selected-011CUvmX5APbfMHaiMR4Xf68
# le code est dans ../switchspy/SwitchSpy
```

## 3. Ce qui reste à faire, dans l'ordre proposé

### 3.1 Reprise de SwitchSpy (suite du plan)

**Étape 3 : relais TCP et UDP.** RAVEN se place entre deux équipements A et B.

- Plugins `TcpRelay` et `UdpRelay` dans `raven/src/engine/`, déclarés dans
  `sources.cpp` (`tcp:` et `udp:`), en s'appuyant sur `raven::net`.
- Ajouter `Direction {AtoB, BtoA}` à `Frame` et au `.rvn` (octet réservé de
  l'en-tête d'enregistrement v2, qui vaut 0 aujourd'hui).
- **Un fil par sens : recevoir, transférer, puis pousser une copie** dans une
  file sans verrou (SPSC) lue par le moteur. Le relais ne doit jamais attendre
  le moteur ni le visualiseur. Aujourd'hui, `Engine::on_frame` est appelé sous
  mutex depuis le fil d'acquisition : le relais doit passer par la file.
- TCP est un flux : découper en messages de la taille de la struct du sens
  (`recv_all`), un type de struct par sens pour commencer.
- Configuration : `raven.ini` avec `[link.x]` (`listen`, `forward`, `a_to_b`,
  `b_to_a`), analyseur INI repris de SwitchSpy (`src/config/ini_parser.cpp`).
- Tests : scénarios 01 (TCP), 02 (UDP, CRC32) et 06 (structs complexes) de
  SwitchSpy, automatisés comme `raven/tests/test_mcast.cpp`. Leurs
  `shared.hpp` sont à reprendre sans les `static_assert` de taille : ceux des
  scénarios 03 et 04 étaient faux sur x86-64, à vérifier pour les autres.

**Étape 4 : santé, journal, performances.**

- `FlowControlMonitor` de SwitchSpy → `raven::LinkHealth` (débits, écart,
  pression, extrémité muette, envois bloqués). Corriger les `static auto
  last_warning` locaux, partagés entre toutes les instances.
- `Logger` → `raven::log` avec des macros préfixées `RAVEN_LOG_*`, et un sink
  qui envoie le journal au visualiseur (nouveau message `log` du protocole).
- `benchmark` → `raven::perf`, pour un futur `raven --bench`.
- Panneaux *Journal* et *Performances* dans `raven-view`.
- Test : scénario 05 (écart de débit).

**Étape 5 : build Windows.** Étape allégée : le générateur Visual Studio
ordinaire suffit déjà, tout construit et tout passe (§ 1.3). Il ne reste que du
confort : reprendre `CMakePresets.json`, `build.cmd` et
`docs/BUILDING_WINDOWS.md` de SwitchSpy, adaptés aux cibles de RAVEN, pour
n'avoir plus à passer `-DPython3_EXECUTABLE` à la main.

**Étape 6 : rejeu vers le réseau.** Réémettre un `.rvn` sur le groupe
multicast d'origine (`MulticastReplay`). Plus tard encore : table
`identifiant de message → type` pour les liaisons qui transportent plusieurs
structs.

### 3.2 Priorités retenues après le logiciel minimal

Dans [RAVEN_CONTOUR.md](RAVEN_CONTOUR.md) :

1. **Tampon de pré-déclenchement** : garder les N dernières secondes en
   mémoire, et les écrire au déclenchement.
2. **Index et robustesse aux coupures** : index temps/trame dans le `.rvn`,
   CRC par bloc. Les enregistrements de taille fixe rendent déjà un fichier
   coupé lisible.
3. **Pilotage par l'autotest** : le protocole texte est déjà pilotable
   (`nc 127.0.0.1 47800`, puis `hello`) ; il manque un client Python pour
   l'autotest.

### 3.3 Études prêtes, non codées

- **Prédicats utilisateur** : petit langage d'expressions évalué sur chaque
  trame, sans Lua ni Python dans `raven.exe`. Dictionnaire, fonctions
  (`changed`, `rose`, `fell`, `prev`, `delta`, `held`, `since`...), actions
  et intégration à l'IHM :
  [RAVEN_FORCAGE_PREDICATS.md](RAVEN_FORCAGE_PREDICATS.md) § 2. Découpage
  proposé : analyseur et tests, puis protocole (`pred add/del`), puis IHM.
- **Forçage de valeurs** : par le séquenceur du simulateur (un appel
  `apply_overrides()` après chaque module), avec la sûreté entre fils déjà
  étudiée ; en réseau, par le relais. Même document, § 1.

### 3.4 Autres points ouverts

- Pointeurs suivis (struct de pointeurs) et champs de bits : non gérés dans
  le `.rvndesc`.
- Relecture d'un `.rvn` dans `raven-view` et rejeu : absents.
- Validation MSVC : **faite** pour RAVEN et pour Scry (§ 1.3), en boucle
  locale seulement. Reste la CI, piste A1 d'[AMELIORATIONS.md](AMELIORATIONS.md) :
  rien n'empêche aujourd'hui cette validation de se périmer au prochain commit.
- Les deux branches de Scry qui restaient sont **fusionnées** depuis (30
  septembre 2026), dans cet ordre, la seconde étant bâtie sur la première.
  Résumé pour qui relit l'historique :
  - `feature/pybind-fonctions` : piste **B1**. Les fonctions libres
    des headers et les méthodes publiques non virtuelles sont exposées en
    Python embarqué (`register_functions`, méthodes sur le `py::class_` de leur
    classe). Un script pilote au lieu de reposer des variables. Règle centrale :
    seule une fonction **définie** dans le header est liée, sinon le module ne
    se lierait pas ; un motif sans joker dans `[pybind] functions` vaut
    autorisation explicite pour les autres.
  - `feature/pybind-vues-stl` : piste **B2**. `std::vector` exposé
    en vue numpy (éléments numériques) ou en `VectorView` (structures, enums,
    chaînes), et paires pointeur + compteur déclarées dans `[pybind] spans`.
    `VectorView` garde le conteneur et non ses octets : un `push_back` du côté
    C++ ne laisse pas une vue pendante.
  - La suite Scry compte 357 tests depuis, contre 291 avant.
- Il ne reste donc **aucune branche en attente** : `main` porte tout, et les
  branches `claude/*`, `feature/*` et `docs/*` du dépôt distant peuvent être
  supprimées.
- La PR 1 d'InterfaceInspector (SwitchSpy) est toujours ouverte.

## 4. Documents de référence

| Document | Contenu |
|---|---|
| `raven/README.md` | workflow, construction, choix du logiciel minimal |
| [RAVEN_CONTOUR.md](RAVEN_CONTOUR.md) | contour fonctionnel et feuille de route |
| [RAVEN_GLUE.md](RAVEN_GLUE.md) | ce que Scry génère pour RAVEN, qui fait quoi |
| [RAVEN_REPRISE_SWITCHSPY.md](RAVEN_REPRISE_SWITCHSPY.md) | plan de reprise de SwitchSpy |
| [RAVEN_FORCAGE_PREDICATS.md](RAVEN_FORCAGE_PREDICATS.md) | forçage de valeurs, prédicats utilisateur |
| [ARCHITECTURE_BRIQUES.md](ARCHITECTURE_BRIQUES.md), [ETUDE_ACQUISITION.md](ETUDE_ACQUISITION.md), [ETUDE_SOURCES.md](ETUDE_SOURCES.md) | études d'architecture |
| [AMELIORATIONS.md](AMELIORATIONS.md) | pistes d'amélioration de Scry |
