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

**Découpage proposé :**

1. Analyseur, compilation et évaluation, avec leurs tests unitaires (sans IHM).
2. `pred add/del` dans le protocole ; déclencheur et sentinelles réécrits comme
   prédicats.
3. Champ texte et constructeur dans `raven-view`.
4. Plus tard : la même expression pour chercher dans un `.rvn`.
