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
même préparation, lance pytest et laisse lui aussi la console ouverte. Le
détail du déploiement est en commentaire en tête des deux scripts.

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
scry gen                 écrit generated/introspection.generated.h
scry json modele.json    exporte le modèle brut
scry ui                  visualiseur ImGui
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
- configuration centralisée, aucun chemin en dur dans le code.

Le C++ généré a été compilé avec `-std=c++17 -Wall -Wextra` : il compile sans
avertissement et les `static_assert` passent contre le layout réel du
compilateur.

Non fait à ce stade : la lecture live réelle depuis une mémoire partagée
alimentée par un producteur C++, l'édition des valeurs, le filtrage des
namespaces, et la comparaison d'ABI entre deux versions d'un header.

---

## 4. Structure

```
pyproject.toml              métadonnées, dépendances, point d'entrée
scry.ini.example            modèle de paramétrage, à copier en scry.ini
scry_console.bat            console prête à l'emploi, déploie le venv au besoin
scry_tests.bat              même préparation, puis pytest
scry.ini                    paramétrage local, non versionné
README.md
DEVELOPPEMENT.md            environnement Python, packaging, publication
Data/                       headers d'essai
Generated/                  sortie, non versionnée
tests/                      tests du modèle, sans castxml ni MSVC
src/
  scry/
    __init__.py
    __main__.py             python -m scry
    cli.py                  point d'entrée console
    config.py               chargement de scry.ini, surcharges par variables d'env
    model.py                modèle intermédiaire : Struct, Field. Zéro dépendance.
    parsing/
      introspect.py         pygccxml -> modèle. Seul module qui importe pygccxml.
      msvc_env.py           détection de Visual Studio, chargement de vcvars
    codegen/
      generator.py          contexte Jinja et écriture du header généré
      templates/
        introspection.h.j2  template du C++ d'introspection
    runtime/
      memory.py             décodage de valeurs depuis un buffer ou une SHM
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

**`pygccxml` 2.x a renommé `variable_t.type` en `decl_type`.** Beaucoup
d'exemples en ligne utilisent encore l'ancienne API.

### Piège castxml

castxml embarque un clang. Un castxml ancien face à des en-têtes MSVC récents
produit des erreurs de parsing dans `<type_traits>` ou `<xstring>`, avec des
messages qui ne ressemblent pas à un problème de configuration. Deux sorties :
mettre castxml à jour, ou épingler un toolset MSVC plus ancien via
`[castxml] toolset`.

---

## 7. Ce que génère le template, et pourquoi

**Des `static_assert` sur `sizeof` et `offsetof`.** Le modèle vient de castxml,
le binaire vient du compilateur cible. Si les deux ABI divergent, packing,
architecture ou version de toolset, la compilation casse au lieu de produire un
visualiseur qui lit à côté. C'est le point le plus important du projet : sans
ces assertions, un visualiseur mémoire se trompe silencieusement, et le
diagnostic coûte des heures.

`offsetof` n'est fiable que sur les membres de premier niveau, non statiques et
hors champs de bits. Les assertions ne sont émises que pour ceux-là.

**Des fonctions de rendu qui lisent par offset depuis un `const uint8_t*`.**
Elles ne nomment jamais le type réel, donc elles fonctionnent indifféremment sur
une instance locale, un bloc de mémoire partagée ou un buffer réseau. Chaque
niveau d'imbrication introduit une base locale et des offsets relatifs.

La lecture passe par `memcpy` dans une variable locale plutôt que par un
`reinterpret_cast` déréférencé : un bloc reçu d'une SHM n'offre aucune garantie
d'alignement, et le cast direct est un comportement indéfini sur les
architectures qui l'exigent.

---

## 8. Améliorations recommandées

Par ordre de rapport valeur sur effort.

### Priorité haute

**Boucler la démonstration live.** Écrire un petit producteur C++ qui publie une
instance dans une mémoire partagée nommée, et brancher `SharedMemorySource`
dessus. C'est la démonstration qui rend le projet convaincant, et toute
l'infrastructure est déjà là. Point d'attention : la synchronisation. Une
lecture pendant une écriture donne un état déchiré. Un compteur de séquence pair
ou impair encadrant l'écriture, lu avant et après, suffit à détecter et rejeter
une lecture incohérente sans verrou.

**Filtrage des types.** Sur un header tiers réel, le nombre de déclarations est
vite ingérable. Une UI de sélection par namespace et par motif de nom, dont le
résultat est mémorisé dans la configuration, conditionne l'utilisabilité sur un
cas réel.

**Diff d'ABI.** Le modèle est déjà sérialisable en JSON. Garder le fichier d'une
version de référence et comparer permet de détecter qu'un header tiers a changé
de layout entre deux livraisons. C'est exactement le genre de régression qui
coûte cher et qu'aucun compilateur ne signale quand la bibliothèque est
précompilée. Un `scry diff ref.json` en CI est peu de code pour beaucoup de
valeur.

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

**Héritage.** Le modèle ne descend pas dans les classes de base. Pour un header
tiers utilisant l'héritage, les membres hérités manquent. `class_t.bases` donne
les bases et leur offset ; l'ajout est mécanique mais demande de traiter
l'héritage virtuel, où l'offset n'est pas constant.

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

## 9. Notes pour un agent reprenant le projet

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
