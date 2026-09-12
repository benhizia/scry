"""Verification ABI : compiler les assertions generees avec le vrai cl.

castxml predit le layout avec clang, qui reimplemente les regles MSVC. Cette
prediction ne vaut que pour les macros qu'il a vues, c'est-a-dire [castxml]
cl_flags et defines. Une application compilee en /MDd a une STL plus grosse
(_ITERATOR_DEBUG_LEVEL=2) : vector, string et map n'y ont pas la meme taille.

'scry verify' compile abi_checks.generated.h avec cl, une fois par profil de
[verify] profiles, et dit pour quelles configurations de build la prediction
tient. La compilation se fait en /Zs : analyse complete, static_assert
compris, sans produire d'objet.
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

_ERROR = re.compile(r"error (C\d+)\s*:\s*(.*)")
_ASSERT = re.compile(r"static_assert failed:\s*'(.*)'")


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


def load_profiles(cfg: Config) -> List[Tuple[str, str]]:
    entries = cfg.get_list("verify", "profiles")
    return parse_profiles(entries) if entries else list(DEFAULT_PROFILES)


def extract_errors(output: str) -> List[str]:
    """Erreurs de cl, ramenees au message utile pour les static_assert."""
    out = []
    for line in output.splitlines():
        m = _ERROR.search(line)
        if not m:
            continue
        message = m.group(2).strip()
        a = _ASSERT.search(message)
        out.append(a.group(1) if a else "%s %s" % (m.group(1), message))
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


def _find_cl(cfg: Config) -> str:
    return str(msvc_env.prepare_cl(cfg))


def run(structs: Sequence[model.Struct], cfg: Config,
        profiles: Sequence[Tuple[str, str]], header=None
        ) -> Tuple[str, List[ProfileResult]]:
    """Genere le header ABI puis le compile pour chaque profil."""
    abi_path = generator.generate_abi(list(structs), cfg, header=header)
    cl = _find_cl(cfg)
    dirs = include_dirs(structs, cfg)

    results = []
    with tempfile.TemporaryDirectory(prefix="scry_verify_") as tmp:
        source = os.path.join(tmp, "scry_verify.cpp")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write('#include "%s"\n' % os.path.basename(abi_path))
        for name, flags in profiles:
            proc = subprocess.run(compile_command(cl, cfg, flags, dirs, source),
                                  capture_output=True, text=True, errors="replace",
                                  cwd=tmp)
            results.append(ProfileResult(name, flags, proc.returncode,
                                         proc.stdout + proc.stderr))
    return abi_path, results
