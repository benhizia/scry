"""Commentaires de documentation des membres, relus dans le source du header.

castxml ne rapporte que les commentaires Doxygen attaches par clang
('///', '///<', '/** */', '//!<'), et encore, un seul par declaration : un
'///' place avant un membre qui porte aussi un '///<' est perdu. Or les
headers tiers documentent le plus souvent avec de simples '//'.

On ne touche donc pas au header, et on n'active pas la sortie epic de castxml,
qui changerait le format XML pour toute la chaine : castxml donne deja le
fichier et la ligne de chaque declaration, il suffit de relire le source a cet
endroit. Sont retenus :

  * le bloc de commentaires colle au-dessus de la declaration, sans ligne vide
    entre les deux, en '//' comme en '/* */' ;
  * le commentaire en fin de ligne, eventuellement poursuivi sur les lignes
    suivantes pour un '/* */' non referme.

Les deux sont concatenes, dans cet ordre. Ce module ne depend pas de pygccxml :
il se teste sur des chaines.
"""

import re
from typing import Dict, List, Optional

# Marqueurs Doxygen en tete de commentaire, et commandes de resume usuelles.
_OPENERS = re.compile(r"^(?://!<?|///?<?|/\*!<?|/\*\*?<?)")
_COMMAND = re.compile(r"^[@\\](?:brief|short)\s+")


def _clean(fragment: str) -> str:
    """Texte d'un fragment de commentaire, sans ses marqueurs."""
    text = fragment.strip()
    if text.endswith("*/"):
        text = text[:-2]
    text = _OPENERS.sub("", text).strip()
    # Ligne interieure d'un bloc : ' * texte'.
    if text.startswith("*"):
        text = text.lstrip("*").strip()
    return _COMMAND.sub("", text)


def _join(fragments: List[str]) -> str:
    return " ".join(t for t in (_clean(f) for f in fragments) if t)


def find_comment_start(line: str) -> int:
    """Position du premier '//' ou '/*' hors litteral, ou -1.

    Les litteraux sont a eviter : un initialiseur 'std::string url =
    "http://..."' contient un '//' qui n'ouvre aucun commentaire.
    """
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif line.startswith("//", i) or line.startswith("/*", i):
            return i
        i += 1
    return -1


def trailing_comment(lines: List[str], index: int) -> str:
    """Commentaire en fin de la ligne index (base 0), code avant lui."""
    line = lines[index]
    start = find_comment_start(line)
    if start <= 0 or not line[:start].strip():
        return ""
    rest = line[start:]
    if rest.startswith("//"):
        return _join([rest])
    # '/* ... */' eventuellement sur plusieurs lignes.
    fragments = [rest]
    i = index
    while "*/" not in fragments[-1] and i + 1 < len(lines):
        i += 1
        fragments.append(lines[i])
    if "*/" in fragments[-1]:
        fragments[-1] = fragments[-1][:fragments[-1].index("*/") + 2]
    return _join(fragments)


def _is_line_comment(stripped: str) -> bool:
    # '///<' seul sur sa ligne documente le membre PRECEDENT, pas le suivant.
    return stripped.startswith("//") and not stripped.startswith(("///<", "//!<"))


def leading_comment(lines: List[str], index: int) -> str:
    """Bloc de commentaires colle au-dessus de la ligne index (base 0)."""
    blocks = []   # du plus proche au plus lointain
    i = index - 1
    while i >= 0:
        stripped = lines[i].strip()
        if _is_line_comment(stripped):
            blocks.append([stripped])
            i -= 1
            continue
        if stripped.endswith("*/"):
            # Remonter jusqu'a l'ouverture ; le bloc doit etre seul sur ses
            # lignes, sinon c'est le commentaire de fin d'une autre ligne.
            j = i
            while j >= 0 and "/*" not in lines[j]:
                j -= 1
            if j < 0 or not lines[j].strip().startswith("/*") \
                    or lines[j].strip().startswith(("/**<", "/*!<")):
                break
            blocks.append([lines[k] for k in range(j, i + 1)])
            i = j - 1
            continue
        break
    return _join([frag for block in reversed(blocks) for frag in block])


def comment_at(lines: List[str], line_number: int) -> str:
    """Documentation de la declaration a line_number (base 1, comme castxml)."""
    index = line_number - 1
    if not 0 <= index < len(lines):
        return ""
    parts = [leading_comment(lines, index), trailing_comment(lines, index)]
    return " ".join(p for p in parts if p)


class SourceComments(object):
    """Lecture des headers, une seule fois par fichier."""

    def __init__(self):
        self._files: Dict[str, Optional[List[str]]] = {}

    def lines(self, path: str) -> Optional[List[str]]:
        if path not in self._files:
            self._files[path] = self._read(path)
        return self._files[path]

    @staticmethod
    def _read(path: str) -> Optional[List[str]]:
        # Les headers Windows sont souvent en cp1252 : on tente utf-8 d'abord.
        for encoding in ("utf-8", "cp1252"):
            try:
                with open(path, encoding=encoding) as fh:
                    return fh.read().splitlines()
            except UnicodeDecodeError:
                continue
            except OSError:
                return None
        return None

    def for_decl(self, decl) -> str:
        """Documentation d'une declaration pygccxml, '' si aucune."""
        loc = getattr(decl, "location", None)
        if loc is None or not getattr(loc, "file_name", None) or not getattr(loc, "line", None):
            return ""
        lines = self.lines(loc.file_name)
        if not lines:
            return ""
        return comment_at(lines, int(loc.line))
