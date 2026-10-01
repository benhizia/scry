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
   - *Pause vue* : gèle les valeurs affichées, pas
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
  s'en passer). Scry a besoin de castxml : dans le `PATH`, ou déclaré dans
  `[paths] castxml` de `scry.ini`.
- Sous Visual Studio : ouvrir le dossier `raven` (CMake), ou
  `cmake -S raven -B build/raven -G "Visual Studio 17 2022" -A x64`. Ajouter
  `-DPython3_EXECUTABLE=<racine>/.venv/Scripts/python.exe` : `raven_mcast_tests`
  fait appeler `scry raven` par CMake, et l'interpréteur système n'a ni
  pygccxml ni castxml.

### Windows

`raven
un_demo.bat` fait tout : venv, CMake avec Visual Studio 2022,
compilation en Release, puis le simulateur et l'enregistreur dans deux
fenêtres et le visualiseur au premier plan. `--no-view` s'arrête avant l'IHM.

La chaîne est vérifiée automatiquement, sans IHM, par `tests/test_raven_e2e.py` :
le simulateur publie, `raven` acquiert sans perte, enregistre sur ordre du
protocole texte, et `raven-cat` relit le `.rvn`. Le test saute tant que les
exécutables ne sont pas construits. `RAVEN_BUILD_DIR` désigne un autre dossier
de build que `build/raven`.

**État sous MSVC, au 30 septembre 2026** (MSVC 19.44, Visual Studio 17 2022,
x64) : tout construit sans un seul avertissement en `/W4`, visualiseur compris,
et les trois suites CTest passent — `raven_tests`, `raven_net_tests` et
`raven_mcast_tests` — plus les 8 tests Python de RAVEN. La couche réseau et
l'écoute multicast ont donc tourné sur la cible réelle, mais **en boucle locale
seulement** : `IP_MULTICAST_IF` sur une vraie carte et le TTL restent à
éprouver. Détails et commandes dans [../docs/PASSATION.md](../docs/PASSATION.md)
§ 1.3.

Essai complet de la démo, dans trois terminaux :

```
build/raven/demo_sim --name demo
build/raven/raven --desc build/raven/demo_gen/demo.rvndesc --source shm:demo
build/raven/raven-view
```

La démo déroule en boucle 2 s à l'arrêt, 10 s de vol et 2 s de gel.
`g_flight.gear_down` passe à `true` pendant une seule trame au milieu du vol :
c'est ce que la sentinelle doit attraper.

## Relais : RAVEN entre deux équipements

Au lieu d'observer à côté, RAVEN se place **entre** A et B, fait passer les
messages et en garde une copie :

```
raven --desc liaison.rvndesc --source "tcp:0.0.0.0:8001|10.0.0.2:8002|cmd|ack"
raven --desc liaison.rvndesc --source "udp:0.0.0.0:9001|10.0.0.2:9002|mesure|consigne"
```

`<écoute>|<vers>|<canal A vers B>|<canal B vers A>`. A nous joint sur
`écoute`, nous joignons B sur `vers`. Un sens laissé vide n'est pas relayé.
Un seul type de struct par sens pour l'instant : TCP est un flux sans
frontières, et c'est la taille du canal qui le découpe.

La même chose dans un fichier, plus lisible dès qu'on y revient
(`config/raven.ini.example`) :

```ini
[link.principal]
type    = tcp
listen  = 0.0.0.0:8001
forward = 10.0.0.2:8002
a_to_b  = commande
b_to_a  = acquittement
```

```
raven --desc liaison.rvndesc --link raven.ini
raven --desc liaison.rvndesc --link raven.ini#secours
```

### Plusieurs liaisons dans un seul RAVEN

`raven --link raven.ini` monte **toutes** les sections `[link.x]` ;
`--link raven.ini#secours` n'en monte qu'une. Chaque liaison a son descripteur
(`desc =`), sa source, son moteur, son déclencheur et son enregistrement
(`record =`), et son propre fil d'acquisition : une liaison muette ne retarde
pas celle d'à côté.

**Un moteur par liaison, et non un moteur à plusieurs descripteurs.** Un champ
se désigne par un `FieldRef`, c'est-à-dire un canal et un champ. Un moteur
unique aurait exigé une troisième coordonnée, la liaison, dans le `FieldRef` —
donc dans le protocole texte, dans le visualiseur, dans l'en-tête du `.rvn`,
dans les sentinelles et dans le déclencheur : tout ce qui touche à un champ.
Un moteur par liaison ne change rien à cela, et donne en prime à chacune son
propre déclencheur et son propre enregistrement, ce qui est bien ce que l'on
veut.

Le protocole gagne deux commandes, et **reste compatible** :

| | |
|---|---|
| `links` | une ligne `link <i> <nom> <état> <trames> <source>` par liaison, `*` sur la courante |
| `use <indice\|nom>` | choisit la liaison dont on parle ensuite, et rend son descripteur |

Toute autre commande s'adresse à la liaison choisie, la première par défaut.
Avec une seule liaison, le dialogue est donc exactement celui d'avant : un
visualiseur qui ignore `links` et `use` continue de marcher — ce que
`tests/test_raven_e2e.py` vérifie sans avoir été modifié.

**Ce qui gouverne la conception.** Le transfert est la fonction vitale : si
RAVEN le retarde, il ne se contente pas de mal observer, il dégrade le système
qu'il observe. D'où l'ordre, jamais autrement :

```
recevoir  →  transférer  →  pousser une copie dans la file
```

La copie part dans une file sans verrou (`include/raven/spsc.h`), vidée par le
fil d'acquisition. Sans elle, le relais appellerait `Engine::on_frame`, qui
prend un mutex partagé avec le visualiseur : le temps de transfert entre deux
équipements réels dépendrait alors de ce que dessine une IHM. Quand le moteur
prend du retard, la file se remplit et l'on perd des trames **d'observation**,
qui se comptent comme les pertes de l'anneau SHM. Un message relayé, lui,
n'est jamais perdu de ce fait.

**Un fil par sens**, parce que `recv` bloque et que les deux sens sont
indépendants : un fil unique planté dans le `recv` de A ne relaierait pas ce
que B envoie pendant ce temps. Chaque file a donc un seul producteur, ce qui
la laisse sans verrou.

**Qui ferme une socket.** Chaque socket est lue par un fil et écrite par
l'autre, ce que le système accepte. Ce qu'il n'accepte pas, c'est que l'un la
ferme sous les pieds de l'autre : les deux sens n'utilisent donc que
`send_all_raw` et `recv_exact_raw`, qui rapportent sans fermer. Personne ne
ferme **pendant** une session ; le fil de supervision ferme entre deux, une
fois les deux sens arrêtés.

Le `.rvn` porte le sens de chaque message dans le premier octet du `u32`
jusqu'ici nul de l'en-tête v2 : la version du format ne change pas, et un
fichier sans relais reste octet pour octet celui qu'écrivait la version
précédente. `raven-cat` ajoute une colonne `dir`, vide hors relais.

Mesuré sur ce poste, sous MSVC (`raven_relay_tests`), les trois scénarios de
SwitchSpy repris :

| Scénario | Résultat |
|---|---|
| 01, TCP | 500 commandes et 500 acquittements relayés sans perte ni altération, 1000 enregistrements avec leur sens, zéro trame d'observation perdue |
| 02, UDP | 2000 mesures et 2000 consignes, zéro erreur de CRC32, zéro trou de numérotation |
| 06, structs complexes | 300 messages, zéro octet modifié, et **zéro écart de décodage** sur ~6000 comparaisons faites par le descripteur seul |

Le scénario 06 est celui qui prouve le plus : les octets reçus sont relus par
les **offsets du `.rvndesc`**, sans que le relecteur connaisse les types C++,
et comparés aux valeurs émises. Imbrication, tableau de structures, tableau de
scalaires, chaîne, enum à valeurs non contiguës, drapeaux en entier masqué. Il
vérifie aussi que `sizeof` du compilateur égale la taille annoncée par le
descripteur : si elle différait, le relais découperait le flux au mauvais
endroit et tout le reste serait faux.

Un tableau de structures est **expansé** : chaque élément est un champ à part
entière, `legs[2].altitude_ft`, à son offset réel. Le relecteur n'a aucune
arithmétique à faire, il demande le chemin qu'il veut. Et tout ce qui traite
un champ en hérite sans rien changer : enregistrement, sentinelles, traces,
colonnes de `raven-cat`, visualiseur.

C'est une correction de ce scénario 06 : auparavant le descripteur ne décrivait
que l'élément 0, si bien que `legs[1..3]` n'existaient nulle part et n'étaient
ni enregistrables, ni observables. Un tableau de scalaires, lui, n'est pas
expansé : il porte déjà son `count`.

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
- **Publication non bloquante** : `raven` n'attend jamais son visualiseur.
  Les mises à jour passent par une file de sortie plafonnée ; quand le
  visualiseur ne suit plus, des lots sont abandonnés et comptés, et il
  rattrape à la mise à jour suivante. Les réponses aux commandes, elles, ne
  sont jamais abandonnées : un enregistrement reste arrêtable même si l'IHM
  est figée. L'enregistrement est un journal, le visualiseur un état.
- **`.rvn` à enregistrements de taille fixe** : l'en-tête contient le
  descripteur, les champs choisis et le déclencheur. La n-ième trame se trouve
  par un simple calcul, et un fichier coupé reste lisible jusqu'au dernier
  enregistrement complet. Un trou dans les numéros de trame est une perte.
- **Des plugins de source** derrière l'interface `ISource`
  (`include/raven/source.h`), déclarés dans `src/engine/sources.cpp` : `shm`
  pour l'anneau du simulateur, `mcast` pour une écoute passive, `tcp` et `udp`
  pour un relais. Le moteur ne sait pas d'où viennent les trames.

## Écoute passive multicast

Le plugin de source `mcast` fait de `raven` un abonné de plus sur un groupe
multicast : il écoute à côté des vrais consommateurs, sans rien leur
retirer. Chaque datagramme est un message d'un canal du descripteur.

1. Décrire la struct transportée, comme canal (une struct, pas une variable) :
   ```
   scry raven -H telemetrie.h --struct TelemetryBroadcast --name telemetry -o gen
   ```
2. Lancer l'enregistreur sur le groupe :
   ```
   raven --desc gen/telemetry.rvndesc --source "mcast:239.1.1.1:5000@192.168.1.10#TelemetryBroadcast?seq=sequence"
   ```
   - `@iface` : interface qui rejoint le groupe (facultatif) ;
   - `#canal` : struct transportée (facultatif s'il n'y a qu'un canal) ;
   - `?seq=champ` : champ qui numérote les messages. Un saut est compté comme
     perte ; sans lui, UDP ne dit rien de ce qui manque.
3. `raven-view` et `raven-cat` s'utilisent comme avec la mémoire partagée.
   Un datagramme d'une autre taille que la struct est écarté et compté.

En réseau, chaque message produit un enregistrement dans le `.rvn` : l'état
de tous les champs choisis à cet instant, et le canal mis à jour (colonne
`channel` de `raven-cat`). Le format passe en version 2 pour porter ce canal ;
les fichiers de version 1 se relisent toujours.

## Couche réseau (mode réseau, en cours)

`include/raven/sockets.h` : `raven::net::TcpSocket`, `TcpListener`,
`UdpSocket`, `MulticastSocket` et `Endpoint`, repris de SwitchSpy
(InterfaceInspector). Une socket appartient à un seul fil, toutes les
attentes ont un délai, et une connexion TCP est suivie jusqu'à son issue
(réussie, refusée ou délai écoulé). Plusieurs abonnés multicast du même poste
partagent un port : RAVEN écoute à côté des vrais consommateurs. Tests :
`raven_net_tests`. Le plan de reprise complet est dans
[../docs/RAVEN_REPRISE_SWITCHSPY.md](../docs/RAVEN_REPRISE_SWITCHSPY.md).

## Pas encore là

Voir [RAVEN_CONTOUR.md](../docs/RAVEN_CONTOUR.md). En particulier : relecture
d'un `.rvn` dans `raven-view`, rejeu, pointeurs suivis, champs de bits, plugins
réseau, et les trois priorités retenues (tampon de pré-déclenchement, index et
robustesse aux coupures, pilotage par l'autotest).
