# Consignes pour Claude Code

- État du projet et travail restant : `docs/PASSATION.md`. À lire en premier.
- Deux produits dans ce dépôt :
  - **Scry** (`src/scry`, Python) : outil de build qui lit les headers C++
    (castxml + pygccxml) et génère du code (Jinja) ;
  - **RAVEN** (`raven/`, C++17) : acquisition, enregistrement et
    visualisation temps réel. Tout ce qui tourne à l'exécution est en C++ ;
    pas de Python dans `raven.exe`.
- Langue : français partout (doc, commentaires, messages de commit, messages
  à l'utilisateur). Les commentaires du code C++ et Python sont sans accents,
  comme le code existant.
- Tests :
  - Scry : `pytest` (certains tests ont besoin de castxml et d'un compilateur,
    et sont sautés sinon) ;
  - RAVEN : `cmake -S raven -B build/raven && cmake --build build/raven`, puis
    `ctest --test-dir build/raven`, et `pytest tests/test_raven_e2e.py`.
    Sous Windows, ajouter `-G "Visual Studio 17 2022" -A x64` et
    `-DPython3_EXECUTABLE=<racine>/.venv/Scripts/python.exe` : CMake fait
    appeler `scry raven`, et l'interpréteur système n'a ni pygccxml ni castxml.
    `--config Release` sur le build et `-C Release` sur ctest.
- RAVEN est construit par plugins : une source (`ISource`, déclarée dans
  `raven/src/engine/sources.cpp`) ne fait que le transport ; le moteur
  (`Engine`) ne sait pas d'où viennent les trames. Garder cette séparation.
- Pas de `pkill -f` avec un motif qui apparaît dans la commande elle-même :
  il tue le shell qui l'exécute.
- `scry raven --type` est pris par le filtrage des types : pour une struct
  comme canal, c'est `--struct`.
- Travailler sur une branche, puis PR vers `main`. **Partir de `main`** : c'est
  la seule branche du dépôt, tout y est fusionné. La branche `raven`, qui
  servait d'atelier long, a été supprimée le 1er octobre 2026 — son contenu est
  dans `main` (PR 5 à 8).
