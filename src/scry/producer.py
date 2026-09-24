"""Producteur de demonstration en memoire partagee : 'scry producer'.

Genere scry_producer.cpp a partir du modele (template producer.cpp.j2), copie
scry_shm.h a cote, et compile le tout avec le compilateur de la cible : cl
sous MSVC, g++ ou clang++ sinon. Le producteur inclut le header ABI : s'il
compile, la charge utile a le layout que le modele annonce.

C'est la demonstration de bout en bout : un processus C++ publie, 'scry
watch', l'IHM Python ou le visualiseur natif lisent et decodent par offset,
sans connaitre le type.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from scry import model
from scry.codegen import generator
from scry.config import Config
from scry.runtime import shm

SOURCE_NAME = "scry_producer.cpp"
DEFAULT_SEGMENT = "scry_demo"
DEFAULT_CXX = {"gcc": "g++", "clang": "clang++"}


class ProducerError(RuntimeError):
    pass


def segment_name(cfg: Config) -> str:
    return cfg.get("shm", "name", DEFAULT_SEGMENT) or DEFAULT_SEGMENT


def build_dir(cfg: Config) -> Path:
    return cfg.get_path("shm", "build_dir", "build/producer")


def copy_protocol_header(cfg: Config) -> str:
    """scry_shm.h dans le dossier de sortie, a cote des headers generes."""
    out_dir = str(cfg.output_dir)
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "scry_shm.h")
    with open(str(shm.header_path()), "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


def generate(structs: List[model.Struct], cfg: Config, header=None) -> str:
    """Ecrit le header ABI, scry_shm.h et scry_producer.cpp. Retourne ce dernier."""
    if not structs:
        raise ProducerError("Aucune structure dans le modele : rien a publier.")
    generator.generate_abi(structs, cfg, header=header)
    copy_protocol_header(cfg)
    context = generator.build_context(structs, cfg, header)
    context["segment"] = segment_name(cfg)
    text = generator.render_template("producer.cpp.j2", context)
    path = os.path.join(str(cfg.output_dir), SOURCE_NAME)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def include_dirs(structs: Sequence[model.Struct], cfg: Config) -> List[str]:
    candidates = [str(cfg.output_dir)]
    candidates += [os.path.dirname(s.header) for s in structs if s.header]
    candidates += list(cfg.include_paths)
    out = []
    for d in candidates:
        d = os.path.abspath(d)
        if d not in out:
            out.append(d)
    return out


def exe_path(cfg: Config) -> Path:
    name = "scry_producer.exe" if cfg.compiler == "msvc" else "scry_producer"
    return build_dir(cfg) / name


def compile_command(cfg: Config, source: str, dirs: Sequence[str], exe: Path,
                    compiler: Optional[str] = None) -> List[str]:
    if cfg.compiler == "msvc":
        from scry.parsing import msvc_env
        flags = cfg.cl_flags.split()
        if not any(f.upper().startswith(("/MD", "/MT")) for f in flags):
            flags.append("/MD")
        cmd = [compiler or "cl", "/nologo", "/EHsc", "/O2", msvc_env._cl_std_flag(cfg.std)]
        cmd += flags + ["/D%s" % d for d in cfg.defines] + ["/I%s" % d for d in dirs]
        cmd += [source, "/Fe%s" % exe, "/Fo%s\\" % exe.parent]
        return cmd
    cxx = compiler or cfg.get("shm", "cxx", "") or DEFAULT_CXX.get(cfg.compiler, "c++")
    cmd = [cxx, "-std=%s" % cfg.std, "-O2", "-pthread"]
    cmd += ["-D%s" % d for d in cfg.defines] + ["-I%s" % d for d in dirs]
    cmd += [source, "-o", str(exe)]
    # shm_open vit dans librt avant la glibc 2.34 ; sans effet apres.
    if os.name == "posix" and not _is_macos():
        cmd.append("-lrt")
    return cmd


def _is_macos() -> bool:
    import sys
    return sys.platform == "darwin"


def build(structs: List[model.Struct], cfg: Config, header=None) -> Path:
    """Genere puis compile le producteur. Retourne l'executable."""
    source = generate(structs, cfg, header)
    exe = exe_path(cfg)
    os.makedirs(str(exe.parent), exist_ok=True)
    compiler = None
    if cfg.compiler == "msvc":
        from scry.parsing import msvc_env
        compiler = str(msvc_env.prepare_cl(cfg))
    cmd = compile_command(cfg, source, include_dirs(structs, cfg), exe, compiler)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise ProducerError("Compilation du producteur echouee :\n%s\n%s"
                            % (" ".join(cmd), (proc.stdout + proc.stderr)[-4000:]))
    return exe
