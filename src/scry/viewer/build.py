"""Compilation du visualiseur C++ natif, 'scry viewer'.

L'IHM Python affiche ce que Scry a compris des headers. Cet executable affiche
ce que le COMPILATEUR en fait : il inclut le header genere, donc ses
static_assert d'ABI, et dessine les structures avec les fonctions generees.
En mode motif de demo, il lit les memes octets que l'IHM Python : les valeurs
affichees doivent coincider.

Chaine :
  1. Dear ImGui : [viewer] imgui_dir, clone au tag [viewer] imgui_tag s'il
     manque. pyimgui n'embarque pas les sources C++.
  2. scry gen : les deux headers generes.
  3. cl : objets ImGui compiles une fois par jeu d'options, puis le
     visualiseur, lie en application fenetree Win32 et DirectX 11.

Le runtime vient de [castxml] cl_flags, /MD a defaut : l'executable est ainsi
compile dans la configuration que le modele decrit, et les static_assert du
header genere le verifient.
"""

import hashlib
import os
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import List, Optional, Sequence

from scry import model, verify
from scry.codegen import generator
from scry.config import Config
from scry.parsing import msvc_env

IMGUI_REPO = "https://github.com/ocornut/imgui.git"
DEFAULT_IMGUI_TAG = "v1.92.9b"

IMGUI_SOURCES = [
    "imgui.cpp",
    "imgui_draw.cpp",
    "imgui_tables.cpp",
    "imgui_widgets.cpp",
    "backends/imgui_impl_win32.cpp",
    "backends/imgui_impl_dx11.cpp",
]
LIBS = ["d3d11.lib", "dxgi.lib", "d3dcompiler.lib", "user32.lib", "gdi32.lib", "dwmapi.lib"]
EXE_NAME = "scry_viewer.exe"


class ViewerError(RuntimeError):
    pass


# -- configuration -----------------------------------------------------------
def imgui_dir(cfg: Config) -> Path:
    return cfg.get_path("viewer", "imgui_dir", "third_party/imgui")


def imgui_tag(cfg: Config) -> str:
    return cfg.get("viewer", "imgui_tag", DEFAULT_IMGUI_TAG)


def build_dir(cfg: Config) -> Path:
    return cfg.get_path("viewer", "build_dir", "build/viewer")


def viewer_source() -> Path:
    """Source du visualiseur, embarque dans le paquet."""
    return Path(str(files("scry.viewer") / "scry_viewer.cpp"))


def runtime_flags(cfg: Config) -> List[str]:
    """Options de cl_flags, completees de /MD si aucun runtime n'y figure."""
    flags = cfg.cl_flags.split()
    if not any(f.upper().startswith(("/MD", "/MT", "-MD", "-MT")) for f in flags):
        flags.insert(0, "/MD")
    return flags


# -- etapes ------------------------------------------------------------------
def ensure_imgui(cfg: Config, log=print) -> Path:
    directory = imgui_dir(cfg)
    if (directory / "imgui.cpp").is_file():
        return directory
    if directory.exists() and any(directory.iterdir()):
        raise ViewerError("%s existe mais ne contient pas imgui.cpp. Corriger "
                          "[viewer] imgui_dir ou vider ce dossier." % directory)
    tag = imgui_tag(cfg)
    log("[viewer] Clone de Dear ImGui %s dans %s" % (tag, directory))
    proc = subprocess.run(["git", "clone", "--depth", "1", "--branch", tag, IMGUI_REPO,
                           str(directory)], capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise ViewerError("Clone de Dear ImGui impossible :\n%s\nCloner a la main %s "
                          "dans %s, ou renseigner [viewer] imgui_dir."
                          % ((proc.stderr or proc.stdout).strip(), IMGUI_REPO, directory))
    return directory


def _run(cmd: Sequence[str], cwd: Path) -> None:
    proc = subprocess.run(list(cmd), capture_output=True, text=True, errors="replace",
                          cwd=str(cwd))
    if proc.returncode != 0:
        errors = verify.extract_errors(proc.stdout + proc.stderr)
        detail = "\n".join(errors[:20]) if errors else (proc.stdout + proc.stderr)[-3000:]
        raise ViewerError("Compilation en echec (cl code %d) :\n%s" % (proc.returncode, detail))


def build(structs: Sequence[model.Struct], cfg: Config, header=None,
          log=print) -> Path:
    """Genere, compile et lie. Retourne le chemin de l'executable."""
    imgui = ensure_imgui(cfg, log)
    generator.generate(list(structs), cfg, header=header)
    cl = str(msvc_env.prepare_cl(cfg))

    flags = runtime_flags(cfg)
    common = ([cl, "/nologo", "/EHsc", "/O2", "/W3", msvc_env._cl_std_flag(cfg.std)]
              + flags + ["/D%s" % d for d in cfg.defines])

    out = build_dir(cfg)
    # Les objets ImGui dependent du runtime et du standard : un dossier par
    # jeu d'options, pour ne jamais lier un objet /MD dans un exe /MDd.
    key = hashlib.sha1(" ".join(common[1:]).encode("utf-8")).hexdigest()[:10]
    obj_dir = out / "obj" / key
    obj_dir.mkdir(parents=True, exist_ok=True)

    imgui_inc = ["/I%s" % imgui, "/I%s" % (imgui / "backends")]
    imgui_objs = [obj_dir / (Path(src).stem + ".obj") for src in IMGUI_SOURCES]
    missing = [src for src, obj in zip(IMGUI_SOURCES, imgui_objs) if not obj.is_file()]
    if missing:
        log("[viewer] Compilation de Dear ImGui (%d fichiers, une seule fois)" % len(missing))
        _run(common + ["/c", "/MP"] + imgui_inc + ["/Fo%s\\" % obj_dir]
             + [str(imgui / src) for src in missing], obj_dir)

    exe = out / EXE_NAME
    includes = imgui_inc + ["/I%s" % d for d in verify.include_dirs(structs, cfg)]
    log("[viewer] Compilation du visualiseur (%s)" % " ".join(flags))
    _run(common + includes + ["/DSCRY_NS=%s" % cfg.cpp_namespace,
                              str(viewer_source()), "/Fo%s\\" % obj_dir, "/Fe%s" % exe]
         + [str(o) for o in imgui_objs]
         + ["/link", "/SUBSYSTEM:WINDOWS", "/ENTRY:mainCRTStartup"] + LIBS, obj_dir)
    return exe


def launch(exe: Path) -> None:
    """Lance l'executable detache : il survit a la fin de 'scry viewer'."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True)
