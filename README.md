# Scry

Introspection C++ automatique à partir de headers tiers **non modifiables**.

Scry lit un `.h` fourni par un tiers ou issu d'une bibliothèque précompilée,
en extrait la structure réelle des types avec offsets, tailles et alignements,
puis génère le C++ capable de relire ces mêmes données en mémoire. Aucune macro
à insérer, aucune annotation, aucune modification du header source.

Chaîne technique : **castxml** produit un AST XML à partir du header, en
utilisant la même ABI que le compilateur cible. **pygccxml** expose cet AST en
Python. **Jinja** génère le C++ à partir du modèle extrait.

Objectif à terme : un visualiseur de mémoire live, alimenté par mémoire
partagée ou par le réseau, capable d'afficher l'état interne d'un processus
qu'on n'instrumente pas.

Ce document sert de point d'entrée pour reprendre le projet, humain ou agent.
Pour le fonctionnement de l'environnement Python lui-même, voir
`DEVELOPPEMENT.md`.

---

## 1. Installation et premier lancement

Sous Windows, le plus simple est de double-cliquer `scry_console.bat`. Au
premier lancement il crée `.venv`, installe les dépendances et copie
`scry.ini.example`. Aux lancements suivants il se contente d'activer le venv :
pip n'est relancé que si `pyproject.toml` a changé. La console reste ouverte ;
`aide` y liste les commandes, `tests` lance les tests. `scry_tests.bat` fait la
même préparation, lance pytest et laisse lui aussi la console ouverte.
`scry_viewer.bat` compile le header généré dans un exécutable ImGui natif et le
lance. Il lui faut les sources C++ de Dear ImGui (1.92 minimum) dans
`third_party/imgui`, et rien n'est téléchargé sans demande. Deux façons de les
obtenir :

- les déposer à la main : voir [third_party/README.md](third_party/README.md) ;
- lancer une fois `scry_viewer.bat --fetch-imgui`, qui fait un `git clone`.

S'il manque quoi que ce soit, le visualiseur s'arrête et affiche la marche à
suivre.
Le détail du déploiement est en commentaire en tête de chaque script.

### Les deux IHM

`scry ui`, l'IHM Python, montre ce que Scry a compris des headers. Elle occupe
toute la fenêtre, en trois colonnes à séparateurs déplaçables :

- **Structures** : sizeof et padding de chacune.
- **Membres** : une carte mémoire de sizeof octets, où le padding est hachuré
  en orange, puis un tree-table. L'arbre est dans la première colonne, et les
  trous de padding sont des lignes à leur offset.
- **Inspecteur** : chemin d'accès, offsets absolu et relatif, bits, pas,
  valeurs d'enum, `offsetof` et lecture C++ copiables, octets bruts.

`scry viewer --run` montre ce que le compilateur en fait : les mêmes lignes,
dessinées par les fonctions générées. En mode « motif de démo », les deux IHM
lisent exactement les mêmes octets et doivent afficher les mêmes valeurs.

L'équivalent manuel :

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[ui]"
copy scry.ini.example scry.ini
scry check
```

Les guillemets autour de `".[ui]"` ne sont pas facultatifs hors de PowerShell :
bash et zsh interprètent les crochets comme un motif de nom de fichier.

`scry.ini` n'est pas versionné : il contient des chemins propres au poste. Le
dépôt fournit `scry.ini.example`, à copier puis renseigner — au minimum
`[paths] castxml` si castxml n'est pas dans le `PATH`. Sans aucun `scry.ini`,
Scry démarre sur ses valeurs par défaut et cherche castxml dans le `PATH`.

`pip install -e .` installe le paquet en mode éditable : le code n'est pas
copié, le venv pointe sur `src/scry/`. Toute modification est prise en compte
immédiatement, sans réinstaller.

L'extra `[ui]` ajoute ImGui, GLFW et PyOpenGL. La chaîne d'introspection et la
génération fonctionnent sans, ce qui permet d'utiliser Scry en CI ou sur une
machine sans OpenGL.

---

## 2. Commandes

```
scry check               vérifie Visual Studio, castxml, vcvars
scry dump                affiche l'arbre avec offsets et tailles
scry gen                 écrit Generated/introspection.generated.h et abi_checks.generated.h
scry json modele.json    exporte le modèle, plateforme comprise
scry diff ref.json       compare au modèle de référence, code 1 si l'ABI a changé
scry ui                  visualiseur ImGui
scry verify              compile les assertions ABI (cl, g++ ou clang++), pour chaque profil de build
scry viewer --run        compile et lance le visualiseur C++ natif (ImGui, DirectX 11)
scry producer --run      compile et lance le producteur de démo en mémoire partagée
scry watch               affiche en continu les valeurs publiées dans un canal
scry gen --pybind        ajoute les bindings pybind11 : types, variables globales, module embarqué
```

Options communes : `-H / --header` cible un autre header, `-c / --config` un
autre fichier de configuration.

`python -m scry <commande>` fait exactement la même chose sans dépendre du
script d'entrée, utile si le venv n'est pas activé ou pour un appel depuis un
autre outil.

`scry check` est le chemin de diagnostic à privilégier : il valide toute la
chaîne sans dépendre d'OpenGL ni d'ImGui, donc il isole un problème de
toolchain d'un problème de rendu.

---

## 3. État actuel

Fonctionnel et validé de bout en bout :

- parsing d'un header, extraction des structures de premier niveau ;
- descente récursive dans les types imbriqués, avec offsets absolus et relatifs ;
- gestion des tableaux, tableaux de structures, unions, structs anonymes,
  champs de bits, pointeurs, enums, membres statiques, types incomplets ;
- garde-fou anti-cycle et limite de profondeur ;
- calcul du padding par fusion d'intervalles ;
- visualiseur ImGui arbre + tableau, avec colonne de valeurs décodées ;
- génération d'un header C++ d'introspection, avec assertions d'ABI ;
- CLI sans OpenGL pour le debug et l'intégration en CI ;
- configuration centralisée, aucun chemin en dur dans le code ;
- héritage : chaque base est un nœud à son offset réel, membres hérités en
  enfants, héritage multiple et bases vides compris, bases virtuelles
  signalées ;
- commentaires de documentation des membres et des structures, relus dans le
  header (voir plus bas).

Le C++ généré a été compilé avec `-std=c++17 -Wall -Wextra` : il compile sans
avertissement et les `static_assert` passent contre le layout réel du
compilateur.

Lecture live : un producteur C++ publie dans un canal de mémoire partagée
(protocole seqlock, `scry_shm.h`), et `scry watch`, l'IHM Python et le
visualiseur natif le décodent par offset. Voir § 7 ter.

Comparaison d'ABI entre deux livraisons d'un header : `scry diff`, voir
§ 7 bis.

Non fait à ce stade : l'édition des valeurs et le filtrage des namespaces.

---

## 4. Structure

```
pyproject.toml              métadonnées, dépendances, point d'entrée
scry.ini.example            modèle de paramétrage, à copier en scry.ini
scry_console.bat            console prête à l'emploi, déploie le venv au besoin
scry_tests.bat              même préparation, puis pytest
scry_viewer.bat             même préparation, puis compile et lance le visualiseur C++
third_party/README.md       où déposer les sources de Dear ImGui
third_party/imgui/          Dear ImGui, à la main ou via --fetch-imgui (non versionné)
build/viewer/               scry_viewer.exe et ses objets (non versionné)
autotest/                   autotest Python embarqué, séparé du paquet Scry
  python/autotest/          runtime des scénarios (Runner, cycles, until, expect)
  cpp/autotest_embed.h      interpréteur embarqué, un tick() par cycle
  demo/                     application legacy factice (CMake) et scénarios
  run_demo.bat              génère, construit et lance la démo
scry.ini                    paramétrage local, non versionné
README.md
DEVELOPPEMENT.md            environnement Python, packaging, publication
Data/                       headers d'essai
Data/corpus/                corpus rejoué par tests/test_corpus.py, voir son README
Generated/                  sortie, non versionnée
tests/                      tests du modèle, sans castxml ni MSVC, plus
                            test_corpus.py et test_verify_reel.py qui sautent
                            sans castxml ni g++
src/
  scry/
    __init__.py
    __main__.py             python -m scry
    cli.py                  point d'entrée console
    diff.py                 export JSON avec plateforme, comparaison de modèles
    config.py               chargement de scry.ini, surcharges par variables d'env
    model.py                modèle intermédiaire : Struct, Field. Zéro dépendance.
    parsing/
      introspect.py         pygccxml -> modèle. Seul module qui importe pygccxml.
      msvc_env.py           détection de Visual Studio, chargement de vcvars
      castxml_bases.py      offsets des classes de base, que pygccxml ne lit pas
      comments.py           commentaires de documentation relus dans le source
    codegen/
      generator.py          contexte Jinja et écriture du header généré
      templates/
        introspection.h.j2  template du C++ d'introspection
    producer.py             producteur de démo en mémoire partagée : génération, compilation
    runtime/
      memory.py             décodage de valeurs depuis un buffer ou une SHM
      scry_shm.h            protocole de mémoire partagée, côté C++ (seqlock)
      shm.py                lecteur Python du même protocole
      watch.py              scry watch : les valeurs d'un canal, en console
    ui/
      app.py                boucle ImGui
      tree.py               arbre d'affichage construit depuis le modèle
      render.py             rendu arbre + tableau
```

Le découpage suit les responsabilités. `parsing` est la seule zone qui connaît
pygccxml, `runtime` la seule qui touche à la mémoire, `ui` la seule qui importe
ImGui. Cette frontière est ce qui rend le projet maintenable, et elle est
maintenant visible dans l'arborescence.

### Décision d'architecture centrale

La version initiale promenait des déclarations pygccxml dans toute
l'application. Chaque consommateur devait donc connaître l'API du parseur et en
subir les cas particuliers, ce qui produisait des erreurs du type
`'class_t' object has no attribute 'decl_type'` : le code supposait que tout
membre d'une classe est une donnée, alors qu'une struct imbriquée apparaît dans
la même liste de membres.

Il existe maintenant un **modèle intermédiaire**. `parsing/introspect.py` est le
seul module qui importe pygccxml. Il produit des dataclasses plates, sans
référence au parseur, sérialisables en JSON et testables sans castxml. L'UI, le
générateur Jinja et le futur lecteur SHM consomment tous ce même modèle.

Conséquence pratique pour qui reprend le projet : **toute correction liée au
parsing va dans `parsing/introspect.py`, jamais ailleurs**. Si un autre module a
besoin d'importer pygccxml, c'est le signe que le modèle est incomplet et qu'il
faut l'enrichir plutôt que contourner.

### Héritage

Chaque classe de base publique non vide devient un `Field` de nature `base`,
placé à son offset réel dans la dérivée, ses membres en enfants. Les membres
hérités gardent le chemin de la dérivée (`obj.membre`), comme en C++. Une
base vide est omise (optimisation de base vide : 0 octet). Une base
virtuelle est signalée sans être placée, son offset n'étant pas constant.
Une base polymorphe affiche son `vptr` à son propre offset 0.

Le header ABI vérifie aussi `offsetof(Dérivée, membre_hérité)` pour les
membres publics des bases publiques non virtuelles, ce qui valide l'offset de
chaque base contre le compilateur. Un nom masqué ou hérité deux fois est
écarté comme ambigu. `[codegen] abi_inherited = false` retire ces assertions,
par exemple si un compilateur les refusait.

`[introspection] include_bases = false` revient à l'ancien comportement.

### Invariant qui prépare la suite

Chaque `Field` porte à la fois :

- `offset`, relatif au parent immédiat ;
- `abs_offset`, absolu depuis le début de la structure racine.

Le premier sert au code C++ généré, qui utilise des pointeurs de base locaux et
peut ainsi boucler sur un tableau de structures avec un simple stride. Le
second sert à l'UI et au futur lecteur mémoire, qui n'ont besoin que d'un
pointeur de base et d'un offset.

### Ressources embarquées

Les templates Jinja voyagent avec le paquet et sont résolus via
`importlib.resources`, jamais par rapport au répertoire courant :

```python
from importlib.resources import files
templates_dir = files("scry.codegen") / "templates"
```

C'est ce qui permet de lancer `scry gen` depuis n'importe quel répertoire, et de
faire fonctionner le paquet une fois installé depuis un wheel. La déclaration
`[tool.setuptools.package-data]` du `pyproject.toml` est ce qui les inclut dans
la distribution ; sans elle, la génération échoue après installation alors
qu'elle marchait en développement.

---

## 5. Configuration

`scry.ini` est copié depuis `scry.ini.example` et renseigné une fois par
poste. Il n'est pas versionné. Toute valeur est surchargeable par
une variable d'environnement `SCRY_<SECTION>_<CLÉ>`, par exemple
`SCRY_CASTXML_TOOLSET=14.38`.

Sections : `[paths]` pour castxml, header, sortie et cache ; `[castxml]` pour
compilateur, toolset, host, architecture, standard, includes et macros ;
`[introspection]` pour profondeur, suivi des pointeurs, membres non publics et
statiques ; `[codegen]` pour le namespace C++ et les assertions ABI.

### Environnement Windows

Deux écueils indépendants, tous deux traités par `parsing/msvc_env.py` :

Un chemin figé vers un toolset MSVC casse à la première mise à jour de Visual
Studio. La détection passe par `vswhere.exe`, dont l'emplacement est stable, puis
lit le toolset par défaut dans `Microsoft.VCToolsVersion.default.txt`.

castxml lance `cl.exe` pour détecter les répertoires d'include, et `cl` a besoin
de `INCLUDE`, `LIB` et `PATH` positionnés. Hors d'une invite développeur, il
échoue avec un laconique `program not executable` même quand le chemin est
correct. `apply_vcvars()` charge l'environnement vcvars dans `os.environ` avant
tout appel.

Vérifier aussi la cohérence d'architecture : Python, le toolset MSVC
(`Hostx64/x64`) et l'application cible doivent être sur la même architecture.

---

## 6. Pièges pygccxml

Tous vérifiés sur du parsing réel, pas de mémoire. Plusieurs sont **silencieux**
et produisent des données fausses sans lever d'exception, ce qui en fait les
plus coûteux.

**`class_t` n'a pas de `decl_type`.** Seuls `variable_t` et `typedef_t` en ont.
Une struct imbriquée est listée parmi les membres au même titre qu'un champ.

**`variables()` est récursif par défaut.** Il remonte les membres des types
imbriqués mélangés à ceux du parent, sans marqueur de provenance. Toujours
`recursive=False`. Silencieux : on obtient une liste plausible mais fausse.

**`byte_offset` et `byte_size` sont des flottants.** Pour un champ de bits,
l'offset est fractionnaire : `392.125` signifie octet 392, bit 1. Un `int()`
naïf perd l'information de position binaire.

**`remove_alias()` reconstruit le type et perd `byte_size`.** Un `pointer_t` qui
annonçait 8 octets en annonce 0 après résolution. Lire la taille sur le type
d'origine, et ne se rabattre sur le type résolu qu'en secours. Silencieux.

**Une struct ou union anonyme a un `name` vide et un `decl_string` égal au nom
de la classe englobante.** Deux conséquences : le type affiché est faux si on se
fie à la chaîne, et un garde-fou anti-cycle basé sur `decl_string` coupe la
descente à tort. Passer par la déclaration et donner une clé d'identité
distincte aux types anonymes.

**Les membres statiques ont un `byte_offset` de 0.0** qui ne signifie rien.
Filtrer sur `type_qualifiers.has_static`.

**`classes(header_file=...)` est récursif** et remonte aussi les types imbriqués
et anonymes. Pour obtenir les racines, filtrer sur
`isinstance(cls.parent, namespace_t)`.

**Le filtre `header_file` compare des chaînes.** Sur Windows, casse et
séparateurs diffèrent, ce qui donne une liste vide sans erreur. Comparer des
`os.path.normcase(os.path.abspath(...))`.

**Un type incomplet**, pointé mais jamais défini, donne un `class_declaration_t`
sans `byte_size`.

**Les templates n'existent dans l'AST que s'ils sont instanciés.** Une
instanciation explicite dans le header d'essai les rend visibles.

**Les structures auto-référençantes bouclent** sans garde-fou.

**`cls.bases` ne donne ni l'offset des bases ni leur caractère virtuel.**
`is_virtual` vaut toujours `False`. castxml écrit pourtant ces informations dans
des éléments `<Base type=… virtual=… offset=…>`, que pygccxml ne lit pas.
`parsing/castxml_bases.py` enveloppe le scanner SAX de pygccxml pour les
recueillir. Silencieux : sans cela, les membres hérités seraient mal placés.

**`declarations.is_class()` répond vrai sur un pointeur vers une classe.**
Tester `is_pointer()` d'abord.

**Un destructeur virtuel n'est pas un `member_function_t`.** Chercher les
méthodes virtuelles parmi les seuls `member_function_t` rate les types dont
seul le destructeur est virtuel, cas courant. Tester `calldef_t`.

**`pygccxml` 2.x a renommé `variable_t.type` en `decl_type`.** Beaucoup
d'exemples en ligne utilisent encore l'ancienne API.

### Commentaires de documentation

Chaque `Struct` et chaque `Field` porte un `doc`, affiché par `scry dump`,
l'inspecteur, l'infobulle du tree-table, l'export JSON et, en infobulle
aussi, le visualiseur C++ natif.

castxml sait rapporter les commentaires, mais seulement les commentaires
Doxygen attachés par clang (`///`, `///<`, `/** */`), et un seul par
déclaration : un `///` placé avant un membre qui porte aussi un `///<` est
perdu. Les headers tiers documentent surtout avec de simples `//`. Scry relit
donc le source à la ligne que castxml donne pour chaque déclaration
(`parsing/comments.py`, sans pygccxml, testé sur des chaînes) :

- le bloc de commentaires collé au-dessus, sans ligne vide, en `//` ou
  `/* */` ;
- le commentaire de fin de ligne, même poursuivi sur plusieurs lignes.

Les deux sont concaténés. Un `//` dans une chaîne d'initialisation n'ouvre pas
de commentaire, et un `///<` seul sur sa ligne n'est pas attribué au membre
suivant. `[introspection] comments = false` désactive la lecture.

Approche reprise d'InterfaceInspector, qui passait par Doxygen après avoir
réécrit les commentaires du header dans une copie temporaire. Ici ni Doxygen ni
réécriture : la position donnée par castxml suffit.

### Piège castxml

castxml embarque un clang. Un castxml ancien face à des en-têtes MSVC récents
produit des erreurs de parsing dans `<type_traits>` ou `<xstring>`, avec des
messages qui ne ressemblent pas à un problème de configuration. Deux sorties :
mettre castxml à jour, ou épingler un toolset MSVC plus ancien via
`[castxml] toolset`.

---

## 7. Ce que génère le template, et pourquoi

`scry gen` écrit deux headers dans `Generated/`.

**`abi_checks.generated.h` : des `static_assert` sur `sizeof`, `alignof` et
`offsetof`.** Il n'a aucune dépendance et ne contient aucun code : il est fait
pour être inclus dans le build de l'application cible, dans chaque
configuration. Le modèle vient de castxml, le binaire vient du compilateur
cible ; si les deux divergent, la compilation casse au lieu de produire un
visualiseur qui lit à côté. Sans ces assertions, un visualiseur mémoire se
trompe silencieusement, et le diagnostic coûte des heures.

`offsetof` n'est fiable que sur les membres de premier niveau, non statiques et
hors champs de bits. Les assertions ne sont émises que pour ceux-là.

### Qui calcule le layout, et ce qui le fait varier

Les offsets ne viennent pas de `cl.exe` mais de clang, dans castxml : son
`MicrosoftRecordLayoutBuilder` réimplémente les règles MSVC, bizarreries
comprises, parce que clang-cl doit être compatible binaire avec MSVC. `cl`
n'intervient que pour fournir ses macros prédéfinies et ses chemins d'include.
Ce sont des constantes de compilation : le runtime n'apporterait rien de plus
juste.

Le layout dépend donc de ce que voit le préprocesseur, pas de l'optimisation :

| Facteur | Effet |
|---|---|
| `/O2`, `/Od`, `/GS`, `/RTC`, garde du tas debug | aucun sur `sizeof` et `offsetof` |
| `/MDd`, donc `_ITERATOR_DEBUG_LEVEL=2` | `vector` 24 → 32, `string` 32 → 40, `map` 16 → 24 |
| `#pragma pack` dans le header parsé | pris en compte, clang le lit |
| `/Zp`, `pack` non refermé par un header inclus avant | invisible pour castxml |
| macros du projet qui conditionnent des membres | à reporter dans `[castxml] defines` |
| architecture | `[castxml] arch` |

`[castxml] cl_flags` transmet à `cl` les options de la configuration visée,
`/MDd` par exemple, pour que castxml voie les mêmes macros. `scry verify`
compile ensuite `abi_checks.generated.h` avec le vrai `cl`, pour chaque profil
de `[verify] profiles`, et dit pour quelles configurations le modèle tient.

Hors Windows, avec `[castxml] compiler = gcc` ou `clang`, `scry verify` passe
par `g++` ou `clang++` en `-fsyntax-only` (`[verify] cxx` pour en forcer un),
avec les profils de `[verify] gnu_profiles`. Le pendant de `/MDd` y est
`-D_GLIBCXX_DEBUG`, qui grossit les conteneurs de libstdc++ exactement de la
même façon : le profil `debug` par défaut échoue tant que castxml n'a pas vu
la macro (`[castxml] extra_cflags`). C'est ce qui rend la vérification d'ABI
possible en CI Linux, avec `pip install castxml`.

| Profil gnu par défaut | Options | Effet sur le layout |
|---|---|---|
| `release` | `-O2` | aucun |
| `debug` | `-D_GLIBCXX_DEBUG` | `vector`, `string`, `map`, `optional`… grossissent |

**`introspection.generated.h` : le rendu ImGui.** Il inclut le header ABI.

**Des fonctions de rendu qui lisent par offset depuis un `const uint8_t*`.**
Elles ne nomment jamais le type réel, donc elles fonctionnent indifféremment sur
une instance locale, un bloc de mémoire partagée ou un buffer réseau. Chaque
niveau d'imbrication introduit une base locale et des offsets relatifs.

La lecture passe par `memcpy` dans une variable locale plutôt que par un
`reinterpret_cast` déréférencé : un bloc reçu d'une SHM n'offre aucune garantie
d'alignement, et le cast direct est un comportement indéfini sur les
architectures qui l'exigent.

---

## 7 bis. Diff d'ABI entre deux livraisons d'un header

Une bibliothèque précompilée livre une nouvelle version de son header : si un
layout a changé, tout lecteur par offset lit à côté, et aucun compilateur ne
le signale. On garde l'export d'une version de référence et on compare :

```
scry json ref.json            une fois, sur la livraison de référence
scry diff ref.json            à chaque livraison : parse les headers courants
scry diff ref.json new.json   ou compare deux exports
```

L'export porte la plateforme qui l'a produit (compilateur, toolset,
architecture, standard, `cl_flags`, macros) : `scry diff` prévient quand les
deux modèles ne viennent pas de la même cible, les écarts pouvant alors venir
d'elle et non du header. L'ancien format, une simple liste de structures, est
encore lu.

Code de retour 1 quand un changement fait lire à côté un lecteur de
l'ancienne version : structure ou membre supprimé, `sizeof`, `alignof`,
offset, taille, type ou bits d'un membre modifiés. Un simple ajout, structure
nouvelle ou membre logé dans un trou de padding, est affiché sans échec, sauf
avec `--strict`. Les membres sont appariés par chemin d'accès (`obj.a.b`).

---

## 7 ter. Lecture live en mémoire partagée

```
scry producer --run                        terminal 1 : publie
scry watch                                 terminal 2 : affiche en continu
scry ui          puis « mémoire partagée »  ou l'IHM Python
scry viewer --run   puis « mémoire partagée »  ou le visualiseur natif (--shm)
```

**Le protocole** est dans `src/scry/runtime/scry_shm.h`, header C++17
autonome, Windows et POSIX, copié dans `Generated/` à côté des headers
générés. Un segment nommé contient un en-tête de 128 octets (magic `SCRY`,
version, taille de la charge, compteur de séquence, horodatage, nom du type)
suivi des octets bruts d'une instance. Le nom du type publié permet au lecteur
de choisir la bonne structure, et sa taille de refuser un layout différent.

**Seqlock.** L'écrivain rend la séquence impaire, copie, la rend paire. Le
lecteur lit la séquence, copie, relit : impaire ou changée, la copie est
déchirée et il recommence. Aucun verrou, l'écrivain n'attend jamais. Vérifié
sous charge : producteur publiant sans pause, 300 lectures Python, aucune
copie déchirée (`tests/test_shm.py`) ; même essai du chemin Win32, compilé
avec mingw et exécuté sous wine.

**Le producteur de démonstration** (`scry producer`) est généré depuis le
modèle et inclut le header ABI : s'il compile, la charge a le layout annoncé.
Il publie le motif de démo décalé à chaque tick, `(i * 7 + 3 + tick) % 251` :
au tick 0, ce sont les octets du « motif de démo » des deux IHM. Une vraie
application publie ses objets en deux lignes :

```cpp
#include "scry_shm.h"
scry::shm::Publisher pub("scry_moteur", sizeof(Etat), "moteur::Etat");
pub.publish(etat);   // à chaque mise à jour
```

**Lecteurs.** `scry.runtime.shm.ShmChannelSource` est une `MemorySource` :
`refresh()` prend un instantané cohérent, `read()` lit toujours dans le
dernier, pour que tous les membres affichés viennent de la même publication.
Sous POSIX il ouvre le segment en lecture seule par `shm_open` et `mmap`, sans
`multiprocessing.shared_memory` : avant Python 3.13, son `resource_tracker`
détruit à la sortie du lecteur tout segment ouvert, sous les pieds du
producteur. Le visualiseur natif utilise `scry::shm::Reader`, et retente la
connexion deux fois par seconde si le producteur démarre après lui.

Rappel : les octets publiés sont ceux de l'objet, pointeurs et vtable
compris. Ils n'ont de sens que dans le processus producteur ; la lecture par
offset reste valide, pas le déréférencement.

---

## 8. Python embarqué : bindings pybind11 générés

Cas visé : une application C++ (un simulateur par exemple) embarque un
interpréteur Python, et des scripts lisent et modifient ses interfaces **dans
son propre cycle**, sans IPC ni copie. Tout le code de liaison est généré par
Scry depuis les headers, sans les modifier :

```
scry gen --pybind -H app/interfaces.h
```

| Fichier généré | Rôle |
|---|---|
| `scry_pybind.generated.h` | `register_types` (tous les types), `register_globals` (toutes les variables globales), `register_all` |
| `scry_module.generated.cpp` | le module embarqué complet : `PYBIND11_EMBEDDED_MODULE(sut, m) { register_all(m); }` |
| `sut.pyi` | stub pour l'autocomplétion, variables comprises |
| `scry_pybind.cmake` | `scry_pybind_embed(mon_app)` : includes, module, `pybind11::embed` |

Côté application, il ne reste qu'à démarrer l'interpréteur et appeler un
script à chaque cycle (voir [autotest/](autotest/README.md) pour un hôte
complet, `autotest_embed.h`) :

```cpp
extern Etat g_etat;               // dans interfaces.h, défini par l'appli
py::scoped_interpreter python;    // une fois
py::object step = py::module_::import("script").attr("step");
for (;;) { simulation(); step(); }
```

```python
import sut
etat = sut.sim.g_etat          # vue typée sur sim::g_etat : aucune copie
def step():
    etat.moteur.regime += 10   # écrit dans la mémoire C++
    sut.sim.g_temps            # scalaire global : relu à chaque accès
```

**Ce que Python voit.** Une variable globale devient une propriété du module
de son namespace (`sim::g_etat` → `sut.sim.g_etat`). Une structure est une vue
par référence, un scalaire ou une enum se lit et s'écrit en place. Un tableau
numérique est une vue numpy sans copie, un tableau de structures une séquence
d'éléments par référence, un `char[N]` une `str` dont la longueur est vérifiée.
Un pointeur vers une structure décrite donne une vue typée sur l'objet pointé,
ou `None`. Une variable `const` est en lecture seule. Écrire un nom inconnu
lève `AttributeError` : une faute de frappe ne crée pas un attribut qui
n'écrit nulle part. Les variables `static` d'un header ne sont jamais
exposées, car chaque unité de compilation en a sa propre copie.
`[pybind] expose` et `hide` filtrent par motif sur le nom qualifié.

Les membres hérités s'atteignent depuis la classe dérivée, comme en C++. Les
membres non publics ne sont jamais nommés par les bindings, car le code ne
compilerait pas : ils restent lisibles par offset (`scry watch`, IHM). Les
commentaires du header deviennent des docstrings : `help(sut.app.g_sensor)`
les affiche. Un type à destructeur privé (singleton) est exposé en vue, sans
constructeur Python.

**Coût, mesuré** (g++ -O2, Python 3.11, un cœur de serveur ; ordres de
grandeur) :

| Accès | Coût |
|---|---|
| élément d'une vue numpy (`v[1] = 2.0`) | ~60 ns |
| lecture d'une globale scalaire (`sut.sim.g_temps`) | ~110 ns |
| membre d'une vue gardée (`etat.mode = 1`) | ~220 ns |
| chemin complet (`sut.sim.g_etat.mode = 1`) | ~360 ns |
| écriture d'une globale scalaire | ~420 ns |
| un cycle type : 5 lectures, 5 écritures, un pointeur suivi | ~4 µs |

Dans une boucle de 20 ms, c'est négligeable. Pour les scripts chauds, garder
les vues dans des variables (`etat = sut.sim.g_etat`) plutôt que de refaire
le chemin à chaque cycle.

**Garde-fous.** Le header généré inclut les `static_assert` d'ABI : il ne
compile que si le layout du modèle est celui du compilateur. Le modèle porte
aussi les types qualifiés, les vraies valeurs des enums et une empreinte de
layout (`layout_hash`, FNV-1a 64 bits), identique en C++, en Python et dans le
JSON.

**Tests.** `tests/test_pybind_embed.py` compile un hôte C++ qui embarque
Python et le module généré (`tests/cpp/pybind_host.cpp`). Il exécute des
scripts, puis relit les octets des structures C++ aux offsets du modèle. Il
saute sans castxml, g++ ou libpython.

**Autotest.** Le dossier [autotest/](autotest/README.md) bâtit là-dessus un
runtime de scénarios (`async def`, `await cycles(n)`, `expect(...)`) piloté
par le séquenceur de l'application. `autotest/run_demo.sh` (Linux) ou
`autotest\run_demo.bat` (Windows) construit et lance la démo avec CMake.

---

## 9. Améliorations recommandées

Par ordre de rapport valeur sur effort.

### Priorité haute

**Boucler la démonstration live : fait.** Voir § 7 ter.

**Filtrage des types.** Sur un header tiers réel, le nombre de déclarations est
vite ingérable. Une UI de sélection par namespace et par motif de nom, dont le
résultat est mémorisé dans la configuration, conditionne l'utilisabilité sur un
cas réel.

**Diff d'ABI : fait.** Voir § 7 bis.

**Cache de parsing.** `parser.file_cache_t` est déjà branché via `[paths] cache`
mais mérite d'être mesuré et documenté. castxml est lent sur les gros headers,
et le gain est immédiat sur un cycle de développement.

### Priorité moyenne

**Édition des valeurs.** Passer de `ImGui::Text` à `ImGui::InputScalar` sur un
buffer non const donne un éditeur de mémoire live. Le modèle contient déjà tout
ce qu'il faut : offset, taille, type. Prévoir une confirmation, écrire dans la
mémoire d'un processus en cours n'est pas anodin.

**Sérialisation.** Le même modèle génère aussi bien un writer binaire, un export
JSON, ou un descripteur pour un protocole de télémétrie. Un second template
suffit, sans toucher au parsing.

**Vues typées en complément.** Quand le type est disponible côté visualiseur,
générer aussi des accesseurs typés qui court-circuitent la lecture par offset.
Plus rapide et plus sûr, avec repli sur la lecture par offset pour les cas
opaques.

**Tests sur le modèle.** Le modèle est indépendant de pygccxml, donc testable
sur des fixtures construites à la main, sans castxml. Un jeu de tests sur le
calcul de padding, les champs de bits et les types anonymes protège les cas
limites qui ont demandé le plus d'itérations.

### Priorité basse, ou à valider avant de s'y fier

**Ordre d'allocation des champs de bits.** Le décodage est implémenté et les
offsets viennent de castxml, donc ils suivent l'ABI de la cible. Le standard ne
normalise pas l'ordre d'allocation. Vérifier sur un cas réel avant de s'appuyer
dessus en production.

**Bases virtuelles.** L'héritage est géré (voir § 6), mais une base virtuelle
est seulement signalée : son offset dépend du type le plus dérivé et castxml ne
le donne pas. Pour un objet complet il est pourtant fixe ; on pourrait le
retrouver en compilant `static_cast<VBase*>(&obj)` sur une instance.

**Types polymorphes.** Ils sont détectés et signalés dans l'UI et le C++ généré.
Le pointeur de vtable occupe le début de l'objet, les offsets en tiennent
compte, mais un objet polymorphe ne doit jamais être reconstruit par `memcpy` à
partir d'octets reçus : le pointeur de vtable serait celui du processus
émetteur. La lecture par offset reste valide, la reconstruction non.

**Conteneurs de la bibliothèque standard.** Un `std::vector` ou `std::string`
membre est vu comme une struct opaque avec ses pointeurs internes. Les lire
depuis une SHM n'a aucun sens, les adresses appartiennent à l'autre processus.
Il faudrait des lecteurs spécialisés par conteneur, ou simplement les signaler
comme non lisibles à distance. C'est aujourd'hui une limite non signalée.

---

## 10. Notes pour un agent reprenant le projet

- Toute modification liée au parsing va dans `parsing/introspect.py`. Si un
  autre module a besoin d'importer pygccxml, enrichir le modèle plutôt que
  contourner.
- Ne pas coder de chemin en dur. Tout passe par `config.py` et `scry.ini`.
- Les ressources embarquées se résolvent via `importlib.resources`, jamais par
  rapport au répertoire courant.
- Vérifier les hypothèses sur l'API pygccxml en parsant réellement un header
  d'essai. Plusieurs comportements sont contre-intuitifs et la documentation
  n'est pas exhaustive.
- Après toute modification du template, compiler réellement le C++ généré. Un
  header d'essai plus un stub ImGui minimal suffisent, et les `static_assert`
  valident au passage la cohérence du modèle avec le compilateur.
- Les offsets relatif et absolu ne sont pas interchangeables. Le template
  utilise le relatif avec des bases locales, l'UI et le lecteur mémoire
  utilisent l'absolu. Les confondre produit un affichage correct sur le premier
  élément d'un tableau et faux sur les suivants, ce qui est difficile à repérer.
