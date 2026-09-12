"""Chargement du parametrage Scry.

Un seul endroit connait scry.ini. Le reste du projet recoit un objet Config et
n'a plus aucun chemin en dur.

    from scry.config import load_config
    cfg = load_config()
    print(cfg.header, cfg.compiler)

Localisation du fichier, dans l'ordre :

  1. le chemin passe explicitement a load_config ;
  2. la variable d'environnement SCRY_CONFIG ;
  3. scry.ini trouve en remontant depuis le repertoire courant, comme le font
     git ou cargo ;
  4. scry.ini trouve en remontant depuis le paquet, ce qui couvre le cas d'une
     installation editable ou l'on travaille dans le depot ;
  5. la configuration utilisateur, %APPDATA%\\scry\\scry.ini sous Windows,
     ~/.config/scry/scry.ini ailleurs.

Chercher par rapport a l'emplacement du code serait une impasse : une fois le
paquet installe depuis un wheel, config.py se trouve dans site-packages et sa
position ne dit plus rien du projet.

Les chemins relatifs du fichier sont resolus depuis le dossier qui le contient.
Quand aucun fichier n'est trouve, la racine est le repertoire courant.
"""

import configparser
import os
from pathlib import Path
from typing import List, Optional

CONFIG_NAME = "scry.ini"
ENV_CONFIG = "SCRY_CONFIG"


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def _user_config() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "scry" / CONFIG_NAME
    return Path.home() / ".config" / "scry" / CONFIG_NAME


def _search_upwards(start: Path) -> Optional[Path]:
    """Remonte l'arborescence a la recherche de scry.ini."""
    current = start.resolve()
    for candidate in [current] + list(current.parents):
        found = candidate / CONFIG_NAME
        if found.is_file():
            return found
    return None


def find_config() -> Optional[Path]:
    """Premier scry.ini trouve, ou None."""
    env = os.environ.get(ENV_CONFIG)
    if env:
        path = Path(env).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(
            "%s pointe sur un fichier inexistant : %s" % (ENV_CONFIG, path)
        )

    found = _search_upwards(Path.cwd())
    if found:
        return found

    found = _search_upwards(_package_dir())
    if found:
        return found

    user = _user_config()
    if user.is_file():
        return user

    return None


class Config(object):
    def __init__(self, parser_obj: configparser.ConfigParser, root: Path,
                 source: Optional[Path]):
        self._cp = parser_obj
        self.root = root
        self.source = source

    @property
    def found(self) -> bool:
        return self.source is not None

    # -- acces bas niveau ---------------------------------------------------
    def get(self, section: str, key: str, default: str = "") -> str:
        env = os.environ.get("SCRY_%s_%s" % (section.upper(), key.upper()))
        if env is not None:
            return env
        return self._cp.get(section, key, fallback=default).strip()

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        raw = self.get(section, key, "true" if default else "false").lower()
        return raw in ("1", "true", "yes", "on")

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        raw = self.get(section, key, "")
        try:
            return int(raw)
        except ValueError:
            return default

    def get_path(self, section: str, key: str, default: str = "") -> Optional[Path]:
        raw = self.get(section, key, default)
        if not raw:
            return None
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (self.root / p)

    def get_list(self, section: str, key: str) -> List[str]:
        raw = self.get(section, key, "")
        return [x.strip() for x in raw.split(";") if x.strip()]

    # -- raccourcis typiques ------------------------------------------------
    @property
    def castxml_path(self) -> Optional[Path]:
        return self.get_path("paths", "castxml")

    @property
    def header(self) -> Optional[Path]:
        return self.get_path("paths", "header")

    @property
    def output_dir(self) -> Path:
        return self.get_path("paths", "output", "generated")

    @property
    def cache_file(self) -> Optional[Path]:
        return self.get_path("paths", "cache")

    @property
    def compiler(self) -> str:
        return self.get("castxml", "compiler", "msvc").lower()

    @property
    def toolset(self) -> str:
        return self.get("castxml", "toolset", "")

    @property
    def host(self) -> str:
        return self.get("castxml", "host", "Hostx64")

    @property
    def arch(self) -> str:
        return self.get("castxml", "arch", "x64")

    @property
    def std(self) -> str:
        return self.get("castxml", "std", "c++17")

    @property
    def cl_flags(self) -> str:
        """Options passees a cl quand castxml l'interroge sur ses macros."""
        return self.get("castxml", "cl_flags", "")

    @property
    def include_paths(self) -> List[str]:
        out = []
        for raw in self.get_list("castxml", "include_paths"):
            p = Path(raw).expanduser()
            out.append(str(p if p.is_absolute() else (self.root / p)))
        return out

    @property
    def defines(self) -> List[str]:
        return self.get_list("castxml", "defines")

    @property
    def extra_cflags(self) -> str:
        return self.get("castxml", "extra_cflags", "")

    @property
    def max_depth(self) -> int:
        return self.get_int("introspection", "max_depth", 8)

    @property
    def follow_pointers(self) -> bool:
        return self.get_bool("introspection", "follow_pointers", False)

    @property
    def include_non_public(self) -> bool:
        return self.get_bool("introspection", "include_non_public", False)

    @property
    def include_static(self) -> bool:
        return self.get_bool("introspection", "include_static", False)

    @property
    def cpp_namespace(self) -> str:
        return self.get("codegen", "namespace", "scry")

    @property
    def emit_abi_checks(self) -> bool:
        return self.get_bool("codegen", "emit_abi_checks", True)

    @property
    def output_header(self) -> str:
        return self.get("codegen", "output_header", "introspection.generated.h")

    @property
    def abi_header(self) -> str:
        return self.get("codegen", "abi_header", "abi_checks.generated.h")

    def describe(self) -> str:
        lines = [
            "config      : %s" % (self.source if self.found
                                  else "AUCUN %s trouve, valeurs par defaut" % CONFIG_NAME),
            "racine      : %s" % self.root,
            "header      : %s" % (self.header or "non renseigne"),
            "compilateur : %s (%s/%s, %s)" % (self.compiler, self.host, self.arch, self.std),
            "cl_flags    : %s" % (self.cl_flags or "aucune, macros d'un build release"),
            "castxml     : %s" % (self.castxml_path
                                  or "non renseigne, recherche dans le PATH"),
        ]
        if not self.found:
            lines.append("")
            lines.append("Cherche depuis %s en remontant, puis dans %s."
                         % (Path.cwd(), _user_config()))
            lines.append("Se placer dans le depot, ou definir %s." % ENV_CONFIG)
        return "\n".join(lines)


_CACHE = None


def load_config(path=None, force_reload: bool = False) -> Config:
    """Charge la configuration. Le resultat est memorise, sauf chemin explicite."""
    global _CACHE

    if path is None and _CACHE is not None and not force_reload:
        return _CACHE

    if path is not None:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError("Fichier de configuration introuvable : %s" % source)
    else:
        source = find_config()

    cp = configparser.ConfigParser()
    if source is not None:
        cp.read(source, encoding="utf-8")
        root = source.parent
    else:
        root = Path.cwd()

    cfg = Config(cp, root, source)
    if path is None:
        _CACHE = cfg
    return cfg


if __name__ == "__main__":
    print(load_config().describe())