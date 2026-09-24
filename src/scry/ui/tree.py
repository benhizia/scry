"""Arbre d'affichage, construit depuis le modele et non depuis pygccxml.

Un noeud ne contient que des donnees deja resolues : un membre du modele, la
structure racine, ou un trou de padding. Les trous sont de vrais noeuds, places
a leur offset parmi les membres : c'est ce qui permet de voir OU se trouve le
padding, et pas seulement combien il y en a.

Tout ici est pur Python et se teste sans imgui.
"""

from typing import List, Optional, Set, Tuple

from scry import model

PADDING = "padding"


class TreeNode(object):
    def __init__(self, name, field=None, struct=None, span=None, label=None):
        self.name = name
        self.field = field            # model.Field ou None
        self.struct = struct          # model.Struct pour la racine
        self.span = span              # (debut, fin) absolus pour un trou
        self.label = label or name    # texte affiche
        self.children = []            # type: List[TreeNode]
        self.parent = None
        self.id = name

    def add(self, child: "TreeNode") -> "TreeNode":
        child.parent = self
        child.id = "%s/%s" % (self.id, child.name)
        self.children.append(child)
        return child

    # -- nature -------------------------------------------------------------
    @property
    def is_root(self) -> bool:
        return self.struct is not None

    @property
    def is_padding(self) -> bool:
        return self.span is not None

    @property
    def kind(self) -> str:
        if self.is_padding:
            return PADDING
        if self.is_root:
            return self.struct.kind
        return self.field.kind

    # -- colonnes -----------------------------------------------------------
    @property
    def type_name(self) -> str:
        if self.is_padding:
            return ""
        if self.is_root:
            return self.struct.name
        return self.field.type_name

    @property
    def offset(self) -> Optional[int]:
        """Offset absolu depuis la racine."""
        if self.is_padding:
            return self.span[0]
        if self.is_root:
            return 0
        if self.field.is_static:
            return None
        return self.field.abs_offset

    @property
    def size(self) -> Optional[int]:
        if self.is_padding:
            return self.span[1] - self.span[0]
        if self.is_root:
            return self.struct.size
        return self.field.size

    @property
    def note(self) -> str:
        if self.field is None:
            return ""
        return TRUNCATION_NOTES.get(self.field.truncated, "")

    def walk(self, depth=0):
        yield self, depth
        for child in self.children:
            for item in child.walk(depth + 1):
                yield item


TRUNCATION_NOTES = {
    "cycle": "cycle interrompu",
    "depth": "profondeur max",
    "pointer": "pointeur non suivi",
    "opaque": "type incomplet",
    "virtual": "base virtuelle",
    "offset": "offset inconnu",
}


def _add_members(parent: TreeNode, fields: List[model.Field], base_abs: int,
                 size: Optional[int], with_holes: bool, polymorphic: bool = False):
    for _, fld, hole in model.layout_items(fields, size, with_holes):
        if hole is not None:
            start, end = hole
            span = (base_abs + start, base_abs + end)
            parent.add(TreeNode("#pad@%d" % span[0], span=span,
                                label=model.hole_label(start, end, polymorphic and start == 0)))
            continue
        node = parent.add(TreeNode(fld.label(), field=fld))
        _add_members(node, fld.children, fld.abs_offset, fld.size,
                     with_holes=model.shows_holes(fld), polymorphic=fld.is_polymorphic)


def build_tree(struct_info: model.Struct) -> TreeNode:
    """Convertit une Struct du modele en arbre affichable, trous compris."""
    root = TreeNode(struct_info.name, struct=struct_info)
    _add_members(root, struct_info.fields, 0, struct_info.size, with_holes=True,
                 polymorphic=struct_info.is_polymorphic)
    return root


def find(root: TreeNode, node_id: Optional[str]) -> Optional[TreeNode]:
    if node_id is None:
        return None
    for node, _ in root.walk():
        if node.id == node_id:
            return node
    return None


def filter_ids(root: TreeNode, text: str) -> Optional[Set[str]]:
    """Noeuds a afficher pour un filtre : ceux qui correspondent et leurs
    ancetres. None si le filtre est vide, c'est-a-dire tout afficher."""
    needle = text.strip().lower()
    if not needle:
        return None
    keep = set()

    def visit(node: TreeNode) -> bool:
        matched = False
        for child in node.children:
            if visit(child):
                matched = True
        if not node.is_padding and (needle in node.label.lower()
                                    or needle in node.type_name.lower()):
            matched = True
        if matched:
            keep.add(node.id)
        return matched

    visit(root)
    keep.add(root.id)
    return keep


def top_level_segments(root: TreeNode) -> List[Tuple[int, int, TreeNode]]:
    """Segments (debut, fin, noeud) du premier niveau, pour la carte memoire."""
    out = []
    for child in root.children:
        if child.offset is None or not child.size:
            continue
        out.append((child.offset, child.offset + child.size, child))
    return out
