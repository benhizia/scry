# Autotest Python embarqué

Des scénarios de test écrits en Python pilotent une application C++ legacy
**de l'intérieur**. Ils positionnent des entrées, laissent tourner des cycles,
puis vérifient des sorties, en lisant et en écrivant directement les structures
de l'application. Il n'y a ni IPC, ni copie, ni modification des structs.

```
 un cycle de l'application
 ┌──────────────┬──────────────┬──────────────────────────────────┐
 │ acquisition  │ code métier  │ étape autotest : host.tick()      │
 │              │              │   le scénario reprend, lit        │
 │              │              │   lit et écrit sut.app.g_sensor…  │
 └──────────────┴──────────────┴──────────────────────────────────┘
          même process, même thread, pointeurs directs
```

Les rôles se répartissent ainsi :

| Pièce | Rôle | Écrit par |
|---|---|---|
| `scry gen --pybind` | bindings pybind11 de **tous** les types et de **toutes** les variables globales des headers, et le module `sut` complet | généré par Scry |
| `cpp/autotest_embed.h` | interpréteur embarqué, un `tick()` par cycle | fourni |
| `python/autotest/` | runtime des scénarios : `Runner`, `cycles`, `until`, `expect`… | fourni |
| `scenarios/test_*.py` | les tests | vous |

## La démo

```bash
autotest/run_demo.sh        # Linux, macOS
autotest\run_demo.bat       # Windows
```

Le script génère les bindings et le module `sut` à partir de
`demo/legacy_app.h`, construit `demo/legacy_app` avec CMake et
lance les scénarios de `demo/scenarios/`. `test_echec_volontaire.py` échoue
exprès : l'échec apparaît dans le rapport sans arrêter l'application, et le
code de sortie vaut 1. Le rapport JUnit est écrit dans
`demo/build/autotest-report.xml`.

## Intégrer dans une application CMake

**1. Générer les bindings** pour les headers de l'application :

```bash
scry gen --pybind
```

Dans `[paths] output`, cela écrit :
- `scry_pybind.generated.h` : bindings pybind11 ; ils incluent
  `abi_checks.generated.h`, donc les `static_assert` de layout ;
- `sut.pyi` : stub pour l'autocomplétion dans l'éditeur ;
- `scry_pybind.cmake` : chemins d'include.

Les réglages vont dans la section `[pybind]` de `scry.ini` : `module` (nom du
module dans le stub) et `globals` (instances annoncées dans le stub, par
exemple `sensor: testgen::SensorSample; telemetry: testgen::TelemetryFrame`).

**2. Le module `sut` est généré** (`scry_module.generated.cpp`). Chaque
variable globale des headers y est, par référence, sous son namespace C++ :
`extern SensorSample g_sensor;` dans `namespace app` devient
`sut.app.g_sensor`. Les variables `static` ne sont jamais exposées, et
`[pybind] expose` / `hide` filtrent par nom qualifié. Pour exposer en plus un
objet qui n'est pas une variable globale, écrivez votre propre module avec
`register_all(m)` puis `m.attr("nom") = py::cast(&objet, py::return_value_policy::reference)`.

N'exposez que des objets qui vivent aussi longtemps que l'interpréteur
(globales, singletons), jamais une variable locale au cycle.

**3. Brancher l'étape autotest** dans le séquenceur :

```cpp
#include "autotest_embed.h"

autotest::HostConfig cfg;
cfg.venv      = L"X:\\projet\\.venv";            // runtime Python, numpy...
cfg.paths     = {L"X:\\projet\\autotest\\python"};
cfg.scenarios = "X:/projet/scenarios";
autotest::Host host(cfg);                         // une seule fois

for (;;) {
    acquisition();
    metier();
    if (!host.tick()) return host.exit_code();    // 0 / 1 échec / 2 erreur
}
```

**4. CMake**, avec une option pour garder Python hors de la production :

```cmake
option(LEGACY_AUTOTEST "Etape autotest" OFF)
if(LEGACY_AUTOTEST)
    execute_process(COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
                    OUTPUT_VARIABLE pybind11_DIR OUTPUT_STRIP_TRAILING_WHITESPACE)
    set(PYBIND11_FINDPYTHON ON)
    find_package(pybind11 CONFIG REQUIRED)
    include("${SCRY_GENERATED_DIR}/scry_pybind.cmake")
    scry_pybind_embed(mon_app)      # includes, module sut genere, pybind11::embed
    target_compile_definitions(mon_app PRIVATE LEGACY_AUTOTEST=1)
endif()
```

Sans l'option, l'exécutable ne dépend pas de Python : dans la démo,
`dumpbin /dependents` ne liste aucune DLL Python.

**5. À l'exécution**, l'exe doit trouver `python312.dll`, qui se trouve dans
l'installation de base du venv : ajoutez ce dossier au `PATH` ou copiez la DLL
à côté de l'exe. `HostConfig::venv` pointe sur le venv qui fournit numpy.

## Écrire un scénario

```python
from autotest import scenario, cycles, until, expect, check, record, snapshot, diff

@scenario(timeout=100, tags=["vol"])
async def montee_puis_croisiere(sut):
    """La docstring sert de description."""
    Phase = sut.testgen.FlightPlan.Phase
    sut.app.g_target.position.z = 3000.0
    sut.app.g_sensor.valid = True

    phases = record("phase", lambda: sut.app.g_telemetry.phase.value)   # une valeur par cycle
    for altitude in range(0, 3001, 250):
        sut.app.g_sensor.value = float(altitude)
        await cycles(1)

    await until(lambda: sut.app.g_telemetry.phase == Phase.Cruise, timeout=5)
    expect(sut.app.g_plan.payload.halves.lo, "altitude publiee").eq(3000)
```

| API | Rôle |
|---|---|
| `@scenario`, `@scenario(timeout=N, tags=[...], name=...)` | déclare une coroutine `async def f(sut)` |
| `await cycles(n)` | rend la main pour `n` cycles de l'application |
| `await until(cond, timeout=n)` | reprend dès que `cond()` est vraie, sinon échec après `n` cycles |
| `expect(v, "libellé").eq / ne / lt / le / gt / ge / between / near(tol=, rel=) / true / false / one_of / satisfies` | vérification **bloquante** |
| `check(...)` | même API, **non bloquante** : l'échec est noté et le scénario continue |
| `record(nom, getter)` | trace échantillonnée à chaque cycle ; `.values` renvoie un tableau numpy |
| `snapshot(obj)`, `diff(avant, après)` | instantané figé et différences ligne à ligne |

Les messages d'échec donnent la valeur obtenue et l'attendu :
`altitude publiee = 2750, attendu 3000`.

Les scénarios s'exécutent l'un après l'autre : d'abord les fichiers
`test_*.py` par ordre alphabétique, puis les scénarios dans l'ordre de
déclaration. `Runner(select="vol")` ne lance que ceux dont le nom ou un tag
contient `vol` ; la démo passe `argv[1]` à ce filtre.

## Ce que Python voit des structs

| Membre C++ | En Python |
|---|---|
| scalaire, enum | attribut en lecture-écriture, écrit en place |
| struct imbriquée, type anonyme | objet vue : `a.b.c = 1` écrit en place |
| `T tab[N]` numérique, `std::array` | vue numpy sans copie : `a.v[2] = 5`, `a.v = [...]` (taille vérifiée) |
| `T tab[N]` de structs | séquence d'éléments par référence : `a.legs[3].phase = ...` |
| `char s[N]` | `str` ; une chaîne trop longue lève `ValueError` au lieu d'être tronquée |
| champ de bits | attribut, masque géré par le compilateur |
| pointeur | adresse en lecture seule |
| `std::string` | `str`, par copie |
| autres STL, statiques, non publics | absents, avec un commentaire dans le header généré |
| membre nommé comme un mot-clé Python | suffixe `_` : `from` devient `from_` |

| variable globale `ns::g` | propriété `sut.ns.g` : lue et écrite en place, même scalaire |
| variable globale `const` | lecture seule |
| pointeur global vers une structure décrite | vue typée sur l'objet pointé, ou `None` |

Chaque classe expose aussi `to_dict()`, `__scry_fields__`, `__scry_layout__`
(sizeof, offsets, empreinte) et `from_address(int)`. Écrire un attribut ou une
variable qui n'existe pas lève `AttributeError` : une faute de frappe ne passe
pas inaperçue.

Coût d'un accès : de 60 ns (élément numpy) à 400 ns environ (écriture d'une
globale scalaire). Un tick qui lit et écrit une dizaine de valeurs coûte
quelques microsecondes. Le détail des mesures est dans le README principal,
§ 8.

## Points de vigilance

- **Temps de cycle.** Le Python s'exécute *dans* le cycle. Faites peu de
  travail par tick et gardez les analyses lourdes pour la fin du scénario.
  `HostConfig::tick_budget_ms` compte les ticks trop longs dans le rapport
  (`slow_ticks`).
- **Debug et Release.** Le modèle Scry décrit une configuration de build.
  L'application doit être compilée dans la même, sinon les `static_assert` des
  bindings refusent de compiler : c'est voulu. Pour une application en `/MDd`,
  réglez `[castxml] cl_flags = /MDd` puis régénérez.
- **Erreurs Python.** `Host::tick()` ne laisse sortir aucune exception : une
  erreur de l'autotest l'arrête (code 2), pas l'application.
- **Déboguer un scénario.** Dans le scénario, lancer
  `import debugpy; debugpy.configure(python=r"X:\projet\.venv\Scripts\python.exe"); debugpy.listen(5678); debugpy.wait_for_client()`,
  puis attacher VS Code. `configure` est nécessaire, car `sys.executable` est
  ici l'exe de l'application.

## Tests

- `pytest autotest/tests` : le runtime, avec une fausse application séquencée,
  sans compilation.
- `pytest tests/test_pybind_embed.py` : compile un hôte C++ qui embarque
  Python et le module généré, exécute des scripts qui écrivent dans ses
  structures et variables globales, puis relit les octets aux offsets du
  modèle. Saute sans castxml, g++ ou libpython.
- `autotest/run_demo.sh` : la démo complète, construite avec CMake.
