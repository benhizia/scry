#!/usr/bin/env bash
# =============================================================================
#  Demo d'autotest Python embarque, sous Linux ou macOS.
#
#    autotest/run_demo.sh            tous les scenarios de demo/scenarios
#    autotest/run_demo.sh montee     seulement ceux dont le nom ou un tag
#                                    contient 'montee'
#
#  1. scry gen --pybind sur legacy_app.h : types et variables globales ;
#  2. cmake construit legacy_app avec l'interpreteur Python embarque ;
#  3. lance l'appli : a chaque cycle, apres le metier, les scenarios avancent.
#
#  Code de sortie : 0 tout passe, 1 echec de scenario (test_echec_volontaire.py
#  echoue expres), 2 erreur de l'autotest lui-meme.
#  Prerequis : castxml, cmake, un compilateur C++17, et dans le Python courant
#  scry, pybind11 et numpy (pip install -e ".[dev]" numpy).
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/demo/build"
PYTHON="${PYTHON:-python3}"

echo "[autotest] 1/3 scry gen --pybind"
# legacy_app.h inclut Data/test_structs_complexe.h : -I pour castxml. Un
# header en echec arrete tout plutot que de generer un module incomplet.
SCRY_PATHS_OUTPUT="$BUILD/generated" SCRY_PATHS_CACHE= \
SCRY_CASTXML_INCLUDE_PATHS="$HERE/../Data" SCRY_INTROSPECTION_STOP_ON_ERROR=true \
    "$PYTHON" -m scry gen --pybind \
    -H "$HERE/demo/legacy_app.h" -H "$HERE/../Data/test_structs_complexe.h"

echo "[autotest] 2/3 cmake"
mkdir -p "$BUILD"
cmake -S "$HERE/demo" -B "$BUILD" -DLEGACY_AUTOTEST=ON -DCMAKE_BUILD_TYPE=Release \
      -DSCRY_GENERATED_DIR="$BUILD/generated" -DPython_EXECUTABLE="$(command -v "$PYTHON")" \
      > "$BUILD/cmake-configure.log" || { cat "$BUILD/cmake-configure.log"; exit 1; }
cmake --build "$BUILD" -j

echo "[autotest] 3/3 legacy_app $*"
cd "$BUILD"
set +e
./legacy_app "$@"
rc=$?
echo "[autotest] code de sortie $rc (0 tout passe, 1 echec de scenario, 2 erreur autotest)"
exit $rc
