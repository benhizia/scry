# RAVEN : logiciel minimal

*Record, Acquire, Verify, Export, Navigate.* Première version volontairement
simple, à relire et valider avant d'ajouter des fonctions. La conception est
dans [../docs/RAVEN_GLUE.md](../docs/RAVEN_GLUE.md) et le contour visé dans
[../docs/RAVEN_CONTOUR.md](../docs/RAVEN_CONTOUR.md).

## Les pièces

| Pièce | Rôle | Où |
|---|---|---|
| `scry raven` | Lit les headers et écrit le descripteur `.rvndesc` et `raven_publish.gen.h` | `src/scry/codegen/raven.py` |
| `raven_publish.gen.h` | Compilé dans le simulateur : `static_assert` sur le layout, `raven_gen::open()` et `raven_gen::publish()` | généré |
| `producer.h`, `shm.h` | Anneau de trames en mémoire partagée, en headers seuls, sans dépendance | `include/raven` |
| `raven` | Enregistreur sans IHM : acquiert, surveille, enregistre sur demande | `src/engine` |
| `raven-view` | Visualiseur ImGui qui pilote `raven` ; peut aller et venir | `src/view` |
| `raven-cat` | Relit un `.rvn` et l'exporte en CSV, enums en texte | `src/tools` |
| `demo_sim` | Simulateur de démonstration, boucle de 20 ms | `demo` |

## Workflow

```
headers ──scry raven──► demo.rvndesc ─────────────┐
                    └─► raven_publish.gen.h        │
                          │ compilé dans            ▼
                      simulateur ──SHM (anneau)──► raven ◄──TCP──► raven-view
                                                     │
                                                     └──► fichier.rvn ──► raven-cat
```

1. **Générer** la glue depuis les headers du simulateur :
   ```
   scry raven -H sim_state.h --channel g_flight --channel g_sim --name demo -o gen
   ```
   Sans `--channel`, la liste vient de `[raven] channels` dans `scry.ini`,
   sinon toutes les variables globales du header sont prises.
2. **Intégrer** dans le simulateur, une fois :
   ```cpp
   #include "raven_publish.gen.h"
   raven::Producer producer;
   raven_gen::open(producer, "demo");          // au démarrage
   raven_gen::publish(producer);               // en fin de chaque cycle
   ```
3. **Lancer l'enregistreur**. Il ne fait qu'observer, rien n'est enregistré :
   ```
   raven --desc demo.rvndesc --source shm:demo [--port 47800]
   ```
4. **Lancer le visualiseur**, le fermer, le relancer, sans effet sur
   l'enregistreur :
   ```
   raven-view [--host 127.0.0.1] [--port 47800]
   ```
   Depuis l'IHM, on règle tout :
   - colonne *Enr.* : les champs à enregistrer (*Tout choisir* / *Aucun*) ;
   - bouton *D* : choisir le champ déclencheur, puis l'opérateur et la valeur.
     Une enum se choisit dans la liste de ses valeurs, par exemple
     `g_sim.state == Running` ;
   - *Armer* : l'enregistrement attend le déclencheur, puis garde **toutes les
     trames** jusqu'à *Arrêter*. Sans déclencheur, il démarre tout de suite ;
   - colonne *Sent.* : chaque changement est compté, même s'il ne dure qu'une
     trame, et le dernier reste affiché ;
   - colonne *Trace* : courbe du champ, une valeur par trame ;
   - *Figer l'affichage* : arrête le rafraîchissement des valeurs, pas
     l'acquisition.
5. **Relire** :
   ```
   raven-cat vol.rvn --info
   raven-cat vol.rvn > vol.csv
   ```

## Construire

```
cmake -S raven -B build/raven
cmake --build build/raven --config Release
ctest --test-dir build/raven
```

- `raven-view` a besoin des sources d'ImGui dans `third_party/imgui` (voir
  `third_party/README.md`), ou via `-DRAVEN_IMGUI_DIR=...`. Sous Windows, il
  utilise Win32 + DirectX 11 ; ailleurs, GLFW + OpenGL 3 (`libglfw3-dev`).
- `demo_sim` appelle Scry en Python pendant le build (`-DRAVEN_DEMO=OFF` pour
  s'en passer).
- Sous Visual Studio : ouvrir le dossier `raven` (CMake), ou
  `cmake -S raven -B build/raven -G "Visual Studio 17 2022"`.

Essai complet de la démo, dans trois terminaux :

```
build/raven/demo_sim --name demo
build/raven/raven --desc build/raven/demo_gen/demo.rvndesc --source shm:demo
build/raven/raven-view
```

La démo déroule en boucle 2 s à l'arrêt, 10 s de vol et 2 s de gel.
`g_flight.gear_down` passe à `true` pendant une seule trame au milieu du vol :
c'est ce que la sentinelle doit attraper.

## Choix de cette version

- **Descripteur texte** (`.rvndesc`) : lisible, facile à comparer entre deux
  versions, analysé en 150 lignes sans dépendance.
- **Anneau de 64 trames** en mémoire partagée : un retard de lecture de moins
  d'une seconde et quart (à 50 Hz) ne perd rien. Au-delà, chaque trame
  manquante est comptée et visible dans l'IHM, jamais silencieuse.
- **Protocole de contrôle en texte** sur TCP en boucle locale : on peut piloter
  `raven` à la main (`nc 127.0.0.1 47800`, puis `hello`), et c'est ce que
  l'autotest utilisera plus tard. La liste des commandes est en tête de
  `src/engine/engine.h`.
- **Visualiseur paresseux** : il n'envoie à `raven` que les champs des lignes
  affichées, environ 20 fois par seconde. Sentinelles et traces sont
  calculées par `raven`, sur toutes les trames.
- **`.rvn` à enregistrements de taille fixe** : l'en-tête contient le
  descripteur, les champs choisis et le déclencheur. La n-ième trame se trouve
  par un simple calcul, et un fichier coupé reste lisible jusqu'au dernier
  enregistrement complet. Un trou dans les numéros de trame est une perte.
- **Un seul plugin de source**, `shm`, derrière l'interface `ISource`
  (`include/raven/source.h`). TCP, multicast et fichier s'y ajouteront sans
  toucher au moteur.

## Pas encore là

Voir [RAVEN_CONTOUR.md](../docs/RAVEN_CONTOUR.md). En particulier : relecture
d'un `.rvn` dans `raven-view`, rejeu, pointeurs suivis, champs de bits, plugins
réseau, et les trois priorités retenues (tampon de pré-déclenchement, index et
robustesse aux coupures, pilotage par l'autotest).
