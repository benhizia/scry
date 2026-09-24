"""Verification ABI : compiler les assertions generees avec le vrai cl.

castxml predit le layout avec clang, qui reimplemente les regles MSVC. Cette
prediction ne vaut que pour les macros qu'il a vues, c'est-a-dire [castxml]
cl_flags et defines. Une application compilee en /MDd a une STL plus grosse
(_ITERATOR_DEBUG_LEVEL=2) : vector, string et map n'y ont pas la meme taille.

'scry verify' compile abi_checks.generated.h avec cl, une fois par profil de
[verify] profiles, et dit pour quelles configurations de build la prediction
tient. La compilation se fait en /Zs : analyse complete, static_assert
compris, sans produire d'objet.

Hors MSVC (compiler = gcc ou clang), la meme verification passe par g++ ou
clang++ en -fsyntax-only, avec les profils de [verify] gnu_profiles. Le
pendant de /MDd y est -D_GLIBCXX_DEBUG, qui grossit lui aussi les conteneurs
de libstdc++. C'est ce qui permet de verifier l'ABI en CI Linux.
"""

import os
import re
import subprocess
import tempfile
from typing import List, Sequence, Tuple

from scry import model
from scry.codegen import generator
from scry.config import Config
from scry.parsing import msvc_env

# /MDd suffit a definir _DEBUG, donc _ITERATOR_DEBUG_LEVEL=2.
DEFAULT_PROFILES = [("release", "/MD"), ("debug", "/MDd")]
# _GLIBCXX_DEBUG : conteneurs de libstdc++ instrumentes, donc plus gros.
DEFAULT_GNU_PROFILES = [("release", "-O2"), ("debug", "-D_GLIBCXX_DEBUG")]
DEFAULT_CXX = {"gcc": "g++", "clang": "clang++"}

_ERROR = re.compile(r"error (C\d+)\s*:\s*(.*)")
_ASSERT = re.compile(r"static_assert failed:\s*'(.*)'")
# g++ et clang++ : 'fichier:12:1: error: ...'. Le message des static_assert de
# Scry commence toujours par 'Scry : ', ce qui evite de dependre du libelle
# exact, qui change d'une version de compilateur a l'autre.
_GNU_ERROR = re.compile(r"(?:fatal )?error:\s*(.*)")
_SCRY_MESSAGE = re.compile(r"(Scry : .*?)\"?$")


def parse_profiles(entries: Sequence[str]) -> List[Tuple[str, str]]:
    """'release: /MD' -> ('release', '/MD')."""
    out = []
    for entry in entries:
        name, sep, flags = entry.partition(":")
        name = name.strip()
        if not sep or not name:
            raise ValueError(
                "Profil mal forme dans [verify] profiles, attendu 'nom: options' : %r"
                % entry)
        out.append((name, flags.strip()))
    return out


def is_msvc(cfg: Config) -> bool:
    return cfg.compiler == "msvc"


def load_profiles(cfg: Config) -> List[Tuple[str, str]]:
    """[verify] profiles pour MSVC, [verify] gnu_profiles pour gcc et clang.

    Deux cles distinctes : un meme scry.ini peut ainsi servir sous Windows et
    en CI Linux, les options de cl n'ayant aucun sens pour g++.
    """
    if is_msvc(cfg):
        entries, default = cfg.get_list("verify", "profiles"), DEFAULT_PROFILES
    else:
        entries, default = cfg.get_list("verify", "gnu_profiles"), DEFAULT_GNU_PROFILES
    return parse_profiles(entries) if entries else list(default)


def extract_errors(output: str) -> List[str]:
    """Erreurs du compilateur, ramenees au message utile pour les static_assert.

    Reconnait le format de cl ('error C2338: ...') et celui de g++ et
    clang++ ('error: ...').
    """
    out = []
    for line in output.splitlines():
        m = _ERROR.search(line)
        if m:
            message = m.group(2).strip()
            a = _ASSERT.search(message)
            out.append(a.group(1) if a else "%s %s" % (m.group(1), message))
            continue
        g = _GNU_ERROR.search(line)
        if g:
            message = g.group(1).strip()
            a = _SCRY_MESSAGE.search(message)
            out.append(a.group(1) if a else message)
    return out


class ProfileResult(object):
    def __init__(self, name: str, flags: str, returncode: int, output: str):
        self.name = name
        self.flags = flags
        self.returncode = returncode
        self.output = output
        self.errors = extract_errors(output)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def include_dirs(structs: Sequence[model.Struct], cfg: Config) -> List[str]:
    """Dossiers des headers sources, include_paths de la config, sortie."""
    candidates = [os.path.dirname(s.header) for s in structs if s.header]
    candidates += list(cfg.include_paths)
    candidates.append(str(cfg.output_dir))
    out = []
    for d in candidates:
        d = os.path.abspath(d)
        if d not in out:
            out.append(d)
    return out


def compile_command(cl: str, cfg: Config, flags: str, dirs: Sequence[str],
                    source: str) -> List[str]:
    cmd = [cl, "/nologo", "/Zs", "/EHsc", msvc_env._cl_std_flag(cfg.std)]
    cmd += flags.split()
    cmd += ["/D%s" % d for d in cfg.defines]
    cmd += ["/I%s" % d for d in dirs]
    cmd.append(source)
    return cmd


def gnu_compile_command(cxx: str, cfg: Config, flags: str, dirs: Sequence[str],
                        source: str) -> List[str]:
    """Pendant de compile_command pour g++ et clang++."""
    cmd = [cxx, "-fsyntax-only", "-std=%s" % cfg.std]
    cmd += flags.split()
    cmd += ["-D%s" % d for d in cfg.defines]
    cmd += ["-I%s" % d for d in dirs]
    cmd.append(source)
    return cmd


def find_cxx(cfg: Config) -> str:
    """[verify] cxx, sinon g++ ou clang++ selon [castxml] compiler."""
    return cfg.get("verify", "cxx", "") or DEFAULT_CXX.get(cfg.compiler, "c++")


def _find_cl(cfg: Config) -> str:
    return str(msvc_env.prepare_cl(cfg))


def compiler_label(cfg: Config) -> str:
    return "cl" if is_msvc(cfg) else find_cxx(cfg)


def run(structs: Sequence[model.Struct], cfg: Config,
        profiles: Sequence[Tuple[str, str]], header=None
        ) -> Tuple[str, List[ProfileResult]]:
    """Genere le header ABI puis le compile pour chaque profil."""
    abi_path = generator.generate_abi(list(structs), cfg, header=header)
    if is_msvc(cfg):
        cl = _find_cl(cfg)

        def command(flags, dirs, source):
            return compile_command(cl, cfg, flags, dirs, source)
    else:
        cxx = find_cxx(cfg)

        def command(flags, dirs, source):
            return gnu_compile_command(cxx, cfg, flags, dirs, source)
    dirs = include_dirs(structs, cfg)

    results = []
    with tempfile.TemporaryDirectory(prefix="scry_verify_") as tmp:
        source = os.path.join(tmp, "scry_verify.cpp")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write('#include "%s"\n' % os.path.basename(abi_path))
        for name, flags in profiles:
            proc = subprocess.run(command(flags, dirs, source),
                                  capture_output=True, text=True, errors="replace",
                                  cwd=tmp)
            results.append(ProfileResult(name, flags, proc.returncode,
                                         proc.stdout + proc.stderr))
    return abi_path, results
