# third_party

Dépendances C++ du visualiseur natif (`scry viewer`, `scry_viewer.bat`).
Seul ce fichier est versionné ; le reste du dossier est ignoré par git.

## Dear ImGui

pyimgui, utilisé par l'IHM Python, n'embarque pas les sources C++ d'ImGui. Le
visualiseur natif en a besoin, et **Scry ne les télécharge pas sans qu'on le
lui demande**.

### Installation manuelle

1. Télécharger Dear ImGui **1.92 ou plus récent**. La version testée est
   `v1.92.9b` :
   <https://github.com/ocornut/imgui/releases/tag/v1.92.9b>, puis
   « Source code (zip) ».
2. Extraire l'archive et placer son **contenu** dans `third_party/imgui/`.
   L'archive contient un dossier `imgui-1.92.9b/` : c'est ce qu'il y a
   *dedans* qu'il faut copier, pas le dossier lui-même.
3. Relancer `scry_viewer.bat`.

Arborescence attendue, réduite aux fichiers réellement compilés :

```
third_party/
  imgui/
    imgui.h
    imgui.cpp
    imgui_draw.cpp
    imgui_tables.cpp
    imgui_widgets.cpp
    backends/
      imgui_impl_win32.cpp
      imgui_impl_dx11.cpp
```

Le reste de l'archive (`examples/`, `docs/`, les autres backends) peut rester
ou être supprimé, Scry ne s'en sert pas.

### Autres possibilités

- **Un checkout existant ailleurs** : renseigner son chemin dans
  `[viewer] imgui_dir` de `scry.ini`.
- **Téléchargement à la demande** : `scry_viewer.bat --fetch-imgui` fait un
  `git clone` au tag `[viewer] imgui_tag`, une seule fois.
- **Téléchargement automatique** : `[viewer] auto_download = true` refait ce
  clone chaque fois que le dossier est vide. Il est désactivé par défaut.

Si les sources manquent ou sont incomplètes, `scry viewer` s'arrête avec la
marche à suivre et la liste des fichiers absents. Avec une version antérieure
à 1.92, il s'arrête aussi, en indiquant la version trouvée.
