# Reprise de SwitchSpy dans RAVEN

> Analyse de la branche `claude/describe-selected-011CUvmX5APbfMHaiMR4Xf68`
> d'InterfaceInspector (5 commits, novembre 2025, 138 fichiers, environ
> 13 000 lignes dont 3 900 de README de tests). Rien n'est encore transféré.
> L'ordre suit la demande : fonctions d'abord, puis impact sur l'architecture,
> les classes et les noms, puis transfert des fichiers, tests et données.

## 0. En une phrase

SwitchSpy est le **mode réseau de RAVEN esquissé avant l'heure** : un
intermédiaire TCP, UDP et multicast avec une IHM ImGui. Ses **briques** sont
réelles et réutilisables : sockets des trois types, moniteur de flux,
journal, mesures de performance et une batterie de six scénarios de test. En
revanche, **le relais lui-même n'est pas câblé** : `main.cpp` s'arrête sur
`// TODO: Create actual network connections here`, les contrôleurs de relais,
d'enregistrement et de rejeu font 5 lignes, la sérialisation est vide. On
reprend donc des briques et des scénarios, pas une application.

---

## 1. Fonctions : ce que fait SwitchSpy, ce que RAVEN a déjà, que faire

Légende de l'état dans SwitchSpy : **fait** (code réel), **ébauche**
(structure sans logique), **prévu** (seulement dans la doc).

| Fonction SwitchSpy | État | Dans RAVEN aujourd'hui | Décision |
|---|---|---|---|
| Relais TCP (écoute, connexion vers la cible, transfert) | sockets **faites**, transfert **absent** | prévu (pont point à point, [ETUDE_ACQUISITION.md](ETUDE_ACQUISITION.md) § 4) | **Reprendre les sockets**, écrire le relais dans RAVEN |
| Relais UDP (`sendTo`, `receiveFrom`) | sockets **faites**, transfert **absent** | prévu | **Reprendre les sockets** |
| Espion multicast (abonnement passif, TTL, bouclage) | **fait** | prévu | **Reprendre** tel quel, c'est la partie la plus aboutie |
| Rejeu en réémission multicast | **prévu** | prévu (rejeu) | Idée **à garder** : un rejeu qui réémet sur le réseau, pas seulement vers l'IHM |
| Enregistrement binaire (format `SWIC`) | **prévu** (sérialiseur vide) | **fait** (`.rvn`) | **Écarter le code**, mais **garder deux idées du format** : direction A→B/B→A par paquet et longueur variable |
| Moniteur de flux (débits, écart de débit, pression du tampon, envois bloqués, extrémité muette) | **fait** | partiel (pertes, statut de source) | **Reprendre**, sous le nom « santé » de la liaison |
| Tampon de paquets à éviction (`DataBuffer`) | **fait** | anneau SHM sans perte | **Écarter pour l'enregistrement** (il jette les plus anciens, contraire au sans-perte) ; utilisable côté visualiseur seulement |
| Journal (niveaux, catégories, sinks, historique) | **fait** | `printf` et `msg=` dans le statut | **Reprendre**, avec un sink qui envoie le journal à `raven-view` |
| Mesures de performance (minuteurs de portée, statistiques par opération) | **fait** | absent | **Reprendre**, sert `raven --bench` prévu |
| Panneaux ImGui Journal et Performances | **faits** | absents | **Reprendre** l'idée et une partie du code, alimentés par le protocole |
| Onglet par connexion | ébauche | un arbre par canal | Idée **à garder** quand il y aura plusieurs sources |
| Rendu automatique des structs depuis le JSON d'InterfaceInspector | ébauche (`struct_renderer` : 10 lignes) | **fait**, mieux (`.rvndesc` généré par Scry, arbre paresseux) | **Écarter** : Scry et le `.rvndesc` le remplacent |
| Visualisation « temps réel » ou « différée » | configuration seulement | différée et paresseuse par construction | **Écarter** : RAVEN ne propose pas de mode qui ralentirait le relais |
| Configuration INI (`[global]`, `[connection.x]`, `[recording]`, `[replay.x]`) | **faite** | options en ligne de commande, `raven.toml` prévu | **Reprendre l'INI** plutôt que TOML : même format que `scry.ini`, analyseur déjà écrit |
| Build Windows (presets CMake, `build.cmd`, guide) | **fait** | CMake seul | **Reprendre** les presets et le guide, adaptés |
| Six scénarios de test émetteur/récepteur | **faits**, mais **manuels** | tests unitaires et un essai de bout en bout | **Reprendre**, et les **automatiser** (§ 4) |

**Trois idées nouvelles pour RAVEN**, absentes de nos études :

1. **La direction** : une liaison point à point a deux sens. Chaque trame
   doit dire si elle va de A vers B ou de B vers A, et les deux sens sont
   visibles et enregistrés.
2. **Les diagnostics d'extrémité** : « des données arrivent mais ne
   repartent pas » (le récepteur n'est pas connecté) et « l'émetteur va plus
   vite que le récepteur ». Ce ne sont pas des pertes, et RAVEN ne les voit
   pas aujourd'hui.
3. **Le rejeu vers le réseau** : réémettre un enregistrement sur le groupe
   multicast d'origine, pour rejouer un scénario à un équipement réel.

---

## 2. Impact sur RAVEN : architecture, classes, noms

### Ce que le réseau change dans l'architecture

| Sujet | Aujourd'hui (SHM) | Avec le réseau | Changement |
|---|---|---|---|
| **Unité de donnée** | trame de taille fixe, tous les canaux à la fois | **message** de taille variable, un canal à la fois, dans un sens | `Frame` gagne `channel` et `direction` ; le `.rvn` gagne un type d'enregistrement « message » |
| **Rôle de la source** | lire | **lire et transférer** (relais), ou lire seulement (espion multicast) | nouveau rôle `Relay` à côté de `ISource` |
| **Fil critique** | acquisition, puis moteur sous mutex | **transférer d'abord**, copier ensuite ; le relais ne doit jamais attendre le moteur | une **file sans verrou** (SPSC) entre le fil du relais et le moteur. Elle était prévue, le réseau la rend obligatoire. |
| **Correspondance message → struct** | un canal = une variable globale | SwitchSpy : un fichier de métadonnées par connexion | 1ʳᵉ étape : **un type de struct par liaison et par sens**, déclaré dans `raven.ini` et vérifié contre le `.rvndesc` ; plus tard, une table `identifiant de message → type` générée par Scry |
| **Santé** | pertes et source présente | débits, écart, pression, extrémité muette, envois bloqués | la santé devient un bloc du statut envoyé au visualiseur |
| **Journal** | `printf` | journal à niveaux et catégories | nouveau message du protocole, `log <niveau> <catégorie> <texte>` |

### Correspondance des classes

| SwitchSpy | RAVEN | Pourquoi ce nom |
|---|---|---|
| `NetworkConnection`, `TCPConnection`, `UDPConnection`, `MulticastConnection` | `raven::net::TcpSocket`, `UdpSocket`, `MulticastSocket` | « Connexion » est ambigu : UDP et multicast n'en ont pas. Ce sont des **sockets**. |
| `NetworkAddress` | `raven::net::Endpoint` | terme usuel, plus court |
| `LineSocket` et `Listener` (RAVEN actuel) | fusionnés dans `raven::net` | une seule couche réseau pour le contrôle et les données |
| `PortMapping` + `[connection.x]` | `raven::LinkConfig` + `[link.x]` | une **liaison** relie A et B ; « mapping » décrit la technique, pas le concept |
| `RelayController` (vide) | `raven::TcpRelay`, `raven::UdpRelay` | un relais **est** une source (il produit des trames) qui transfère aussi |
| mode espion multicast | `raven::MulticastSource` | abonné passif : une source comme la SHM |
| rejeu multicast | `raven::MulticastReplay` | un puits (*sink*) : réémet des messages lus dans un `.rvn` |
| `PacketDirection {AtoB, BtoA}` | `raven::Direction {AtoB, BtoA}` | repris tel quel, avec les noms d'extrémité de la configuration dans l'IHM |
| `PacketInfo` | `raven::Frame` étendu | une seule structure de donnée dans tout RAVEN |
| `FlowControlMonitor` | `raven::LinkHealth` | il ne contrôle pas le flux, il le **surveille** : le nom actuel promet autre chose |
| `DataBuffer` | non repris | l'éviction silencieuse est contraire au sans-perte |
| `logging::Logger`, `ILogSink`, `LOG_INFO` | `raven::log::Logger`, `Sink`, `RAVEN_LOG_INFO` | préfixe pour éviter les collisions de macros dans le simulateur |
| `benchmark::PerformanceMonitor`, `ScopedTimer` | `raven::perf::Stats`, `ScopeTimer` | court, dans son propre espace de noms |
| `ConfigManager`, `IniParser` | `raven::Ini` (analyseur) + `raven::Config` (valeur, pas de singleton) | la configuration est passée, pas globale : testable |
| `view::LogPanel`, `PerformancePanel` | `raven::ui::log_panel()`, `perf_panel()` dans `raven-view` | même découpage que `ui.cpp` : des fonctions de dessin |
| `ConnectionState` | `raven::net::State` | local à la couche réseau |
| `switchspy` (espace de noms, préfixe `SWITCHSPY_`) | `raven` (`RAVEN_`) | un seul produit |

**Le nom SwitchSpy disparaît** : ce n'est pas un second outil, c'est le mode
réseau de RAVEN. Le mot « spy » ne reste que dans la doc, pour décrire
l'abonné multicast passif.

### Défauts à corriger au passage

- **`static auto last_warning` dans les méthodes** de `FlowControlMonitor` et
  `DataBuffer` : la variable est partagée par **toutes** les instances, donc
  une liaison bruyante fait taire les avertissements de toutes les autres. À
  remplacer par un membre.
- **Horodatage en `system_clock`** (`timestamp_t`) : il peut reculer (NTP,
  changement d'heure). RAVEN utilise `steady_clock` pour mesurer et garde
  l'heure murale seulement dans les métadonnées de session.
- **Singletons partout** (`Logger`, `ConfigManager`, `NetworkManager`,
  `ConnectionManager`) : difficiles à tester. Seul le journal peut rester
  global ; le reste est passé en paramètre.
- **Un mutex par socket, pris à chaque `send` et `receive`** : inutile quand
  un seul fil possède la socket, ce qui sera le cas dans le relais (un fil
  par sens).
- **`connect()` non bloquant sans suivi** : la connexion est déclarée
  « Connecting » mais rien ne la fait passer à « Connected ». À traiter dans
  le relais (sélection en écriture ou connexion bloquante avec délai).
- **README des tests en anglais, et très longs** (300 à 760 lignes chacun),
  alors que le reste du projet est en français : on garde le scénario et le
  résultat attendu, en un tableau.

---

## 3. Ce qu'il faut ajouter à RAVEN (esquisse)

```cpp
namespace raven {

enum class Direction : uint8_t { AtoB, BtoA };

struct Frame {                      // etendu : SHM et reseau
    uint64_t no = 0, t_ns = 0;
    int      channel = -1;          // -1 : trame complete (SHM)
    Direction direction = Direction::AtoB;
    const unsigned char* data = nullptr;
    uint32_t size = 0;
};

// Un relais est une source qui transfere aussi. Un fil par sens :
// recevoir -> transferer -> pousser une copie dans la file du moteur.
class TcpRelay : public ISource {
public:
    TcpRelay(const LinkConfig&, const Descriptor&);
    // ISource : poll() vide la file alimentee par les deux fils du relais.
private:
    net::TcpSocket listen_, a_, b_;
    SpscQueue<OwnedFrame> queue_;   // jamais bloquant pour le relais
    LinkHealth health_;             // debits, ecart, extremite muette
};

} // namespace raven
```

Dans le `.rvn`, un second type d'enregistrement, à longueur variable, pour
les messages, à côté des trames fixes de la SHM :

```
message  : u8 type=2, u8 direction, u16 channel, u32 length, u64 no, u64 t_ns, octets
```

La relecture reste simple : un enregistrement « message » se lit par sa
longueur. On perd l'accès direct à la n-ième trame, que l'index prévu
(priorité 2) rétablira.

`raven.ini`, dans la continuité de SwitchSpy :

```ini
[link.fcs]
type        = tcp              ; tcp, udp
listen      = 0.0.0.0:8001     ; A se connecte ici
forward     = 192.168.1.100:9001
a_to_b      = FlightCommand    ; struct du .rvndesc, verifiee au demarrage
b_to_a      = FlightStatus

[source.bus]
type  = multicast
group = 239.1.1.1:5000
iface = 192.168.1.10
type_of = SensorData
```

---

## 4. Transfert : fichiers, tests, données

### Code

| Source (SwitchSpy) | Destination (RAVEN) | Travail |
|---|---|---|
| `src/core/tcp_connection.cpp`, `udp_connection.cpp`, `multicast_connection.cpp`, `network_connection.cpp`, `include/.../platform.hpp` | `raven/src/net/tcp.cpp`, `udp.cpp`, `multicast.cpp`, `raven/include/raven/net.h` | Reprise à environ 70 % : renommer, retirer les mutex et les callbacks, fusionner avec `LineSocket`/`Listener`, suivre la connexion non bloquante |
| `src/controller/flow_control.cpp` + `.hpp` | `raven/src/engine/link_health.{h,cpp}` | Reprise quasi directe ; `static` locaux → membres ; seuils en configuration |
| `src/common/logger.cpp` + `.hpp` | `raven/src/common/log.{h,cpp}` | Reprise ; macros préfixées ; nouveau sink vers le protocole |
| `src/common/benchmark.cpp` + `.hpp` | `raven/src/common/perf.{h,cpp}` | Reprise ; utilisé par `--bench` |
| `src/config/ini_parser.cpp` + `.hpp` | `raven/src/common/ini.{h,cpp}` | Reprise ; `ConfigManager` réécrit sans singleton |
| `src/view/log_panel.cpp`, `performance_panel.cpp` | `raven/src/view/ui_log.cpp`, `ui_perf.cpp` | Reprise partielle : alimentés par le client du protocole au lieu du singleton |
| `CMakePresets.json`, `build.cmd`, `quick-build.cmd`, `docs/BUILDING_WINDOWS.md` | `raven/CMakePresets.json`, `raven/build.cmd`, section Windows du README | Adaptation des noms de cibles ; `build.cmd` réduit aux presets |
| `main.cpp`, `main_window`, `connection_tab`, `struct_renderer`, `tree_viewer`, `metadata_parser`, `stats_panel`, `data_buffer`, contrôleurs, sérialisation, `session_data`, `replay_data`, `network_manager`, `connection_manager` | — | **Non repris** : ébauches ou remplacés par RAVEN |

### Tests

Les six scénarios sont le meilleur apport : ils couvrent exactement les cas
difficiles du mode réseau. Ils sont **manuels** aujourd'hui (« lancez
l'IHM », « appuyez sur Entrée ») et **aucun ne passe par SwitchSpy
automatiquement**. On les reprend en tests CTest automatisés :

| Scénario | Ce qu'il vérifie | Test RAVEN |
|---|---|---|
| 01 TCP simple | relais TCP, intégrité des structs | `net_tcp_relay` : récepteur, `raven` en relais, émetteur ; le récepteur sort en erreur au premier écart |
| 02 relais UDP | CRC32 par commande, relais sans connexion | `net_udp_relay` : zéro erreur de CRC, zéro trou de séquence |
| 03 multicast | abonnement passif, plusieurs récepteurs | `net_multicast_spy` : RAVEN reçoit autant que les récepteurs, sans les perturber |
| 04 haut débit | pertes à fort débit (`MarketTick`, 72 octets) | `net_high_rate` : débit mesuré, pertes comptées identiques côté RAVEN et côté récepteur |
| 05 écart de débit | émetteur plus rapide que le récepteur | `net_rate_mismatch` : `LinkHealth` signale l'écart et la pression ; le relais ne perd rien tant que TCP retient |
| 06 structs complexes | imbrication, tableaux (les drapeaux sont des entiers masqués, pas des champs de bits C++) | `net_complex_structs` : décodage via le `.rvndesc` de Scry, comparé aux valeurs émises |

- Chaque couple émetteur/récepteur prend en arguments l'adresse, le débit, le
  nombre de messages et un code de sortie non nul en cas d'écart. Un script
  CTest lance les trois processus et vérifie les codes de sortie.
- Les `shared.hpp` passent par `scry raven`, qui remplace
  `header_inspector.py` et `generate_metadata.cmd`. Les commentaires
  `/// ... * 100` et `(scaled by 10000)` deviennent des annotations d'unité et
  d'échelle (`@raven unit=degC scale=0.01`), à ajouter au vocabulaire prévu.
- Les README de 300 à 760 lignes sont condensés dans un seul
  `raven/tests/net/README.md` : un tableau par scénario (but, commande,
  résultat attendu).
- `tests/test_networking.cpp` (un `TODO`) n'est pas repris.

### Données

| Donnée | Décision |
|---|---|
| `MetaDataGen/*.meta.json` (format InterfaceInspector) | **Obsolète** : remplacé par le `.rvndesc` généré à la volée |
| `config/example.ini`, `tests/*/switchspy.ini` | **Modèles** du futur `raven.ini`, sections renommées (`[connection.x]` → `[link.x]` ou `[source.x]`) |
| `shared.hpp` des six scénarios | **Repris** dans `raven/tests/net/<scénario>/`, ils servent aussi de corpus à Scry |

---

## 5. Découpage proposé

1. **Couche réseau** : `raven::net` (TCP, UDP, multicast) reprise de SwitchSpy,
   avec ses tests unitaires. **Fait** : `include/raven/sockets.h`,
   `src/core/sockets.cpp`, `tests/test_net.cpp`. `LineSocket` et `Listener`
   restent pour le protocole de contrôle, mais partagent désormais les
   utilitaires de plateforme (`src/core/net_platform.h`) ; leur fusion complète
   attendra que le protocole bouge.
2. **Espion multicast** : `MulticastSource`, messages dans le `.rvn`, colonne
   *direction* inutile ici ; scénarios 03 et 04 automatisés. **Fait** :
   - plugin `mcast` (`src/engine/mcast_source.cpp`), déclaré dans un registre
     de sources séparé (`src/engine/sources.cpp`). Le moteur reçoit des
     messages d'un canal (`Frame::channel`) et ne sait pas d'où ils viennent ;
   - `scry raven --struct` : un canal par struct, pour les messages ;
   - `.rvn` en version 2 : chaque message donne un enregistrement de taille
     fixe (état des champs choisis et canal mis à jour). Les enregistrements à
     longueur variable prévus plus haut ne sont pas nécessaires tant qu'une
     liaison transporte des structs de taille connue ; l'accès direct à la
     n-ième trame est conservé ;
   - scénarios 03 et 04 automatisés (`raven_mcast_tests`) : le vrai
     consommateur reçoit tout, les pertes sont annoncées exactement, 50 000
     messages à plus de 200 000 messages/s sans perte en boucle locale.
   - Trouvaille : les `static_assert` des headers de ces scénarios étaient
     faux sur x86-64 (44 et 72 octets annoncés, 48 et 64 réels) ; les headers
     ne compilaient pas. Ils sont retirés, la taille vient de Scry.
3. **Relais TCP et UDP** : `TcpRelay`, `UdpRelay`, file SPSC, `Direction`,
   `[link.x]` dans `raven.ini` ; scénarios 01, 02 et 06.
4. **Santé, journal, performances** : `LinkHealth`, `log`, `perf`, panneaux
   dans `raven-view` ; scénario 05.
5. **Build Windows** : presets CMake et `build.cmd`.
6. Plus tard : rejeu vers le réseau (`MulticastReplay`), table
   `identifiant → type` pour les liaisons qui transportent plusieurs structs.

Chaque étape est livrée seule, testée, et validée par toi avant la
suivante, comme pour le logiciel minimal.

## 6. Questions pour toi

1. Sur tes liaisons réelles, **un seul type de struct par sens**, ou
   plusieurs types avec un en-tête (identifiant, longueur) ? C'est ce qui
   décide si l'étape 6 remonte dans la liste.
2. **INI plutôt que TOML** pour `raven.ini` : d'accord ? C'est cohérent avec
   `scry.ini` et l'analyseur existe.
3. Les **scénarios de SwitchSpy** (capteurs, cotations boursières,
   robotique) sont génériques. Veux-tu les remplacer à terme par des
   scénarios de simulateur de vol, pour que les tests ressemblent à ton
   usage ?
