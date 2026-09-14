# =============================================================================
#  Demo : application legacy sequencee avec etape autotest Python embarquee.
#
#  cmake -S autotest/demo -B build -DLEGACY_AUTOTEST=ON
#        -DSCRY_GENERATED_DIR=<sortie de scry gen --pybind>
#        -DPython_EXECUTABLE=<python du venv>
#  cmake --build build --config Release
#
#  Release : le modele Scry decrit un build /MD. En Debug (/MDd), la STL change
#  de taille et les static_assert d'ABI des bindings refusent de compiler,
#  sauf a regenerer avec [castxml] cl_flags = /MDd.
# =============================================================================
cmake_minimum_required(VERSION 3.20)
project(legacy_demo LANGUAGES CXX)

option(LEGACY_AUTOTEST "Etape autotest : interpreteur Python embarque" ON)
set(SCRY_GENERATED_DIR "" CACHE PATH "Dossier des fichiers de scry gen --pybind")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(DEMO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../..")

add_executable(legacy_app legacy_app.cpp)
target_include_directories(legacy_app PRIVATE "${DEMO_ROOT}/Data" "${CMAKE_CURRENT_SOURCE_DIR}")
if(MSVC)
    target_compile_options(legacy_app PRIVATE /utf-8 /W3)
endif()

if(LEGACY_AUTOTEST)
    if(NOT SCRY_GENERATED_DIR)
        message(FATAL_ERROR "SCRY_GENERATED_DIR : lancer 'scry gen --pybind' et passer son dossier de sortie")
    endif()

    # pybind11 installe dans le venv : il donne lui-meme son dossier CMake.
    execute_process(COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
                    OUTPUT_VARIABLE pybind11_DIR OUTPUT_STRIP_TRAILING_WHITESPACE)
    # Module FindPython moderne de CMake plutot que l'ancien FindPythonLibsNew.
    set(PYBIND11_FINDPYTHON ON)
    find_package(pybind11 CONFIG REQUIRED)

    # Fragment genere par Scry : includes des headers sources et du dossier genere.
    include("${SCRY_GENERATED_DIR}/scry_pybind.cmake")

    target_sources(legacy_app PRIVATE autotest_glue.cpp)
    target_link_libraries(legacy_app PRIVATE pybind11::embed)
    scry_pybind_setup(legacy_app)
    target_include_directories(legacy_app PRIVATE "${DEMO_ROOT}/autotest/cpp")
    target_compile_definitions(legacy_app PRIVATE
        LEGACY_AUTOTEST=1
        AUTOTEST_PYTHON_DIR="${DEMO_ROOT}/autotest/python"
        AUTOTEST_SCENARIOS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/scenarios")
else()
    target_compile_definitions(legacy_app PRIVATE LEGACY_AUTOTEST=0)
endif()
