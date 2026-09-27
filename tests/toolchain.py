"""Outillage natif des tests d'integration : castxml et le compilateur C++.

Les tests compilaient en dur avec g++ et sautaient sous Windows. Ici on
decouvre l'outillage du poste, puis on construit les lignes de commande par
famille, pour que le meme test tourne sous MSVC comme sous gcc ou clang.

  * castxml : variable SCRY_PATHS_CASTXML, puis [paths] castxml du scry.ini du
    depot, puis le PATH. Un poste Windows l'a rarement dans le PATH.
  * compilateur : cl quand Visual Studio est detecte, sinon g++ ou clang++.

Les headers de tiers (ImGui, pybind11, Python) passent en includes externes :
/external:I sous MSVC, -isystem ailleurs. Sans cela, /W4 /WX ou
-Wall -Wextra -Werror echoueraient sur leurs avertissements, pas les notres.
"""

import configparser
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

import pytest

ROOT = Path(__file__).resolve().parent.parent
STD = "c++17"


# -- castxml -----------------------------------------------------------------
def _castxml() -> Optional[str]:
    candidates = [os.environ.get("SCRY_PATHS_CASTXML", "")]
    ini = ROOT / "scry.ini"
    if ini.is_file():
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        candidates.append(parser.get("paths", "castxml", fallback="").strip())
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir():
            path = path / "castxml.exe"
        if path.is_file():
            return str(path)
    return shutil.which("castxml")


CASTXML = _castxml()


# -- compilateur --------------------------------------------------------------
def _has_msvc() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from scry.parsing import msvc_env
        msvc_env.find_vs_root()
        return True
    except Exception:
        return False


def _gnu() -> Optional[str]:
    for name in ("g++", "clang++"):
        if shutil.which(name):
            return name
    return None


IS_MSVC = _has_msvc()
GNU_CXX = None if IS_MSVC else _gnu()
#  Famille de l'outillage : "msvc", "gnu", ou None sur un poste sans compilateur.
KIND = "msvc" if IS_MSVC else ("gnu" if GNU_CXX else None)
#  Valeur correspondante de [castxml] compiler.
COMPILER = "msvc" if IS_MSVC else ("clang" if GNU_CXX == "clang++" else "gcc")

_cl = None


def cxx() -> str:
    """Compilateur a lancer. Sous MSVC, charge au passage l'environnement
    vcvars : les sous-processus heritent alors de INCLUDE, LIB et PATH."""
    global _cl
    if not IS_MSVC:
        return GNU_CXX
    if _cl is None:
        from scry.config import load_config
        from scry.parsing import msvc_env
        ini = ROOT / "scry.ini"
        cfg = load_config(ini if ini.is_file() else ROOT / "scry.ini.example")
        _cl = str(msvc_env.prepare_cl(cfg))
    return _cl


needs_castxml = pytest.mark.skipif(
    CASTXML is None,
    reason="castxml absent (PATH, [paths] castxml de scry.ini, ou SCRY_PATHS_CASTXML)")
needs_cxx = pytest.mark.skipif(
    KIND is None, reason="aucun compilateur : ni cl (Visual Studio), ni g++, ni clang++")
needs_toolchain = pytest.mark.skipif(
    CASTXML is None or KIND is None, reason="castxml ou compilateur C++ absent")


# -- fragments de scry.ini ----------------------------------------------------
def ini_paths(output=None, cache="", headers=None, extra: Sequence[str] = ()) -> str:
    """Section [paths] d'un scry.ini de test, avec le castxml du poste."""
    lines = ["[paths]"]
    if headers is not None:
        lines.append("headers = %s" % headers)
    if output is not None:
        lines.append("output = %s" % output)
    lines.append("cache = %s" % cache)
    if CASTXML:
        lines.append("castxml = %s" % Path(CASTXML).as_posix())
    lines.extend(extra)
    return "\n".join(lines) + "\n"


def ini_castxml(extra_cflags="-Wno-pragma-once-outside-header",
                extra: Sequence[str] = ()) -> str:
    """Section [castxml] : compilateur du poste. extra_cflags s'adresse a
    castxml lui-meme, qui est clang des deux cotes."""
    lines = ["[castxml]", "compiler = %s" % COMPILER, "extra_cflags = %s" % extra_cflags]
    lines.extend(extra)
    return "\n".join(lines) + "\n"


def ini_verify(profiles="release") -> str:
    """Section [verify]. Les profils de cl et ceux de g++ ont des cles
    distinctes, pour qu'un meme scry.ini serve des deux cotes."""
    if IS_MSVC:
        choix = {"release": "release: /MD", "both": "release: /MD; debug: /MDd"}
        return "[verify]\nprofiles = %s\n" % choix[profiles]
    choix = {"release": "release: -O2", "both": "release: -O2; debug: -D_GLIBCXX_DEBUG"}
    return "[verify]\ngnu_profiles = %s\n" % choix[profiles]


# -- lignes de commande -------------------------------------------------------
def _includes(includes: Sequence, external: Sequence) -> List[str]:
    if IS_MSVC:
        out = ["/I%s" % d for d in includes]
        if external:
            out.append("/external:W0")
            out += ["/external:I%s" % d for d in external]
        return out
    return ["-I%s" % d for d in includes] + ["-isystem%s" % d for d in external]


def _warnings(werror: bool) -> List[str]:
    if not werror:
        return []
    return ["/W4", "/WX"] if IS_MSVC else ["-Wall", "-Wextra", "-Werror"]


def _defines(defines: Sequence[str]) -> List[str]:
    return [("/D%s" if IS_MSVC else "-D%s") % d for d in defines]


def syntax_only(sources: Sequence, includes=(), external=(), defines=(),
                extra: Sequence[str] = (), werror=True) -> List[str]:
    """Analyse complete sans produire d'objet : /Zs ou -fsyntax-only."""
    if IS_MSVC:
        cmd = [cxx(), "/nologo", "/Zs", "/EHsc", "/std:%s" % STD, "/permissive-"]
    else:
        cmd = [cxx(), "-std=%s" % STD, "-fsyntax-only"]
    cmd += _warnings(werror) + _includes(includes, external) + _defines(defines)
    return cmd + list(extra) + [str(s) for s in sources]


OBJ_SUFFIX = ".obj" if IS_MSVC else ".o"


def compile_object(source, obj, includes=(), external=(), defines=(),
                   extra: Sequence[str] = (), werror=False) -> List[str]:
    if IS_MSVC:
        cmd = [cxx(), "/nologo", "/c", "/EHsc", "/Od", "/std:%s" % STD, "/MD"]
        cmd += _warnings(werror) + _includes(includes, external) + _defines(defines)
        return cmd + list(extra) + [str(source), "/Fo%s" % obj]
    cmd = [cxx(), "-std=%s" % STD, "-O0", "-c"]
    cmd += _warnings(werror) + _includes(includes, external) + _defines(defines)
    return cmd + list(extra) + [str(source), "-o", str(obj)]


def compile_exe(sources: Sequence, exe, includes=(), external=(), objects: Sequence = (),
                defines=(), extra: Sequence[str] = (), werror=True,
                libs: Sequence[str] = (), lib_dirs: Sequence[str] = ()) -> List[str]:
    exe = Path(exe)
    if IS_MSVC:
        cmd = [cxx(), "/nologo", "/EHsc", "/O1", "/std:%s" % STD, "/MD", "/bigobj"]
        cmd += _warnings(werror) + _includes(includes, external) + _defines(defines)
        cmd += list(extra) + [str(s) for s in sources] + [str(o) for o in objects]
        cmd += ["/Fe%s" % exe, "/Fo%s%s" % (exe.parent, os.sep)]
        if libs or lib_dirs:
            cmd.append("/link")
            cmd += ["/LIBPATH:%s" % d for d in lib_dirs] + list(libs)
        return cmd
    cmd = [cxx(), "-std=%s" % STD, "-O1"]
    cmd += _warnings(werror) + _includes(includes, external) + _defines(defines)
    cmd += list(extra) + [str(s) for s in sources] + [str(o) for o in objects]
    cmd += ["-L%s" % d for d in lib_dirs] + ["-l%s" % lib for lib in libs]
    return cmd + ["-o", str(exe)]


def exe_name(stem: str) -> str:
    return stem + ".exe" if sys.platform == "win32" else stem


def run(cmd: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          errors="replace", **kwargs)


def check(cmd: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    """Lance et, en cas d'echec, montre la fin de la sortie du compilateur :
    c'est la que sont les erreurs, pas dans l'en-tete."""
    proc = run(cmd, **kwargs)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]
    return proc
