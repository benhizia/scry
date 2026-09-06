# DEVELOPPEMENT.md

Comment travailler sur Scry maintenant que c'est un paquet Python et non plus
un script à la racine. Ce document part du principe qu'on connaît le
développement C++ mais pas les conventions Python.

---

## 1. Le modèle mental, en une page

En C++, la question « où est mon code » a une réponse simple : le compilateur
reçoit des chemins d'include et des chemins de bibliothèques, explicitement.

En Python, l'équivalent est `sys.path` : une liste de répertoires, parcourue
dans l'ordre, dans laquelle l'interpréteur cherche un paquet quand il rencontre
`import scry`. Trois choses la remplissent : le répertoire du script lancé,
les variables d'environnement, et surtout le `site-packages` de l'interpréteur
utilisé.

D'où les trois notions qui structurent tout le reste :

**L'environnement virtuel** est un interpréteur Python avec son propre
`site-packages`. C'est l'unité d'isolation. Un projet, un venv.

**L'installation** est ce qui rend un paquet visible depuis `site-packages`,
donc importable de n'importe où sans se soucier du répertoire courant.

**La distribution** est le fichier que l'on produit pour installer le paquet
ailleurs. En Python c'est un *wheel*, l'analogue d'un binaire livrable.

Le point qui déroute le plus au début : il n'y a pas d'étape de compilation, mais
il y a quand même une étape d'installation. Elle ne transforme pas le code, elle
le rend trouvable.

---

## 2. L'environnement virtuel

### Ce que c'est

`python -m venv .venv` crée un dossier `.venv/` contenant un interpréteur, un
`site-packages` vide et les scripts d'activation. Rien n'est installé au niveau
de la machine. Deux projets peuvent utiliser deux versions incompatibles de la
même bibliothèque sans se marcher dessus.

C'est aussi ce qui règle définitivement le problème rencontré plus tôt : le
`%APPDATA%\Python\Python39\site-packages` est partagé entre un Python 3.9
32 bits et 64 bits, ce qui produit des `ModuleNotFoundError` sur des extensions
compilées alors que pip annonce le paquet comme installé. Un venv n'utilise pas
ce dossier utilisateur.

### Où il vit

Dans le dépôt, à la racine, sous `.venv/`. Il ne se commite jamais : il pèse
lourd, il est spécifique à la machine et à l'architecture, et il se reconstruit
en une commande. Le `.gitignore` doit contenir au minimum :

```
.venv/
__pycache__/
*.pyc
*.egg-info/
build/
dist/
generated/
.bpg_cache/
.scry_cache/
```

### L'activer

```
.venv\Scripts\activate
```

L'activation modifie `PATH` dans le shell courant pour que `python` et `pip`
désignent ceux du venv. Le prompt affiche `(.venv)`. Elle ne survit pas à la
fermeture du shell, et un script `.bat` qui appelle `activate` sans `call`
s'arrête net à cette ligne.

On peut aussi ne jamais activer et préfixer les commandes :

```
.venv\Scripts\python -m scry dump
```

C'est ce qu'il faut faire dans une tâche planifiée ou un build : plus explicite,
et insensible à l'état du shell.

### Vérifier où l'on est

```
python -c "import sys; print(sys.executable)"
pip -V
```

`pip -V` affiche le chemin du `site-packages` visé. Si ce n'est pas celui du
venv, l'activation n'a pas pris.

---

## 3. L'installation éditable, le mode de travail quotidien

```
pip install -e .[ui]
```

Le `.` désigne le répertoire courant, où se trouve `pyproject.toml`. Le `-e`
signifie *editable*.

Une installation normale copie le code dans `site-packages`. Il faudrait
réinstaller à chaque modification, ce qui est insupportable en développement.

Une installation éditable ne copie rien. Elle dépose dans `site-packages` un
petit fichier qui redirige vers `src/scry/`. Le code exécuté est celui du dépôt,
donc **toute modification est active immédiatement**, sans réinstaller.

Trois choses sont créées :

- la redirection vers `src/scry/`, qui rend `import scry` possible partout ;
- un dossier de métadonnées `scry.egg-info/` ou `.dist-info`, qui contient la
  version et les dépendances déclarées ;
- le script `.venv\Scripts\scry.exe`, généré à partir de `[project.scripts]`.

C'est ce dernier point qui répond à « comment je lance mon programme
maintenant ». La commande `scry` est un petit exécutable qui appelle
`scry.cli:main`. Il fonctionne depuis n'importe quel répertoire tant que le venv
est actif.

### Quand réinstaller

Le code Python, jamais. Il faut relancer `pip install -e .` seulement quand on
modifie `pyproject.toml` : ajout d'une dépendance, changement de version, ajout
ou renommage d'une commande dans `[project.scripts]`.

### Les extras

`[ui]` correspond à `[project.optional-dependencies]` du `pyproject.toml`. Sans
lui, la chaîne d'introspection et la génération fonctionnent, mais pas
l'interface graphique. C'est ce qui permet d'installer Scry sur un serveur de
build sans y traîner OpenGL.

---

## 4. Les trois façons de lancer le code

```
scry dump                    le script d'entrée, venv activé
python -m scry dump          le paquet comme module
.venv\Scripts\python -m scry dump    sans activer le venv
```

Les trois exécutent le même code. La deuxième forme est la plus robuste pendant
le développement : elle ne dépend pas du script généré, donc elle continue de
marcher si `[project.scripts]` change sans réinstallation.

Ce qu'il ne faut **plus** faire : `python src/scry/cli.py`. Lancer un fichier
directement place son répertoire en tête de `sys.path` au lieu de la racine du
paquet, et les imports `from scry.config import ...` échouent. C'est le message
`ModuleNotFoundError: No module named 'scry'` classique, et c'est le principal
changement d'habitude par rapport à ton ancien `python main.py`.

---

## 5. Les dépendances

Elles sont déclarées dans `pyproject.toml`, section `[project] dependencies`.
C'est la source de vérité : ce qui doit être présent pour que le paquet
fonctionne, avec des contraintes larges du type `pygccxml>=2.2`.

Un `requirements.txt` a un autre rôle : figer les versions exactes d'un
environnement reproductible, obtenu par `pip freeze`. Il sert au déploiement,
pas à la déclaration du paquet. Le dépôt n'en fournit pas : celui qui existait
recopiait la déclaration au lieu de geler des versions, et avait déjà divergé.
Deux listes de dépendances finissent toujours par se contredire.

Règle simple : une nouvelle bibliothèque utilisée par le code va dans
`pyproject.toml`, puis `pip install -e .` la récupère.

Sur ton poste, l'installation passe par le feed interne, donc rien à faire de
particulier. Hors ligne :

```
pip install -e . --no-index --find-links dependencies --only-binary=:all:
```

---

## 6. Construire une distribution

C'est l'étape « produire le livrable », l'équivalent d'un build Release.

```
pip install build
python -m build
```

Le dossier `dist/` contient alors deux fichiers :

**Le wheel**, `scry-0.2.0-py3-none-any.whl`. C'est une archive zip contenant le
code et les métadonnées, installable directement. `py3-none-any` signifie
Python 3, pas d'ABI native, toutes plateformes : Scry est du Python pur, donc un
seul wheel suffit pour tous les postes.

**La sdist**, `scry-0.2.0.tar.gz`. C'est le code source complet, à partir duquel
un wheel peut être reconstruit. Utile pour l'archivage ou pour un consommateur
qui veut rebâtir lui-même.

### Vérifier ce qu'il y a dedans

L'erreur classique est un wheel qui compile mais dans lequel manquent les
fichiers non-Python. Pour Scry, ce sont les templates Jinja.

```
python -c "import zipfile; print('\n'.join(zipfile.ZipFile('dist/scry-0.2.0-py3-none-any.whl').namelist()))"
```

`scry/codegen/templates/introspection.h.j2` doit apparaître. S'il est absent,
c'est que `[tool.setuptools.package-data]` du `pyproject.toml` est mal
renseigné, et la génération échouera après installation alors qu'elle marchait
en développement.

### Tester le wheel pour de vrai

Le seul test qui compte est une installation propre dans un venv jetable :

```
python -m venv .venv-test
.venv-test\Scripts\activate
pip install dist\scry-0.2.0-py3-none-any.whl
cd %TEMP%
scry check
```

Le `cd` est essentiel. Il vérifie que rien ne dépend du répertoire du dépôt.

### La version

Elle est dans `pyproject.toml`, champ `version`. La convention est
`majeur.mineur.correctif`. Un feed refuse en général de réécrire une version
déjà publiée, donc il faut l'incrémenter avant chaque publication.

---

## 7. Publier sur le feed Azure Artifacts

### Authentification

```
pip install twine keyring artifacts-keyring
```

`artifacts-keyring` gère l'authentification Azure DevOps de façon transparente.
Un `%USERPROFILE%\.pypirc` déclare le dépôt :

```ini
[distutils]
index-servers = PythonPackages

[PythonPackages]
repository = https://ssog-tfs/tfs/DefaultCollection/_packaging/PythonPackages/pypi/upload
```

### Publier

```
python -m build
twine upload -r PythonPackages --cert "C:\Cert\...RootCA...cer" dist\*
```

### Le piège Metadata-Version

Ton feed on-prem refuse les métadonnées de version 2.2 et supérieure avec un
HTTP 400. Les setuptools récents en émettent. Le wheel de Scry sera donc rejeté
comme l'ont été les dépendances tierces.

Vérifier avant d'uploader :

```
python -c "import zipfile,sys;z=zipfile.ZipFile(sys.argv[1]);n=[x for x in z.namelist() if x.endswith('.dist-info/METADATA')][0];print(z.read(n).decode().splitlines()[0])" dist\scry-0.2.0-py3-none-any.whl
```

Si la réponse est `Metadata-Version: 2.1`, rien à faire. Sinon, deux sorties :

1. passer le wheel dans le script `downgrade_wheel_metadata.py`, qui réécrit
   l'en-tête et recalcule le `RECORD` ;
2. épingler une version de setuptools qui émet encore de la 2.1, en modifiant
   `[build-system] requires` du `pyproject.toml`. Il faut tester quelle version
   convient, la bascule ne s'est pas faite sur un numéro rond.

La première option est plus fiable, parce qu'elle ne dépend pas du comportement
d'un outil tiers susceptible de changer.

### Consommer le paquet publié

Sur un autre poste :

```
pip install scry
scry check
```

Le paquet arrive du feed comme n'importe quelle dépendance. À noter : il faudra
tout de même castxml et Visual Studio sur la machine cible, puisque ce sont des
outils externes et non des dépendances Python.

---

## 8. Le cycle de travail au quotidien

Une fois, à la création du poste :

```
git clone ...
cd scry
python -m venv .venv
.venv\Scripts\activate
pip install -e .[ui,dev]
```

Ensuite, tous les jours :

```
.venv\Scripts\activate
scry check          quand la toolchain a bougé
scry dump           boucle de développement
pytest              tests
```

Et pour livrer :

```
éditer la version dans pyproject.toml
python -m build
vérifier le contenu du wheel et sa Metadata-Version
tester dans un venv jetable
twine upload -r PythonPackages dist\*
```

---

## 9. Les erreurs qu'on rencontre les premières semaines

**`ModuleNotFoundError: No module named 'scry'`** — le venv n'est pas activé, ou
`pip install -e .` n'a pas été fait, ou on lance un fichier directement au lieu
de `python -m scry`.

**Une modification n'a aucun effet** — on édite un fichier pendant qu'un autre
interpréteur tourne, ou le paquet a été installé sans `-e`. Vérifier avec
`pip show -f scry` : en mode éditable, l'emplacement pointe vers `src/`.

**`scry` n'est pas reconnu** — le venv n'est pas activé, ou `[project.scripts]` a
changé sans réinstallation.

**Ça marche en dev, pas après installation** — presque toujours un fichier non
Python absent du wheel, ou un chemin résolu par rapport au répertoire courant au
lieu du paquet.

**Un import circulaire** — deux modules s'importent mutuellement. En C++ un
en-tête avancé règle le problème ; en Python il faut soit déplacer le code
partagé dans un troisième module, soit importer à l'intérieur de la fonction.
`parsing/introspect.py` utilise déjà cette seconde technique pour `msvc_env`.

**Les `__pycache__`** apparaissent partout. Ce sont des bytecodes mis en cache,
sans intérêt, ignorés par git. Ils ne se suppriment pas à la main.
