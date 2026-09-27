# RAVEN : contour fonctionnel

> *Record, Acquire, Verify, Export, Navigate.* Il capture tout, sans perte, et
> rejoue.
>
> Première partie : ce qui a été discuté jusqu'ici et fait partie du contour.
> Seconde partie : ce qu'on pourrait ajouter par la suite, jamais abordé
> avant. Le « comment » est dans [RAVEN_GLUE.md](RAVEN_GLUE.md),
> [ETUDE_ACQUISITION.md](ETUDE_ACQUISITION.md) et
> [ETUDE_SOURCES.md](ETUDE_SOURCES.md).

## Partie 1 : le contour discuté

### Périmètre et principes

- Tout en C++, contraintes temps réel : pas de GIL, pas de ramasse-miettes,
  tampons alloués au démarrage, files sans verrou.
- Deux exécutables : `raven.exe` (enregistreur, sans IHM) et
  `raven-view.exe` (visualiseur imgui paresseux).
- Un fil par rôle : réception, enregistrement, analyse, publication vers le
  visualiseur.
- Ne parse aucun header et ne devine aucun layout : tout vient du descripteur
  `.rvndesc` généré par Scry.
- Générique : aucune ligne de code propre au projet dans RAVEN. Changer de
  projet, c'est changer de `.rvndesc`, pas d'exécutable.
- Scry ne connaît pas les plugins de RAVEN : il vise seulement le contrat de
  données `raven/descriptor.h`.

### Ce que Scry fournit (au build)

- Le descripteur `.rvndesc` : types, champs, chemins, offsets, tailles, enums,
  tableaux, champs de bits, pointeurs à suivre, unités, seuils, canaux,
  périodes attendues, `layout_hash`.
- La glue du simulateur `raven_publish.gen.cpp` : `static_assert` par champ,
  collecte de fin de cycle (zones dispersées, pointeurs suivis avec leur
  compteur annoté, bases d'origine notées), signal de fin de cycle.
- En option, des codecs par type (boutisme, sérialisation champ par champ) et
  une table `identifiant de message → type` pour les protocoles réseau.
- Les entrées : headers, section `[raven]` de `scry.ini`, annotations
  `@raven` dans les commentaires ou dans `scry.ini` pour les headers tiers.
- Un pointeur sans compteur annoté est refusé, jamais deviné.

### Acquérir (`raven.exe`)

- Système de plugins de sources (`ISource`), choisis à l'exécution dans
  `raven.toml` : même exécutable pour le direct et le rejeu.
- SHM contiguë : fenêtre publiée, seqlock, attente du signal de fin de cycle.
- SHM de pointeurs vers des zones dispersées : collecte faite par le
  simulateur, jamais par lecture de la mémoire d'un autre processus pour
  l'enregistrement.
- TCP : découpage par longueur et en-tête.
- UDP et multicast : respect du MTU (1472 octets utiles), fragmentation et
  réassemblage, numéros de séquence.
- Intermédiaire sur les liaisons point à point : relayer d'abord, copier
  ensuite, sur des fils séparés ; alternative passive par recopie de port
  quand c'est possible.
- Rejeu d'un fichier comme source.
- Trame commune : canal, numéro de séquence, horodatage source et réception,
  `layout_hash`, charge utile, régions suivies et leurs bases.

### Vérifier

- `layout_hash` contrôlé à chaque trame : refus de décoder en cas d'écart.
- Détection des pertes : trous dans les séquences, période attendue
  dépassée.
- Toute perte est signalée et enregistrée comme telle, jamais silencieuse.
- Statistiques de chaque source : débit, pertes, contre-pression.

### Enregistrer

- Chaque trame, sans perte, ou avec perte signalée.
- Fichier `.rvn` auto-descriptif : descripteur en tête, relisible sans le build
  d'origine.
- Bases d'origine des pointeurs enregistrées, pour le rejeu à froid.
- Gros volumes : sélection de canaux, deltas, compression, tampons
  dimensionnés, contre-pression explicite.
- Un seul maître de la sémantique : l'enregistrement est un journal (toutes
  les trames), le visualiseur un état (la dernière).

### Analyser en temps réel

- Sentinelles sur toutes les trames : changement exact pour `bool`, enum et
  entiers, seuil pour les flottants.
- Un booléen qui ne vit qu'une trame est accroché et reste visible.
- Journal des sentinelles publié vers le visualiseur et enregistré.

### Publier vers le visualiseur

- Dernière trame de chaque canal et journal des sentinelles, dans une petite
  SHM locale (ou par le réseau pour un visualiseur distant).
- L'enregistreur n'attend jamais le visualiseur.

### Naviguer, rejouer

- Rejeu avec l'horloge d'origine, vitesse variable, pause, pas à pas, saut.
- Rejeu à froid dans une nouvelle instance : relocation des pointeurs de
  l'ancienne base vers la nouvelle.
- Réinjection région par région, jamais par copie d'une région entière.

### Visualiser (`raven-view.exe`)

- En direct : lit le `.rvndesc`, les instantanés et le journal publiés par
  `raven.exe`.
- Hors ligne : ouvre un `.rvn`, sans `.rvndesc` puisque le descripteur y est.
- Arbre imgui construit à l'exécution (mode immédiat) : noms, chemins, unités,
  enums, tableaux, adresses.
- Paresseux : un nœud replié ne décode rien ; `ImGuiListClipper` pour les très
  grands arbres.
- Changements récents mis en évidence grâce aux sentinelles.
- *Pause vue* : gèle les valeurs affichées sans arrêter l'acquisition (fait).
- Widgets spécialisés écrits à la main, associés par type ou par annotation
  (`@raven widget=map`).
- Un plantage du visualiseur n'arrête pas l'enregistrement ; plusieurs
  visualiseurs peuvent regarder le même enregistreur.

### Exporter

- Extraction de canaux ou de champs vers des formats d'analyse (CSV au
  minimum), à partir d'un `.rvn`.

---

## Partie 2 : ce qu'on pourrait ajouter par la suite

**Priorités retenues, après validation du logiciel minimal** : tampon de
pré-déclenchement, index avec robustesse aux coupures, pilotage par
l'autotest.

Rien de ce qui suit n'a été discuté. À trier avant toute spécification.

### Enregistrement

- **Tampon de pré-déclenchement**, comme un enregistreur de vol ou un
  oscilloscope : garder en permanence les N dernières secondes en mémoire, et
  ne les écrire qu'au déclenchement (sentinelle, marqueur, seuil). Utile pour
  les longues sessions où seul l'incident compte.
- **Déclencheurs d'enregistrement** : démarrer ou arrêter sur une condition
  (`phase == Descente`, `gear_down` passe à `true`).
- **Rotation des fichiers** par taille ou par durée, avec continuité de
  lecture entre segments.
- **Index** dans le `.rvn` (temps, cycle, événements) pour sauter
  instantanément n'importe où dans un fichier de plusieurs gigaoctets.
- **Robustesse aux coupures** : un fichier interrompu (plantage, coupure de
  courant) reste lisible jusqu'au dernier bloc complet ; CRC par bloc.
- **Métadonnées de session** : banc, version et révision du simulateur,
  opérateur, configuration `raven.toml` complète, commentaire libre.
- **Surveillance du disque** : débit d'écriture, place restante, alerte avant
  saturation.

### Temps et sources multiples

- **Plusieurs sources dans un même enregistrement** (SHM du simulateur et
  liaison série vers un équipement, par exemple), alignées sur une même base
  de temps.
- **Synchronisation d'horloges** entre machines (PTP ou NTP) et mesure de la
  dérive, pour corréler des flux venus de postes différents.
- **Latence de bout en bout** mesurée par canal (horodatage source contre
  réception).

### Analyse

- **Marqueurs manuels** pendant l'enregistrement : une touche ou une commande
  pose un repère (« début manœuvre »), avec un commentaire.
- **Recherche dans un enregistrement** : « quand `gear_down` est-il passé à
  `true` ? », « toutes les trames où `alt < 500` », en s'appuyant sur l'index
  des sentinelles.
- **Statistiques par champ** : min, max, moyenne, nombre de changements.
- **Comparaison de deux enregistrements** : écart champ par champ entre une
  exécution et une référence, avec tolérances. Base d'une non-régression.
- **Prédicats utilisateur** : conditions écrites par l'utilisateur sur les
  champs observés (`rose(g_flight.gear_down) && g_flight.pos.alt > 5000`),
  dans un petit langage d'expressions évalué sur chaque trame, avec les
  actions compter, marquer, démarrer, arrêter ou alerter. Le déclencheur et
  les sentinelles actuels en deviennent des cas particuliers. Étude :
  [RAVEN_FORCAGE_PREDICATS.md](RAVEN_FORCAGE_PREDICATS.md) § 2.
- **Règles de surveillance** déclaratives (bornes, cohérences entre champs)
  évaluées en direct, en plus des sentinelles.

### Intervenir sur le système (mode intrusif)

- **Forçage de valeurs** : depuis `raven-view`, remplacer la valeur d'un champ
  pour tous ses lecteurs, en empêchant son écrivain de l'imposer. Simple en
  pont réseau (point à point, relais de groupe multicast) ; en SHM, il faut
  l'appliquer au moment de la publication, par la glue générée du producteur.
  Mode explicite, toujours visible, journalisé dans le `.rvn`. Étude :
  [RAVEN_FORCAGE_PREDICATS.md](RAVEN_FORCAGE_PREDICATS.md) § 1.

### Visualisation

- **Courbes temporelles** de champs choisis, superposables.
- **Liste de surveillance** : quelques champs épinglés hors de l'arbre.
- **Ligne de temps** avec les marqueurs et les événements des sentinelles,
  pour naviguer au clic.
- **Vues sauvegardées** : arbre déplié, champs épinglés, courbes ; rechargées
  par projet.
- **Rejeu synchronisé avec une vidéo** (caméra cockpit, capture d'écran de
  l'IHM du simulateur).
- **Recherche de champ** par nom ou chemin dans l'arbre.

### Exporter, s'interfacer

- **Formats d'analyse** au-delà du CSV : Parquet ou HDF5 pour les gros
  volumes, MCAP pour des outils de visualisation existants.
- **Découpe** d'un segment de `.rvn` en un nouveau `.rvn` autonome.
- **Plugins de sortie** : retransmettre un flux vers un autre outil ou un
  autre poste pendant l'enregistrement.

### Pilotage et intégration

- **Mode sans IHM pilotable** : démarrer, arrêter, marquer, changer de
  fichier par ligne de commande ou par une socket de contrôle.
- **Pilotage depuis la couche d'autotest** : un script démarre un
  enregistrement, lance un scénario, pose des marqueurs, puis compare le
  résultat à une référence.
- **Supervision** : état de santé exporté (débit, pertes, latence, tampons,
  disque) pour un tableau de bord.

### Évolution des layouts

- **Relire un ancien `.rvn` avec un nouveau layout** : correspondance par
  chemin de champ (`pos.alt`), champs ajoutés ou supprimés signalés. Utile
  pour comparer une exécution avant et après une modification de header.
- **Diff de descripteurs** entre deux `.rvndesc`, en réutilisant le diff de
  modèles que Scry sait déjà faire.

### Déploiement et qualité

- **Exécutables autonomes**, sans installation, Windows et Linux.
- **Auto-test de performance** : `raven.exe --bench` mesure débit mémoire,
  disque et réseau sur le banc cible, et dit quelle configuration tient.
- **Producteur de démonstration** qui génère un flux réaliste à partir d'un
  `.rvndesc`, pour tester RAVEN sans simulateur.
- **Intégrité** : empreinte ou signature d'un `.rvn`, pour prouver qu'un
  enregistrement n'a pas été modifié.
