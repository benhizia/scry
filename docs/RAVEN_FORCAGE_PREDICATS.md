# Étude : forçage de valeurs et prédicats utilisateur

> Étude, rien n'est codé. Deux fonctions à ajouter après validation du logiciel
> minimal ; elles sont inscrites dans la feuille de route
> ([RAVEN_CONTOUR.md](RAVEN_CONTOUR.md)).
>
> Vocabulaire : **forçage**, c'est remplacer une valeur à la place de son
> écrivain, pour tous ses lecteurs. À ne pas confondre avec **Pause vue**, déjà
> codé, qui gèle seulement l'affichage de `raven-view`.

---

## 1. Forçage de valeurs

### Le besoin

Voir ce que fait un système consommateur s'il reçoit une autre valeur que celle
de son producteur, sans modifier ni l'un ni l'autre. Le développeur choisit un
champ dans `raven-view`, saisit la valeur (liste des enums, `true`/`false`,
nombre) et l'applique. Tant que le forçage est actif, **l'écrivain ne peut plus
imposer sa valeur** : tous les lecteurs voient la valeur forcée.

Quel que soit le transport, quelques règles s'imposent :

- **Une seule autorité** : `raven-view` demande, `raven.exe` applique et
  journalise. Deux visualiseurs ne se contredisent pas, et tout forçage est
  tracé.
- **Mode intrusif explicite** : désactivé par défaut, activé au lancement
  (`raven --allow-override`). Une liste de champs interdits peut venir de
  `scry.ini`.
- **Toujours visible** : bandeau rouge dans l'IHM, liste des forçages actifs,
  bouton « tout relâcher ».
- **Relâchement sûr** : à la fermeture de `raven.exe` ou à la perte du
  visualiseur, selon une option, et avec une durée maximale en option.
- **Enregistré** : chaque pose ou relâchement de forçage est un événement du
  `.rvn`. On sait au rejeu ce qui était vrai et ce qui était forcé, en gardant
  la valeur d'origine et la valeur forcée.
- **Granularité** : un champ feuille, un élément de tableau, un champ de bits
  plus tard.

### En réseau : le cas naturel

**Point à point, RAVEN en intermédiaire** (le pont déjà prévu,
[ETUDE_ACQUISITION.md](ETUDE_ACQUISITION.md) § 4). Chaque message traverse
`raven.exe` : on le décode avec le descripteur, on remplace les octets du champ
et on réémet. Pas de déchirure possible, puisque le message est modifié avant
d'être envoyé. C'est le cas simple.

- Le coût tient dans le chemin critique du relais : une copie et quelques
  `memcpy` par message forcé, rien quand aucun forçage n'est actif.
- Il faut recalculer les sommes de contrôle applicatives, s'il y en a (CRC dans
  le message) : à décrire dans le descripteur (annotation `@raven crc=...`).
- Sur TCP, la longueur ne change pas, puisqu'on remplace des octets de même
  taille : aucun problème de découpage.

**Multicast : forcer pour tous suppose d'être sur le chemin.** En multicast, le
producteur émet vers un groupe et chaque abonné reçoit directement de lui.
RAVEN, simple abonné de plus, voit tout mais ne peut rien retirer. Trois
possibilités :

| Approche | Principe | Verdict |
|---|---|---|
| Injection concurrente | RAVEN émet sur le même groupe un paquet forcé juste après l'original | **À écarter** : les lecteurs reçoivent les deux, dans un ordre non garanti. Doublons de numéro de séquence, résultat imprévisible. |
| Relais de groupe | Le producteur émet sur un groupe « amont » (configuration ou redirection réseau) ; RAVEN s'y abonne et réémet sur le groupe que lisent les consommateurs, forçage appliqué | **La bonne solution** : c'est le pont, en multicast. Coûte un saut (latence de l'ordre de 10 à 100 µs en local), et il faut pouvoir changer le groupe du producteur ou le filtrer au switch. |
| Forçage par consommateur | Un consommateur précis reçoit un flux relayé, les autres le flux direct | Utile pour tester un seul équipement sans perturber les autres ; c'est un pont point à point pour ce consommateur. |

Un effet de bord du relais de groupe est à garder en tête : si RAVEN s'arrête,
les consommateurs ne reçoivent plus rien. Il faut un mode où RAVEN relaie
toujours, forçage ou pas, et une procédure de retour au flux direct.

### En mémoire partagée : le cas difficile

La difficulté tient en trois exigences simultanées :

1. Écrire **juste après** la vraie écriture, sinon l'écrivain écrase le forçage
   au cycle suivant.
2. **Sans déchirure** : aucun lecteur ne doit voir un mélange de l'ancienne et
   de la nouvelle valeur, ni la vraie valeur entre l'écriture et le forçage.
3. **Tous les lecteurs** voient la valeur forcée.

Un processus externe qui écrit dans la SHM « au bon moment » ne peut garantir
ni 1 ni 2 : entre la fin de l'écriture du producteur et le forçage, un lecteur
peut passer. La conclusion du brainstorm : **en SHM, le forçage doit se faire
au moment de la publication, c'est-à-dire du côté de l'écrivain ou d'un
publieur unique**.

| # | Approche | Principe | Garanties | Coût, limites |
|---|---|---|---|---|
| A | **Application par la glue du producteur** (recommandée) | La glue générée par Scry ajoute une table de forçages en SHM (champ, octets, actif). Le producteur appelle `raven_gen::apply_overrides()` après son calcul et **avant** de signaler la fin de cycle ; `raven.exe` ne fait qu'écrire dans la table. | 1, 2 et 3, si les lecteurs se synchronisent sur la fin de cycle | Une ligne de plus dans le simulateur ; parcours d'une table vide quand rien n'est forcé, négligeable. Suppose un écrivain instrumenté et un signal de fin de cycle. |
| B | **Publieur en deux phases** | L'écrivain écrit dans une zone privée et signale « écrit » ; RAVEN applique les forçages et publie dans la zone lue par les consommateurs, puis signale « publié ». | 1, 2 et 3 | Latence d'un saut, **copie de toute la zone** (9 ms pour 50 Mo, mesuré), consommateurs à adapter pour attendre « publié ». Réservé aux petites zones. C'est le pont réseau appliqué à la SHM. |
| C | **Accesseurs générés côté lecteurs** | Les lecteurs lisent par des accesseurs générés qui consultent la table de forçages. | 2 et 3 pour les lecteurs instrumentés | Intrusif chez **chaque** lecteur ; un lecteur non recompilé voit la vraie valeur. À écarter en général. |
| D | **Écriture externe opportuniste** | RAVEN écrit la valeur forcée dès qu'il voit la fin de cycle. | Aucune | Fenêtre de course, déchirure possible, écrasé au cycle suivant. Acceptable seulement comme « coup de pouce » de test manuel, jamais comme garantie. |
| E | Protection mémoire ou points d'arrêt matériels | `mprotect`, pages de garde, registres de débogage pour intercepter l'écriture | — | Coûteux, fragile, dépendant de l'OS. À écarter. |

**Recommandation : A**, qui prolonge naturellement ce qui existe. La glue
générée copie déjà les variables dans l'anneau de RAVEN ; elle peut aussi
appliquer les forçages dans les variables **d'origine** avant la fin de cycle.
Tous les lecteurs de la SHM, RAVEN compris, voient alors la valeur forcée sans
déchirure, et `raven.exe` n'écrit jamais dans les données d'un autre processus.

Esquisse de ce que Scry générerait en plus :

```cpp
// Table de forcages : dans le segment de RAVEN, ecrite par raven.exe.
struct OverrideSlot {
    std::atomic<uint32_t> seq;       // seqlock : raven.exe ecrit, la glue lit
    uint32_t active;                 // 0 = libre
    uint32_t field_id;               // index global du champ (descripteur)
    uint32_t size;
    uint8_t  value[16];              // octets de la valeur forcee
};

// Genere : table des adresses des champs forcables (resolue par l'editeur de liens).
static void* const kFieldAddr[] = { &g_flight.cycle, &g_flight.pos.lat, /* ... */ };

inline void apply_overrides(raven::Producer& p) {
    for (const OverrideSlot& s : p.overrides())        // quelques emplacements
        if (s.active) std::memcpy(kFieldAddr[s.field_id], s.value, s.size);
}

// Dans le simulateur, fin de cycle :
//   calcul();
//   raven_gen::apply_overrides(producer);   // avant tout lecteur
//   raven_gen::publish(producer);
```

#### Cas retenu : le séquenceur du simulateur est accessible

On sait quand le cycle commence et se termine, et on peut intercaler un appel
entre l'écriture d'un module et la lecture du suivant. C'est plus fin que la
fin de cycle, et cela suffit à tout garantir :

```cpp
// Sequenceur du simulateur : un appel apres chaque module.
for (Module* m : modules) {
    m->step();
    raven_gen::apply_overrides(producer);   // reimpose les forcages actifs
}
raven_gen::publish(producer);
```

- **Pas besoin de savoir quel module écrit quelle variable** : l'appel
  réimpose *tous* les forçages actifs après *chaque* module. Dès que
  l'écrivain a écrit, sa valeur est remplacée avant que le module suivant ne
  lise. Un module qui lit avant l'écrivain, dans le même cycle, voit la valeur
  forcée au cycle précédent.
- **Pas de déchirure** : tout se passe dans le fil du séquenceur, entre deux
  modules.
- **Coût** : un parcours de la table par module, soit rien quand aucun
  forçage n'est actif et quelques `memcpy` sinon.
- **Limite** : ce qu'un module lit et écrit *en interne*, pendant son propre
  `step()`, échappe au forçage. Par exemple un intégrateur `x += dx` lit sa
  propre sortie : il repart de la valeur forcée au cycle suivant, ce qui est
  en général l'effet recherché, mais doit être connu.

#### Sûreté entre fils

Trois accès concurrents sont en jeu : `raven.exe` écrit la table de forçages
(depuis un autre processus), le séquenceur l'applique, et d'éventuels fils
lancés par certains modules lisent ou écrivent les variables forcées.

**1. Entre `raven.exe` et le séquenceur : sans verrou.**

- Chaque emplacement de la table a son compteur de séquence (seqlock), comme
  les emplacements de l'anneau. `apply_overrides()` copie l'emplacement,
  vérifie que le compteur n'a pas bougé, et sinon **garde la valeur appliquée
  précédemment** au lieu d'attendre.
- **Jamais de mutex partagé entre processus** : si `raven.exe` plantait en
  tenant le verrou, le simulateur serait bloqué. Le séquenceur ne doit jamais
  pouvoir attendre RAVEN.
- La table n'est que lue par le simulateur ; seul `raven.exe` l'écrit.

**2. Écriture de la valeur forcée : atomique quand c'est possible.**

- Pour un scalaire aligné de 8 octets ou moins (la grande majorité des
  champs), la glue générée écrit par un store atomique typé plutôt que par
  `memcpy` : `std::atomic_ref<T>(var).store(v, std::memory_order_relaxed)` en
  C++20, `__atomic_store_n` ou `InterlockedExchange` sinon. Un fil qui lit en
  même temps voit l'ancienne ou la nouvelle valeur, jamais un mélange. Scry
  connaît la taille et l'alignement de chaque champ, et choisit donc à la
  génération.
- Pour un champ plus gros (struct, tableau), il n'y a pas d'écriture atomique
  possible : voir le point 3.

**3. Modules qui lancent des fils : cela dépend de leur modèle.**

| Modèle du module | Exemple | Ce qu'il faut |
|---|---|---|
| **Fork-join** : ses fils sont terminés quand `step()` rend la main | calcul parallélisé à l'intérieur du pas | Rien : l'appel après `step()` est sûr tel quel. |
| **Fil de fond qui écrit une sortie** en continu, hors du rythme du séquenceur | acquisition d'un capteur, communication | Appliquer le forçage **au point où ce fil publie**, sous le verrou que le module utilise déjà pour protéger cette sortie : `raven_gen::apply_overrides(producer, raven_gen::Scope::Capteur)` dans la section critique existante. |
| **Fil de fond qui lit** une variable forcée | supervision, journalisation | Scalaire : rien de plus, grâce au store atomique du point 2. Plus gros : il lit déjà sous un verrou ou il a déjà un problème de concurrence, forçage ou pas ; le forçage se fait sous ce même verrou. |

- Pour appliquer par module, Scry génère une table par **portée** : une
  annotation `@raven owner=Capteur` sur les variables concernées, ou une
  liste dans `scry.ini` pour les headers tiers. Sans annotation, tout est dans
  la portée globale appliquée après chaque `step()`.
- **Un seul fil applique une variable donnée** : si deux fils appliquaient le
  même forçage en même temps, ce serait une course, même avec la même valeur.
  Les portées garantissent qu'une variable n'est appliquée que par le fil de
  son propriétaire.
- **Ne pas forcer une variable qui sert de synchronisation** (drapeau d'un
  protocole entre fils, compteur de séquence) : la glue peut les refuser par
  annotation `@raven no_override`.
- Ces fils étant peu nombreux, il est réaliste de les recenser un par un et de
  poser les annotations au moment d'activer le forçage.

Il reste des questions ouvertes :

- **Un champ recalculé à partir d'un autre dans le même cycle** : forcer
  `alt` après le calcul ne change pas ce qui a été calculé à partir de `alt`
  dans ce cycle. C'est voulu (on simule ce que *reçoivent* les consommateurs),
  mais il faut le dire.
- **Lecteurs non synchronisés** sur la fin de cycle : sans signal, aucune
  garantie n'est possible, forçage ou pas. Cela rejoint la question de la
  signalisation de fin de cycle ([ARCHITECTURE_BRIQUES.md](ARCHITECTURE_BRIQUES.md) § 7).
- **Plusieurs écrivains** sur la même SHM : chacun applique les forçages des
  champs qu'il possède. La glue sait quel écrivain publie quelle variable,
  puisque c'est lui qui l'inclut.

---

## 2. Prédicats utilisateur

### Le besoin

Aujourd'hui, une sentinelle signifie « ce champ a changé » et le déclencheur
« un champ, un opérateur, une valeur ». L'idée : laisser l'utilisateur écrire
ses propres conditions sur les interfaces observées, par exemple
`g_sim.state == Running && g_flight.pos.alt > 1000`, puis s'en servir pour
**déclencher, arrêter, compter, marquer ou alerter**.

### Les options de moteur

| Option | Pour | Contre | Verdict |
|---|---|---|---|
| **Constructeur dans l'IHM** (listes : champ, opérateur, valeur ; ET/OU) | Aucun texte à apprendre, valeurs d'enum proposées | Vite limité : pas d'arithmétique, pas de parenthèses lisibles | Utile en **façade** du langage ci-dessous |
| **Petit langage d'expressions maison** | Évalué en C++ dans `raven.exe` sur **chaque trame**, en quelques dizaines de ns ; aucune dépendance ; vérifié contre le descripteur avant usage ; enums par leur nom | Un analyseur à écrire (~400 lignes) et à tester | **Recommandé pour commencer** |
| **Lua** embarqué | Petit (~250 Ko), rapide, facile à isoler, avec un état (compteurs, séquences) | Dépendance, deuxième langage à côté de l'autotest Python ; coût d'appel par trame plus élevé | **Plus tard**, si des scripts avec état deviennent nécessaires |
| **Python** embarqué | Déjà connu, glue pybind existante | GIL et ramasse-miettes dans le fil qui voit toutes les trames : contraire aux contraintes temps réel de `raven.exe` | **Non dans `raven.exe`**. Python reste dans l'autotest, qui pilote RAVEN par le protocole. |

**Faut-il Lua ?** Non, a priori. Les tests « A puis B » (un événement, puis
un autre dans un délai) s'écrivent avec deux fonctions à état fournies par
RAVEN, `since(cond)` (trames écoulées depuis que cond a été vraie) et
`held(cond, n)`. Par exemple, « quand le pilote commande la sortie du train,
le train doit être sorti en moins de 3 s » :

```
since(rose(g_cmd.gear_down)) == 150 && !g_flight.gear_down     # action alert
```

Les scénarios à plusieurs étapes avec embranchements relèvent de l'autotest
en Python, qui pilote RAVEN par le protocole.

Ce n'est pas surdimensionné si on commence par le petit langage : il remplace
en même temps le déclencheur, la condition d'arrêt, les sentinelles avancées,
les règles de surveillance et, plus tard, la recherche dans un `.rvn`. Ce sont
cinq fonctions pour un seul mécanisme.

### Comment je le ferais

**Le langage, volontairement petit :**

```
expression  := ou
ou          := et ('||' et)*
et          := comparaison ('&&' comparaison)*
comparaison := somme (('=='|'!='|'<'|'<='|'>'|'>=') somme)?
somme       := produit (('+'|'-') produit)*
produit     := unaire (('*'|'/') unaire)*
unaire      := ('!'|'-') unaire | primaire
primaire    := nombre | 'true' | 'false' | chemin | NomEnum
             | fonction '(' arguments ')' | '(' expression ')'
chemin      := g_flight.pos.alt | g_flight.fuel[2]
```

**Des fonctions qui regardent la trame précédente** : c'est ce qui manque aux
simples comparaisons, et c'est ce que RAVEN peut offrir puisqu'il voit toutes
les trames :

| Fonction | Sens |
|---|---|
| `changed(x)` | x différent de la trame précédente (la sentinelle actuelle) |
| `rose(x)` / `fell(x)` | front montant ou descendant d'un booléen |
| `prev(x)` | valeur à la trame précédente |
| `delta(x)` | `x - prev(x)` |
| `abs`, `min`, `max`, `within(x, a, b)` | arithmétique courante |
| `held(cond, n)` | cond vraie depuis au moins n trames (anti-rebond) |
| `since(cond)` | trames écoulées depuis la dernière fois où cond était vraie |

**Des exemples tirés de la démo :**

```
g_sim.state == Running                                  # le declencheur actuel
rose(g_flight.gear_down) && g_flight.pos.alt > 5000     # train sorti en altitude
abs(delta(g_flight.pos.alt)) > 500                      # saut d'altitude suspect
g_flight.fuel[0] - g_flight.fuel[3] > 50                # desequilibre carburant
held(g_sim.state == Frozen, 100)                        # gel de plus de 2 s
```

**La mise en œuvre dans `raven.exe` :**

1. **Analyse** : un analyseur récursif descendant produit un arbre. Les
   chemins et les noms d'enum sont résolus **à ce moment**, contre le
   descripteur : un champ inexistant, une enum mal orthographiée ou une
   comparaison entre une enum et une autre enum sont refusés avec la position
   de l'erreur, avant tout usage.
2. **Compilation** : l'arbre devient une liste d'instructions pour une petite
   machine à pile, avec les offsets déjà calculés. Rien n'est cherché par nom
   pendant l'évaluation.
3. **Évaluation** : sur chaque trame, dans le fil d'analyse, avec la trame
   courante et la précédente (déjà conservée pour les sentinelles). Tout est
   calculé en `double`, entiers de 64 bits comparés exactement.
4. **Action** attachée à chaque prédicat : `count` (compteur et dernière
   occurrence, comme une sentinelle), `mark` (événement dans le `.rvn`),
   `start` ou `stop` (enregistrement), `alert` (bandeau dans l'IHM).

**Dans le protocole et l'IHM :**

```
pred add <nom> <action> <expression>     ->  ok | err <position> <message>
pred del <nom>
```

- Dans `raven-view` : un champ texte avec complétion des chemins et des noms
  d'enum, l'erreur soulignée à sa position, et le constructeur à listes qui
  écrit le même texte pour ceux qui préfèrent cliquer.
- Les prédicats sont enregistrés dans l'en-tête du `.rvn`, comme le
  déclencheur aujourd'hui.
- Le déclencheur actuel devient un prédicat d'action `start` ; les sentinelles,
  des prédicats `changed(x)` d'action `count`. Le code existant se simplifie au
  lieu de s'alourdir.

### Dictionnaire du langage

Pour qu'on maîtrise vite le langage, tout ce qu'il accepte tient sur une page,
et la même page est intégrée à `raven-view` (voir plus bas).

**Valeurs**

| Écriture | Sens | Exemple |
|---|---|---|
| nombre | entier ou décimal | `42`, `-3.5`, `1e3` |
| `true`, `false` | booléens | `g_flight.gear_down == true` |
| chemin de champ | valeur du champ à la trame courante | `g_flight.pos.alt` |
| élément de tableau | index entre crochets | `g_flight.fuel[2]` |
| nom d'enum | valeur d'une enum, vérifiée contre le type du champ comparé | `g_sim.state == Running` |

**Opérateurs**, du moins au plus prioritaire

| Opérateur | Sens |
|---|---|
| `\|\|` | ou |
| `&&` | et |
| `==` `!=` `<` `<=` `>` `>=` | comparaison |
| `+` `-` | addition, soustraction |
| `*` `/` | multiplication, division |
| `!` `-` (unaires) | non, opposé |
| `( )` | regroupement |

**Fonctions**

| Fonction | Rend | Sens | Exemple |
|---|---|---|---|
| `changed(x)` | booléen | x différent de la trame précédente | `changed(g_flight.phase)` |
| `rose(b)` | booléen | b passe de faux à vrai | `rose(g_flight.gear_down)` |
| `fell(b)` | booléen | b passe de vrai à faux | `fell(g_flight.gear_down)` |
| `prev(x)` | valeur | x à la trame précédente | `prev(g_flight.phase) == Climb` |
| `delta(x)` | nombre | `x - prev(x)` | `abs(delta(g_flight.pos.alt)) > 500` |
| `held(c, n)` | booléen | c vraie depuis au moins n trames | `held(g_sim.state == Frozen, 100)` |
| `since(c)` | nombre | trames depuis la dernière fois où c était vraie | `since(rose(g_cmd.gear_down)) == 150` |
| `abs(x)` | nombre | valeur absolue | `abs(g_flight.pos.lat - 48.85)` |
| `min(a, b)`, `max(a, b)` | nombre | minimum, maximum | `min(g_flight.fuel[0], g_flight.fuel[1]) < 100` |
| `within(x, a, b)` | booléen | a ≤ x ≤ b | `within(g_flight.pos.alt, 0, 40000)` |

**Actions**, à choisir pour chaque prédicat

| Action | Effet quand le prédicat devient vrai |
|---|---|
| `count` | compte et garde la dernière occurrence (comme une sentinelle) |
| `mark` | pose un marqueur horodaté dans le `.rvn` |
| `start` | démarre l'enregistrement s'il est armé (le déclencheur) |
| `stop` | arrête l'enregistrement |
| `alert` | bandeau dans `raven-view`, et compteur |

**Recettes**

| Je veux | J'écris |
|---|---|
| enregistrer dès que la simulation tourne | `start : g_sim.state == Running` |
| arrêter au gel | `stop : g_sim.state == Frozen` |
| attraper un booléen fugitif | `count : changed(g_flight.gear_down)` |
| un saut de valeur suspect | `alert : abs(delta(g_flight.pos.alt)) > 500` |
| un délai dépassé après une commande | `alert : since(rose(g_cmd.gear_down)) == 150 && !g_flight.gear_down` |
| une incohérence entre champs | `alert : g_flight.phase == Cruise && g_flight.pos.alt < 1000` |

**Règles à connaître**

- Évaluation sur **chaque trame**. `prev`, `delta`, `rose`, `fell` et `changed`
  sont faux ou nuls à la première trame.
- Les calculs se font en `double` ; les entiers de 64 bits sont comparés
  exactement.
- Une enum ne se compare qu'à ses propres noms ou à un entier : `g_sim.state
  == Climb` est refusé, puisque `Climb` n'est pas un `SimState`.
- Une division par zéro rend le prédicat faux, et il est signalé une fois.

### Le dictionnaire dans `raven-view`

Le dictionnaire ci-dessus est écrit une seule fois, sous forme de table dans
le code de l'analyseur : noms, signatures, descriptions et exemples. Il sert à
la fois à l'analyseur, à l'aide de l'IHM et à la génération de cette page. Il
ne peut donc pas diverger de ce qui est vraiment accepté.

Dans l'éditeur de prédicats de `raven-view` :

- **Panneau d'aide à côté du champ texte**, avec trois onglets :
  - *Fonctions* : la table ci-dessus, filtrable ; un clic insère la fonction
    avec ses parenthèses.
  - *Champs* : l'arbre du descripteur avec le type de chaque feuille et, pour
    une enum, la liste de ses valeurs ; un clic insère le chemin ou le nom.
  - *Recettes* : les exemples, qu'un clic copie dans l'éditeur, prêts à
    adapter.
- **Complétion** pendant la frappe : chemins de champs, noms d'enum valables
  pour le champ à gauche d'une comparaison, fonctions.
- **Vérification à chaque frappe** : l'erreur est soulignée à sa position,
  avec un message clair (« `Climb` n'est pas une valeur de `demo::SimState` :
  Stopped, Running, Frozen »).
- **Essai immédiat** : un bouton *Tester* évalue l'expression sur la trame
  courante et affiche le résultat, avec la valeur de chaque sous-expression
  au survol. On voit tout de suite pourquoi c'est vrai ou faux.
- **Constructeur à listes** pour les cas simples, qui écrit le texte
  équivalent dans l'éditeur : on apprend la syntaxe en cliquant.

**Découpage proposé :**

1. Analyseur, compilation et évaluation, avec leurs tests unitaires (sans IHM).
2. `pred add/del` dans le protocole ; déclencheur et sentinelles réécrits comme
   prédicats.
3. Champ texte et constructeur dans `raven-view`.
4. Plus tard : la même expression pour chercher dans un `.rvn`.
