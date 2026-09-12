"""Detection automatique de MSVC et configuration de castxml pour pygccxml.

Aucun chemin en dur : tout vient de scry.ini, section [castxml].

Deux choses sont faites ici :

  1. localiser l'installation VS via vswhere.exe, dont le chemin est stable,
     puis lire le toolset par defaut au lieu de le figer. Un chemin fige du
     type VC\\Tools\\MSVC\\14.35.32215 casse a la premiere mise a jour de VS ;
  2. charger l'environnement vcvars dans os.environ, pour que INCLUDE, LIB et
     PATH soient positionnes. Sans ca, castxml lance cl.exe pour detecter les
     repertoires d'include, cl ne trouve rien, et l'appel echoue avec un
     laconique "program not executable".

Diagnostic en ligne de commande :

    python -m src.scry.parsing.msvc_env
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from scry.config import Config, load_config

VSWHERE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
    / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


class MsvcNotFound(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------
def find_vs_root() -> Path:
    if not VSWHERE.is_file():
        raise MsvcNotFound("vswhere.exe introuvable : %s" % VSWHERE)

    out = subprocess.check_output(
        [
            str(VSWHERE),
            "-latest",
            "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath",
        ],
        text=True,
        errors="replace",
    ).strip()

    if not out:
        raise MsvcNotFound(
            "Aucune installation VS avec les outils C++ x64. "
            "Installe la charge de travail 'Desktop development with C++'."
        )
    return Path(out.splitlines()[0])


def find_toolset(vs_root: Path, pinned: str = "") -> str:
    tools = vs_root / "VC" / "Tools" / "MSVC"

    if pinned:
        matches = sorted(p.name for p in tools.iterdir() if p.name.startswith(pinned))
        if not matches:
            raise MsvcNotFound(
                "Toolset %s absent. Disponibles : %s"
                % (pinned, ", ".join(sorted(p.name for p in tools.iterdir())))
            )
        return matches[-1]

    default_file = vs_root / "VC" / "Auxiliary" / "Build" / "Microsoft.VCToolsVersion.default.txt"
    if default_file.is_file():
        return default_file.read_text(encoding="utf-8").strip()

    versions = sorted(p.name for p in tools.iterdir())
    if not versions:
        raise MsvcNotFound("Aucun toolset sous %s" % tools)
    return versions[-1]


def find_cl(vs_root: Path, toolset: str, host: str = "Hostx64", arch: str = "x64") -> Path:
    cl = vs_root / "VC" / "Tools" / "MSVC" / toolset / "bin" / host / arch / "cl.exe"
    if not cl.is_file():
        raise MsvcNotFound("cl.exe introuvable : %s" % cl)
    return cl


def prepare_cl(cfg: Config) -> Path:
    """cl.exe du toolset configure, avec l'environnement vcvars charge dans
    os.environ : les processus lances ensuite trouvent INCLUDE, LIB et PATH."""
    vs_root = find_vs_root()
    toolset = find_toolset(vs_root, cfg.toolset)
    cl = find_cl(vs_root, toolset, cfg.host, cfg.arch)
    apply_vcvars(vs_root, cfg.arch, cfg.toolset)
    return cl


ENV_CASTXML = "SCRY_PATHS_CASTXML"


def locate_castxml(cfg: Config) -> Tuple[Path, str]:
    """Chemin de castxml et origine de ce chemin, pour le diagnostic.

    Ordre : variable SCRY_PATHS_CASTXML, puis [paths] castxml de scry.ini,
    puis recherche dans le PATH quand la cle est vide.
    """
    configured = cfg.castxml_path
    if configured:
        origin = ("variable %s" % ENV_CASTXML if os.environ.get(ENV_CASTXML)
                  else "scry.ini, [paths] castxml")
        p = Path(configured)
        if p.is_dir():
            p = p / "castxml.exe"
        if p.is_file():
            return p, origin
        raise MsvcNotFound("castxml pointe sur un fichier inexistant (%s) : %s" % (origin, p))

    from pygccxml import utils
    try:
        path, _name = utils.find_xml_generator()
        if path:
            return Path(path), "trouve dans le PATH, [paths] castxml vide"
    except Exception:
        pass

    raise MsvcNotFound(
        "castxml.exe introuvable. Renseigne [paths] castxml dans scry.ini "
        "ou ajoute castxml au PATH."
    )


def find_castxml(cfg: Config) -> Path:
    return locate_castxml(cfg)[0]


# ---------------------------------------------------------------------------
# Environnement de compilation
# ---------------------------------------------------------------------------
def apply_vcvars(vs_root: Path, arch: str = "x64", toolset: str = "") -> dict:
    """Charge vcvars dans os.environ. Retourne les variables ajoutees ou modifiees."""
    name = "vcvars64.bat" if arch == "x64" else "vcvars32.bat"
    vcvars = vs_root / "VC" / "Auxiliary" / "Build" / name
    if not vcvars.is_file():
        raise MsvcNotFound("Script introuvable : %s" % vcvars)

    cmd = '"%s"%s >nul 2>&1 && set' % (
        vcvars,
        (" -vcvars_ver=%s" % toolset) if toolset else "",
    )
    out = subprocess.check_output(cmd, shell=True, text=True, errors="replace")

    changed = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if os.environ.get(key) != value:
            os.environ[key] = value
            changed[key] = value

    if len(os.environ.get("INCLUDE", "").split(";")) < 2:
        raise MsvcNotFound(
            "vcvars n'a pas positionne INCLUDE. Lance '%s' a la main pour voir l'erreur."
            % vcvars
        )
    return changed


# ---------------------------------------------------------------------------
# Configuration pygccxml
# ---------------------------------------------------------------------------
def _cl_std_flag(std: str) -> str:
    """Traduit le std de scry.ini ('c++17', 'gnu++20'...) en option de cl."""
    version = std.lower().replace("gnu++", "c++")
    if version in ("c++14", "c++17", "c++20"):
        return "/std:%s" % version
    return "/std:c++latest"


def _cl_command(cl: Path, std: str, extra_flags: str = "") -> str:
    """compiler_path qui fait tourner cl dans la configuration de la cible.

    En mode MSVC, castxml interroge cl pour recuperer ses macros predefinies,
    dont _MSVC_LANG. Sans option, cl est en C++14 : _MSVC_LANG vaut 201402L,
    et la STL MSVC masque alors <optional>, <variant>, std::string_view...
    Le -std= passe a clang n'y change rien, c'est _MSVC_LANG qui fait foi.

    extra_flags ([castxml] cl_flags) suit la meme logique : /MDd donne _DEBUG
    et _ITERATOR_DEBUG_LEVEL=2, ce qui grossit vector, string et map. Le
    layout calcule par clang depend de ces macros, pas de l'optimisation.

    castxml accepte '( cc options... )' a la place du seul compilateur, mais
    pygccxml ecrit sous Windows --castxml-cc-msvc "<compiler_path>" sans
    option. On compose donc la valeur pour que, une fois entouree de ses
    guillemets, la ligne devienne :

        --castxml-cc-msvc "(" "C:\\...\\cl.exe" /std:c++17 ")"

    C'est la syntaxe que pygccxml emploie lui-meme sous Linux.
    """
    options = " ".join(x for x in (_cl_std_flag(std), extra_flags.strip()) if x)
    return '(" "%s" %s ")' % (cl, options)


def build_castxml_config(cfg: Optional[Config] = None, **overrides):
    """Retourne un xml_generator_configuration_t pret a l'emploi pour MSVC."""
    from pygccxml import parser

    cfg = cfg or load_config()

    vs_root = find_vs_root()
    toolset = find_toolset(vs_root, cfg.toolset)
    cl = find_cl(vs_root, toolset, cfg.host, cfg.arch)
    castxml = find_castxml(cfg)

    apply_vcvars(vs_root, cfg.arch, cfg.toolset)

    config = dict(
        xml_generator="castxml",
        xml_generator_path=str(castxml),
        compiler="msvc",
        compiler_path=_cl_command(cl, cfg.std, cfg.cl_flags),
        cflags="-std=%s" % cfg.std,
    )
    config.update(overrides)
    return parser.xml_generator_configuration_t(**config)


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------
def main(cfg=None) -> int:
    """Diagnostic MSVC.

    Le cfg est passe par le CLI pour honorer -c/--config ; en appel autonome on
    le charge, et on affiche alors le resume que le CLI a deja imprime sinon.
    """
    if cfg is None:
        cfg = load_config()
        print(cfg.describe())
        print()

    try:
        vs_root = find_vs_root()
        toolset = find_toolset(vs_root, cfg.toolset)
        cl = find_cl(vs_root, toolset, cfg.host, cfg.arch)
    except MsvcNotFound as exc:
        print("[MSVC] %s" % exc)
        return 1

    print("Visual Studio : %s" % vs_root)
    print("Toolset       : %s%s" % (toolset, "  (epingle)" if cfg.toolset else "  (defaut)"))
    print("cl.exe        : %s" % cl)

    try:
        castxml, origin = locate_castxml(cfg)
        print("castxml       : %s  (%s)" % (castxml, origin))
        changed = apply_vcvars(vs_root, cfg.arch, cfg.toolset)
    except MsvcNotFound as exc:
        print("[erreur] %s" % exc)
        return 1

    print("vcvars        : %d variables positionnees" % len(changed))
    print("INCLUDE       : %d repertoires" % len(os.environ.get("INCLUDE", "").split(";")))
    print()

    for cmd in ([str(castxml), "--version"], [str(cl)]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            lines = (out.stdout or out.stderr).strip().splitlines()
            print("%-14s -> %s" % (Path(cmd[0]).name, lines[0] if lines else "pas de sortie"))
        except OSError as exc:
            print("%-14s -> %s" % (Path(cmd[0]).name, exc))

    print()
    print("Toolsets disponibles :")
    for p in sorted((vs_root / "VC" / "Tools" / "MSVC").iterdir()):
        print("  %s" % p.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
