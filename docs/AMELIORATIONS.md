# Scry : pistes d'amélioration

Brainstorm structuré sur ce qui rendrait Scry plus fiable, plus utile au
quotidien sur un simulateur, et plus simple à adopter. Chaque piste est
rattachée à un problème observé ou mesuré, et chiffrée en valeur, effort et
risque. Le document remplace la liste de la section 9 du README, devenue en
partie obsolète (diff d'ABI, démo live et tests du modèle sont faits).

Les efforts sont des estimations, en jours de travail pour quelqu'un qui
connaît le code : **S** ≤ 2 j, **M** 3 à 5 j, **L** 1 à 3 semaines.

---

## 1. Résumé

Scry fait aujourd'hui ce qu'il promet sous Linux : modèle fidèle au compilateur,
vérification d'ABI, lecture live, Python embarqué sans copie, 266 tests. Trois
faiblesses dominent :

1. **Rien n'est validé automatiquement sur la vraie cible.** MSVC, le
   visualiseur DirectX et les scripts `.bat` n'ont été compilés qu'avec mingw
   ou pas du tout, et il n'y a aucune CI.
2. **Le Python embarqué ne sait que lire et écrire des données.** Pas de
   fonctions exposées, pas de `std::vector`, pas de rechargement de script :
   c'est là que se joue l'usage sur simulateur.
3. **L'outil passe mal à l'échelle d'un vrai header tiers.** Pas de filtrage
   des types dans les IHM, parsing à froid lent (9,3 s mesurées sur un header
   qui tire la STL), code généré monolithique.

**Les cinq pistes à lancer en premier** (détail dans les fiches) :

| # | Piste | Pourquoi maintenant | Effort |
|---|---|---|---|
| A1 | CI GitHub Actions Linux + Windows/MSVC | valide enfin la cible réelle à chaque push | M |
| B1 | Fonctions du header exposées en Python | passer de « lire/écrire » à « piloter » | M |
| B2 | `std::vector`, `std::string` et pointeurs+taille en vues Python | les interfaces réelles en sont pleines | M |
| C1 | Filtrage des types (IHM, CLI, config) | conditionne l'usage sur un vrai header | S |
| B3 | Rechargement à chaud des scripts embarqués | cycle de mise au point en secondes, sans relancer le simulateur | S |

---

## 2. État des lieux

### Ce qui marche, et comment on le sait

| Domaine | Preuve |
|---|---|
| Modèle et parsing | corpus de 17 headers passé par castxml et g++, avec et sans membres non publics |
| Garantie d'ABI | `static_assert` compilés par g++ ; `-D_GLIBCXX_DEBUG` détecté comme divergence |
| C++ généré | compilé en `-Wall -Wextra -Werror`, exécuté en headless contre Dear ImGui |
| Mémoire partagée | 300 lectures sous écriture continue, 0 copie déchirée (Python/Linux et C++/wine) |
| Python embarqué | hôte C++ + module généré, octets relus aux offsets du modèle ; démo CMake |
| Performance Python | 60 ns (élément numpy) à 420 ns (écriture globale), ~4 µs par cycle type |

### Ce qui manque ou coince

| Constat | Mesure ou source |
|---|---|
| MSVC jamais utilisé réellement | tout Windows validé par mingw/wine ; `scry verify` avec cl non rejoué depuis l'héritage |
| Aucune CI | pas de dossier `.github/` |
| Parsing lent à froid | 9,3 s à froid, 0,49 s avec cache, sur `test_structs_complexe.h` |
| Compilation des bindings lente | ~20 s pour un module pybind11 sur un seul header |
| STL ignorée par les bindings | `std::vector`, `std::map`… : « non liée (STL, pas un POD) » |
| Aucune fonction exposée | seuls types et variables passent en Python |
| Pas de filtrage des types | tous les types des headers apparaissent dans les IHM |
| Code mort | `SharedMemorySource` (`runtime/memory.py`) remplacé par `runtime/shm.py` |
| Lint résiduel | `E741` (`O`) dans `codegen/pybind.py`, imports inutiles dans `autotest/` |
| Gros modules | `parsing/introspect.py` 878 lignes, `codegen/pybind.py` 846 lignes |

---

## 3. Méthode de priorisation

- **Valeur** (1 à 5) : ce que la piste débloque pour l'usage visé, un
  simulateur C++ dont on lit, vérifie et pilote les interfaces.
- **Effort** : S, M, L (voir plus haut).
- **Risque** : ce qui peut faire échouer ou coûter plus que prévu.
- **Priorité** : P1 à lancer maintenant, P2 ensuite, P3 opportuniste.

---

## 4. Vue d'ensemble

| ID | Piste | Axe | Valeur | Effort | Priorité |
|---|---|---|---|---|---|
| A1 | CI Linux + Windows/MSVC | Fiabilité | 5 | M | P1 |
| A2 | Rejouer `scry verify` et la démo sous MSVC réel | Fiabilité | 5 | S | P1 |
| A3 | Test d'ordre des champs de bits compilé et exécuté | Fiabilité | 3 | S | P2 |
| A4 | Détection des conteneurs STL illisibles à distance | Fiabilité | 3 | S | P2 |
| A5 | Offset des bases virtuelles sur l'objet complet | Fiabilité | 2 | M | P3 |
| B1 | Fonctions du header exposées en Python | Python embarqué | 5 | M | P1 |
| B2 | Vues Python sur `std::vector`, `std::string`, pointeur + taille | Python embarqué | 5 | M | P1 |
| B3 | Rechargement à chaud des scripts | Python embarqué | 4 | S | P1 |
| B4 | Vue numpy structurée d'une struct entière | Python embarqué | 4 | M | P2 |
| B5 | Budget de temps par tick et profilage | Python embarqué | 4 | S | P2 |
| B6 | Mode lecture seule et liste blanche d'écriture | Python embarqué | 3 | S | P2 |
| B7 | Enregistrement et rejeu d'un vol | Python embarqué | 4 | L | P2 |
| B8 | Métadonnées des commentaires : unités, bornes | Python embarqué | 4 | M | P2 |
| B9 | Autotest : couverture des interfaces et fuzzing borné | Python embarqué | 3 | M | P3 |
| C1 | Filtrage des types | Observation | 5 | S | P1 |
| C2 | Édition des valeurs dans les IHM | Observation | 4 | S | P2 |
| C3 | Courbes live (ImPlot) | Observation | 4 | M | P2 |
| C4 | Points de surveillance : alerte sur condition | Observation | 3 | S | P2 |
| C5 | Transport réseau (UDP) en plus de la mémoire partagée | Observation | 3 | M | P3 |
| C6 | Conseiller de layout : padding récupérable | Observation | 2 | S | P3 |
| D1 | Instanciations de templates déclarées dans la config | Modèle | 4 | S | P2 |
| D2 | Cibles 32 bits et big-endian | Modèle | 2 | M | P3 |
| D3 | Diff d'ABI : renommages et déplacements | Modèle | 2 | S | P3 |
| D4 | Schéma JSON versionné du modèle | Modèle | 2 | S | P3 |
| E1 | Cache de parsing par défaut, mesuré et documenté | Adoption | 4 | S | P1 |
| E2 | Bindings découpés en plusieurs unités de compilation | Adoption | 3 | M | P2 |
| E3 | Paquet installable : wheel, castxml en dépendance | Adoption | 3 | S | P2 |
| E4 | Intégration CMake de première classe | Adoption | 4 | M | P2 |
| F1 | Nettoyage : code mort, lint, README | Dette | 2 | S | P1 |
| F2 | Découpage de `introspect.py` et `pybind.py` | Dette | 2 | M | P3 |

---

## 5. Fiches détaillées

### Axe A : fiabilité et validation sur la vraie cible

#### A1. CI GitHub Actions Linux + Windows/MSVC · P1 · M

**Problème.** Tout le chemin Windows a été validé par mingw et wine, jamais
avec `cl.exe` ; aucune régression n'est détectée automatiquement.

**Proposition.** Deux jobs :
- `ubuntu-latest` : `pip install -e ".[dev]" castxml pybind11 numpy`, `ruff`,
  `pytest` complet (corpus, headless ImGui, Python embarqué), démo
  `autotest/run_demo.sh` ;
- `windows-latest` : MSVC, `scry check`, `scry verify` sur le corpus,
  compilation du visualiseur natif, `autotest\run_demo.bat`.

**Esquisse.** `.github/workflows/ci.yml` ; cacher `third_party/imgui` et le
cache pygccxml. Les tests qui sautent sans toolchain (`test_corpus.py`,
`test_pybind_embed.py`) tournent alors pour de vrai.

**Risque.** Le runner Windows manque de castxml : `pip install castxml` le
fournit. Temps de CI : ~5 min Linux, ~10 min Windows, acceptable.

**Réussite.** Un badge vert sur `main`, et une PR qui casse l'ABI échoue.

#### A2. Rejouer `scry verify` et la démo sous MSVC réel · P1 · S

**Problème.** Deux points restent non vérifiés : `offsetof` sur membres hérités
avec `cl` (repli prévu : `[codegen] abi_inherited = false`), et la démo
`run_demo.bat` depuis le passage au module généré.

**Proposition.** Session manuelle sur le poste Windows, puis intégrer les cas
dans A1. Corriger ce qui casse.

#### A3. Test d'ordre des champs de bits · P2 · S

**Problème.** Le décodage suit les offsets de castxml, mais l'ordre
d'allocation des bits n'est pas normalisé : jamais confronté au compilateur.

**Proposition.** Générer un petit programme qui écrit chaque champ de bits
d'une instance, en vide les octets, et comparer au décodage Python
(`runtime/memory.decode`). Même principe que `tests/cpp/pybind_host.cpp`.

#### A4. Signaler les conteneurs STL illisibles à distance · P2 · S

**Problème.** En mémoire partagée, un `std::vector` n'est que trois pointeurs
du processus producteur. Les IHM affichent ces adresses comme des données.

**Proposition.** Marquer dans le modèle les types dont la lecture distante n'a
pas de sens (`truncated = "remote"`), les griser dans les IHM et `scry watch`,
et l'expliquer dans l'inspecteur. Distinct de B2 : en Python embarqué, même
processus, ces conteneurs sont lisibles.

#### A5. Offset des bases virtuelles · P3 · M

**Problème.** Une base virtuelle est signalée, pas placée.

**Proposition.** Pour l'objet complet, l'offset est fixe : le calculer en
compilant `static_cast<VBase*>(&obj)` dans un programme généré, comme pour A3.
Rare dans les interfaces de simulateur, d'où P3.

---

### Axe B : Python embarqué, le cœur de l'usage simulateur

#### B1. Fonctions du header exposées en Python · P1 · M

**Problème.** Un script peut positionner des variables, pas appeler
`reset()`, `set_mode(Mode)` ou `compute_trim(const Etat&)`. Aujourd'hui il faut
les ajouter à la main dans un module personnalisé.

**Proposition.** Collecter les fonctions libres des headers (castxml les donne,
comme les variables) et les méthodes publiques non virtuelles, puis générer
`m.def(...)` dans `register_functions`. Filtres `[pybind] functions` /
`hide_functions`. Signatures prises en charge d'abord : scalaires, enums,
références et pointeurs vers types liés, `const char*`, `std::string`. Le
reste est commenté dans le header généré, comme les membres non liés.

**Esquisse.** `model.Function` (nom qualifié, retour, arguments décrits par
des `Field`) ; `Introspector._root_functions` sur le modèle de
`_root_variables` ; surcharges gérées par `py::overload_cast`.

**Risque.** Fonctions déclarées dans le header mais absentes de l'édition de
liens : le module ne se lierait plus. Même remède que `inline_constructible` :
n'exposer que ce qui est défini (inline) ou ce qui est explicitement listé.

**Réussite.** `sut.sim.reset()` et `sut.sim.set_mode(sut.sim.Mode.Vol)`
fonctionnent sans glue.

#### B2. Vues Python sur `std::vector`, `std::string`, pointeur + taille · P1 · M

**Problème.** Les bindings écartent tout conteneur STL. Or en Python
embarqué, même processus, un `std::vector<double>` est parfaitement lisible, et
souvent au cœur des interfaces (listes de waypoints, de capteurs).

**Proposition.**
- `std::vector<T>` numérique : vue numpy sur `data()`, taille relue à chaque
  accès ; `T` structure : séquence d'éléments par référence (le `ArrayView`
  existant, sur `data()`/`size()`).
- `std::string` : déjà en `str`, par copie ; garder.
- Paires pointeur + compteur (`Waypoint* wps; int nb_wps;`) : déclarées dans
  la config (`[pybind] spans = sim::Plan::wps: nb_wps`), exposées comme un
  `std::vector`.

**Risque.** Une vue numpy gardée au-delà d'une réallocation du vector pointe
dans le vide. Remède : ne jamais mettre en cache la vue, la reconstruire à
chaque accès (coût ~100 ns), et le documenter.

#### B3. Rechargement à chaud des scripts · P1 · S

**Problème.** Modifier un script impose de relancer le simulateur.

**Proposition.** Dans `autotest_embed.h` et un hôte minimal générique :
surveiller la date des scripts, `importlib.reload` entre deux ticks, garder
l'état du module `sut` (il n'est que des vues). Commande `sut.reload()` en plus.

#### B4. Vue numpy structurée d'une struct entière · P2 · M

**Problème.** Un accès par attribut coûte ~200 ns. Pour lire 200 valeurs par
cycle, c'est 40 µs, encore acceptable, mais pas pour des traitements vectorisés.

**Proposition.** Générer depuis le modèle un `numpy.dtype` à offsets explicites
(noms, formats, offsets, itemsize = sizeof) et exposer `obj.as_record()`, vue
numpy sans copie de la struct. Un tableau de structs devient un tableau
structuré : `plan.legs.as_record()["altitude"]` lit 16 valeurs en un appel.

**Risque.** Champs de bits et types non POD : exclus du dtype, avec leurs
octets en champ opaque.

#### B5. Budget de temps par tick et profilage · P2 · S

**Problème.** Un script trop lent décale le cycle de 20 ms. `tick_budget_ms`
compte les dépassements, sans dire où part le temps.

**Proposition.** Histogramme des durées de tick dans le rapport, pire cas,
et, sur dépassement, un échantillon `cProfile` du tick fautif. Option pour
couper un scénario qui dépasse N fois.

#### B6. Mode lecture seule et liste blanche d'écriture · P2 · S

**Problème.** Un script peut écrire n'importe quelle variable exposée, y
compris des sorties du modèle de vol qu'il ne devrait qu'observer.

**Proposition.** `[pybind] writable = sim::inputs::*` : tout le reste est
généré sans setter. Un mode `--read-only` pour les scripts d'observation.

#### B7. Enregistrement et rejeu d'un vol · P2 · L

**Problème.** Reproduire un défaut vu en séance demande de refaire le vol.

**Proposition.** Enregistrer à chaque tick les octets des variables
sélectionnées (le modèle donne tailles et offsets), dans un fichier
append-only horodaté avec l'empreinte `layout_hash`. Rejeu : réinjecter les
entrées cycle par cycle et comparer les sorties ; relecture dans l'IHM avec
une barre de temps.

**Risque.** Volume : 4 Ko × 50 Hz = 200 Ko/s, ~720 Mo/h ; prévoir une
sélection fine et une compression.

#### B8. Métadonnées tirées des commentaires : unités et bornes · P2 · M

**Problème.** Les commentaires sont déjà lus (docstrings). Ils portent souvent
unités et plages : `double altitude; // [ft] 0..60000`.

**Proposition.** Reconnaître une convention légère (`[unité]`, `min..max`)
dans `parsing/comments.py`, la stocker dans le modèle, et l'exploiter :
unités affichées dans les IHM, bornes vérifiées par `expect(...).in_range()`
et par un avertissement quand un script écrit hors plage.

#### B9. Autotest : couverture et fuzzing borné · P3 · M

**Proposition.** Rapport des variables lues et écrites par la suite de
scénarios, pour repérer les interfaces jamais testées. Générateur d'entrées
aléatoires dans les bornes de B8, avec invariants vérifiés à chaque cycle.

---

### Axe C : observation et outillage

#### C1. Filtrage des types · P1 · S

**Problème.** Sur un header réel (et ce qu'il inclut), des centaines de types
apparaissent. Les IHM, `scry dump` et le code généré deviennent illisibles.

**Proposition.** `[introspection] include_types` / `exclude_types` : motifs sur
le nom qualifié, appliqués après parsing dans `Introspector.parse`, donc
partagés par toutes les commandes. Dans l'IHM, filtre par namespace
mémorisé dans `scry.ini`. Même syntaxe que `[pybind] expose`.

#### C2. Édition des valeurs dans les IHM · P2 · S

**Proposition.** `ImGui::InputScalar` sur les feuilles lisibles quand la source
est inscriptible (instance locale, et mémoire partagée si l'on ajoute un
canal de commande). Confirmation explicite : écrire dans un processus vivant
n'est pas anodin. En mémoire partagée, un segment « commandes » écrit par
l'IHM et appliqué par le producteur entre deux cycles, pour respecter le
seqlock à un seul écrivain.

#### C3. Courbes live · P2 · M

**Proposition.** Clic droit sur une valeur, « tracer » : historique glissant
dans le visualiseur natif (ImPlot) et l'IHM Python. Avec B7, tracé d'un vol
enregistré.

#### C4. Points de surveillance · P2 · S

**Proposition.** `scry watch --when "obj.phase == Descent and obj.alt < 500"` :
alerte, capture des octets, ou arrêt de l'enregistrement. Les expressions
s'évaluent sur les valeurs décodées.

#### C5. Transport réseau · P3 · M

**Problème.** La mémoire partagée impose la même machine.

**Proposition.** Même en-tête et même charge que `scry_shm.h`, envoyés en UDP ;
un `UdpSource` côté lecteurs. La séquence du seqlock devient un numéro de
paquet. Utile pour observer un simulateur depuis un autre poste.

#### C6. Conseiller de layout · P3 · S

**Proposition.** `scry dump --advise` : pour chaque struct, l'ordre des membres
qui minimise le padding et les octets récupérables. Informatif (on ne modifie
pas un header tiers), utile pour ses propres interfaces.

---

### Axe D : modèle et parsing

#### D1. Instanciations de templates déclarées dans la config · P2 · S

**Problème.** Un template n'existe dans l'AST que s'il est instancié. Un
`RingBuffer<Sample, 64>` utilisé seulement dans un `.cpp` est invisible.

**Proposition.** `[introspection] instantiate = RingBuffer<Sample, 64>; …` :
Scry génère un header temporaire qui inclut les sources et déclare
`template struct …;`, puis le parse en plus.

#### D2. Cibles 32 bits et big-endian · P3 · M

**Problème.** Le décodage Python suppose little-endian (`runtime/memory.py`,
`runtime/shm.py`) et la taille des pointeurs de l'hôte.

**Proposition.** Endianness et taille de pointeur dans la plateforme du modèle
(déjà exportée par `scry json`), utilisées par le décodage. À faire seulement
si une cible embarquée l'exige.

#### D3. Diff d'ABI : renommages et déplacements · P3 · S

**Proposition.** Dans `scry diff`, rapprocher un membre supprimé et un membre
ajouté de même type et même offset (« renommé ? »), et regrouper les décalages
en cascade derrière leur cause (« `drapeaux` inséré, 12 membres décalés de 8 »).

#### D4. Schéma JSON versionné · P3 · S

**Proposition.** Publier le schéma de `scry json` (format `scry-model`,
version 1) pour les outils tiers, et tester sa rétrocompatibilité.

---

### Axe E : adoption et intégration

#### E1. Cache de parsing par défaut, mesuré · P1 · S

**Constat.** 9,3 s à froid contre 0,49 s avec le cache, sur un header qui tire
la STL. Le cache existe (`[paths] cache`) mais son gain n'est ni documenté ni
garanti par défaut.

**Proposition.** Cache activé par défaut, clé qui inclut déjà compilateur,
options et `INCLUDE` ; `scry cache --clear` ; temps affichés en `-v`. Avec
C1, les deux leviers qui rendent Scry utilisable sur un gros projet.

#### E2. Bindings découpés en plusieurs unités de compilation · P2 · M

**Constat.** ~20 s de compilation pour le module d'un seul header ; sur un
vrai projet, un header monolithique devient le goulot du build.

**Proposition.** Un `register_types_<namespace>.cpp` par namespace, compilables
en parallèle, et un fichier de registre ; régénération incrémentale (ne
réécrire un fichier que si son contenu change, pour ne pas relancer la
compilation).

#### E3. Paquet installable · P2 · S

**Proposition.** Wheel publiée (index interne), `castxml` en dépendance pip
(c'est ce qui a été utilisé en CI Linux), extra `[pybind]`. Supprime la
moitié de la section installation.

#### E4. Intégration CMake de première classe · P2 · M

**Proposition.** Un module `ScryConfig.cmake` : `scry_generate(TARGET app
HEADERS … PYBIND ON)` ajoute la génération comme étape de build dépendante des
headers, les `static_assert` à la cible, et le module embarqué en option. Plus
besoin de lancer `scry gen` à la main.

---

### Axe F : dette technique

#### F1. Nettoyage · P1 · S

- supprimer `SharedMemorySource` de `runtime/memory.py`, remplacé par
  `runtime/shm.py` ;
- corriger le lint restant (`E741` dans `codegen/pybind.py`, imports
  inutiles dans `autotest/`) et ajouter `autotest/` au périmètre de `ruff` ;
- réécrire la section 9 du README pour renvoyer à ce document.

#### F2. Découpage des gros modules · P3 · M

`parsing/introspect.py` (878 lignes) mêle lecture, racines, variables,
héritage et constructibilité ; `codegen/pybind.py` (846 lignes) mêle noms,
découverte, membres et stub. Les découper suivant ces lignes, sans changer
leur API, quand une des pistes B1, B2 ou D1 les touchera.

---

## 6. Feuille de route proposée

| Phase | Contenu | Durée indicative |
|---|---|---|
| **1. Fiabiliser** | A1, A2, F1, E1, C1 | 2 semaines |
| **2. Piloter un simulateur** | B1, B2, B3, B5, B6 | 3 semaines |
| **3. Exploiter les séances** | B7, B8, C2, C3, C4, E2, E4 | 4 à 6 semaines |
| **4. Opportuniste** | A3, A4, A5, B4, B9, C5, C6, D1 à D4, E3, F2 | au fil des besoins |

La phase 1 conditionne le reste : sans CI Windows, chaque nouvelle fonction
ajoute du risque non mesuré sur la cible réelle.

---

## 7. Idées écartées

| Idée | Pourquoi non |
|---|---|
| Module Python autonome qui lit l'application par IPC | contraire au besoin : copies et latence ; le Python embarqué couvre l'usage, la mémoire partagée couvre l'observation |
| Réflexion par macros dans les headers | Scry existe précisément pour ne pas toucher aux headers |
| Reconstruire des objets polymorphes par `memcpy` | la vtable serait celle d'un autre processus ; la lecture par offset reste la bonne voie |
| Remplacer castxml par libclang directement | castxml reproduit déjà les règles MSVC ; coût élevé pour un gain incertain |

---

## 8. Annexe : mesures

| Mesure | Valeur | Conditions |
|---|---|---|
| Parsing à froid | 9,3 s | `test_structs_complexe.h`, castxml 0.4.5, sans cache |
| Parsing avec cache | 0,49 s | même header, cache pygccxml |
| Parsing petit header | 0,97 s | `test_structs_simple.h`, sans cache |
| Code généré | 735 lignes (ImGui), 743 lignes (pybind) | `test_structs_complexe.h` |
| Compilation d'un module pybind | ~20 s | g++ -O1, un header |
| Accès Python | 60 à 420 ns ; ~4 µs par cycle type | g++ -O2, Python 3.11 |
| Tests | 266 | Linux, castxml, g++, Dear ImGui, libpython |
