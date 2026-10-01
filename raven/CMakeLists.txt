# RAVEN : enregistreur (raven), visualiseur (raven-view), outils et demo.
#
#   cmake -S raven -B build/raven && cmake --build build/raven
#
# La demo a besoin de Scry (Python) pour generer sa glue ; le visualiseur a
# besoin des sources d'ImGui (third_party/imgui du depot Scry par defaut).
cmake_minimum_required(VERSION 3.16)
project(raven CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
  add_compile_options(/W4 /utf-8)
  # fopen, sscanf, localtime : MSVC pousse ses variantes _s, qui n'existent
  # nulle part ailleurs. RAVEN est portable, il garde les fonctions standard.
  add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
else()
  add_compile_options(-Wall -Wextra)
endif()

set(RAVEN_IMGUI_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/imgui" CACHE PATH "sources d'ImGui")
option(RAVEN_VIEW "construire raven-view (ImGui)" ON)
option(RAVEN_DEMO "construire le simulateur de demonstration (Scry requis)" ON)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
find_package(Threads REQUIRED)

# Coeur partage : descripteur, fichiers .rvn, sockets.
add_library(raven_core STATIC
  src/core/descriptor.cpp
  src/core/rvn.cpp
  src/core/net.cpp
  src/core/sockets.cpp
  src/core/ini.cpp)
target_include_directories(raven_core PUBLIC include)
if(WIN32)
  target_link_libraries(raven_core PUBLIC ws2_32)
endif()

# Moteur de l'enregistreur, en bibliotheque pour les tests.
add_library(raven_engine STATIC src/engine/engine.cpp src/engine/sources.cpp
  src/engine/shm_source.cpp src/engine/mcast_source.cpp src/engine/relay_source.cpp)
target_include_directories(raven_engine PUBLIC src/engine)
target_link_libraries(raven_engine PUBLIC raven_core Threads::Threads)
if(UNIX AND NOT APPLE)
  target_link_libraries(raven_engine PUBLIC rt)
endif()

add_executable(raven src/engine/main.cpp)
target_link_libraries(raven PRIVATE raven_engine)

add_executable(raven-cat src/tools/raven_cat.cpp)
target_link_libraries(raven-cat PRIVATE raven_core)

add_executable(raven_tests tests/test_core.cpp)
target_link_libraries(raven_tests PRIVATE raven_engine)
enable_testing()
add_test(NAME raven_tests COMMAND raven_tests)

add_executable(raven_net_tests tests/test_net.cpp)
target_link_libraries(raven_net_tests PRIVATE raven_core Threads::Threads)
add_test(NAME raven_net_tests COMMAND raven_net_tests)

if(RAVEN_VIEW)
  add_subdirectory(src/view)
endif()

if(RAVEN_DEMO)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  set(DEMO_GEN "${CMAKE_CURRENT_BINARY_DIR}/demo_gen")
  add_custom_command(
    OUTPUT "${DEMO_GEN}/raven_publish.gen.h" "${DEMO_GEN}/demo.rvndesc"
    COMMAND ${CMAKE_COMMAND} -E env "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/../src"
            ${Python3_EXECUTABLE} -m scry raven
            -H "${CMAKE_CURRENT_SOURCE_DIR}/demo/sim_state.h"
            --channel g_flight --channel g_sim --name demo -o "${DEMO_GEN}"
    DEPENDS demo/sim_state.h
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
    COMMENT "scry raven : glue de la demo")
  # Ecoute passive multicast : descripteurs des scenarios 03 et 04 de SwitchSpy.
  set(NET_GEN "${CMAKE_CURRENT_BINARY_DIR}/net_gen")
  foreach(pair "03_multicast:TelemetryBroadcast:telemetry" "04_high_throughput:MarketTick:market")
    string(REPLACE ":" ";" parts "${pair}")
    list(GET parts 0 dir)
    list(GET parts 1 type)
    list(GET parts 2 name)
    add_custom_command(
      OUTPUT "${NET_GEN}/${name}.rvndesc"
      COMMAND ${CMAKE_COMMAND} -E env "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/../src"
              ${Python3_EXECUTABLE} -m scry raven
              -H "${CMAKE_CURRENT_SOURCE_DIR}/tests/net/${dir}/shared.hpp"
              --struct ${type} --name ${name} -o "${NET_GEN}"
      DEPENDS tests/net/${dir}/shared.hpp
      WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
      COMMENT "scry raven : descripteur ${name}")
  endforeach()
  # Relais : un type de struct par sens, donc deux canaux par liaison.
  # '+' separe les types : un ';' ferait une liste CMake des le depart, et le
  # decoupage sur ':' ne rendrait plus trois morceaux.
  foreach(trio "01_tcp_simple:SwitchCommand+SwitchAck:switchlink"
               "02_udp_relay:SensorReading+SensorSetpoint:sensors")
    string(REPLACE ":" ";" parts "${trio}")
    list(GET parts 0 dir)
    list(GET parts 1 joined)
    list(GET parts 2 name)
    string(REPLACE "+" ";" types "${joined}")
    set(struct_args "")
    foreach(type ${types})
      list(APPEND struct_args --struct ${type})
    endforeach()
    add_custom_command(
      OUTPUT "${NET_GEN}/${name}.rvndesc"
      COMMAND ${CMAKE_COMMAND} -E env "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/../src"
              ${Python3_EXECUTABLE} -m scry raven
              -H "${CMAKE_CURRENT_SOURCE_DIR}/tests/net/${dir}/shared.hpp"
              ${struct_args} --name ${name} -o "${NET_GEN}"
      DEPENDS tests/net/${dir}/shared.hpp
      WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
      COMMENT "scry raven : descripteur ${name}")
  endforeach()
  add_executable(raven_relay_tests tests/test_relay.cpp
    "${NET_GEN}/switchlink.rvndesc" "${NET_GEN}/sensors.rvndesc")
  target_include_directories(raven_relay_tests PRIVATE tests)
  target_link_libraries(raven_relay_tests PRIVATE raven_engine)
  add_test(NAME raven_relay_tests
           COMMAND raven_relay_tests "${NET_GEN}/switchlink.rvndesc" "${NET_GEN}/sensors.rvndesc")

  add_executable(raven_mcast_tests tests/test_mcast.cpp
    "${NET_GEN}/telemetry.rvndesc" "${NET_GEN}/market.rvndesc")
  target_include_directories(raven_mcast_tests PRIVATE tests)
  target_link_libraries(raven_mcast_tests PRIVATE raven_engine)
  add_test(NAME raven_mcast_tests
           COMMAND raven_mcast_tests "${NET_GEN}/telemetry.rvndesc" "${NET_GEN}/market.rvndesc")

  add_executable(demo_sim demo/demo_sim.cpp "${DEMO_GEN}/raven_publish.gen.h")
  target_include_directories(demo_sim PRIVATE include "${DEMO_GEN}" demo)
  target_link_libraries(demo_sim PRIVATE Threads::Threads)
  if(UNIX AND NOT APPLE)
    target_link_libraries(demo_sim PRIVATE rt)
  endif()
endif()
