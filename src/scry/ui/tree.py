"""Arbre d'affichage, construit depuis le modele et non depuis pygccxml.

L'ancien TreeNode portait directement des declarations pygccxml, ce qui
obligeait chaque consommateur a connaitre l'API du parseur et a en subir les
cas particuliers. Ici un noeud ne contient que des donnees deja resolues.
"""

from typing import List, Optional

from scry import model


class TreeNode(object):
    def __init__(self, name, field=None, struct=None, parent=None):
        self.name = name
        self.field = field            # model.Field ou None
        self.struct = struct          # model.Struct pour la racine
        self.children = []            # type: List[TreeNode]
        self.parent = parent
        self.checked = False
        self.expanded = True
        self.is_printable_in_table_view = True
        self.id = self._make_id()

    def _make_id(self) -> str:
        if self.parent is None:
            return self.name
        return "%s/%s" % (self.parent.id, self.name)

    def add(self, child: "TreeNode") -> "TreeNode":
        child.parent = self
        child.id = child._make_id()
        self.children.append(child)
        return child

    # -- colonnes du tableau ------------------------------------------------
    @property
    def type_name(self) -> str:
        if self.struct is not None:
            return self.struct.kind
        return self.field.type_name if self.field else ""

    @property
    def offset(self) -> Optional[int]:
        if self.field is None or self.field.is_static:
            return None
        return self.field.abs_offset

    @property
    def size(self) -> Optional[int]:
        if self.struct is not None:
            return self.struct.size
        return self.field.size if self.field else None

    @property
    def note(self) -> str:
        if self.struct is not None:
            pad = self.struct.padding_bytes()
            return "padding %d o" % pad if pad else ""
        if self.field is None:
            return ""
        return {
            "cycle": "cycle interrompu",
            "depth": "profondeur max",
            "pointer": "pointeur non suivi",
            "opaque": "type incomplet",
        }.get(self.field.truncated, "")

    def walk(self, depth=0):
        yield self, depth
        for child in self.children:
            for item in child.walk(depth + 1):
                yield item


def build_tree(struct_info: model.Struct) -> TreeNode:
    """Convertit une Struct du modele en arbre affichable."""
    root = TreeNode(struct_info.name, struct=struct_info)

    def add_fields(parent_node: TreeNode, fields):
        for fld in fields:
            node = parent_node.add(TreeNode(fld.label(), field=fld))
            add_fields(node, fld.children)

    add_fields(root, struct_info.fields)
    return root


def build_forest(structs) -> List[TreeNode]:
    return [build_tree(s) for s in structs]
