"""Rendu ImGui de l'arbre et du tableau.

Change par rapport a la version precedente :

  * un vrai tree_node avec repli, au lieu d'un selectable detourne, ce qui
    supprime les problemes d'alignement et donne le comportement attendu au
    clic ;
  * une seule passe : l'arbre et le tableau parcourent la meme liste de noeuds
    visibles, donc les lignes restent alignees quel que soit le repli ;
  * une colonne Valeur alimentee par une source memoire optionnelle. C'est la
    maquette du visualiseur live : le C++ genere fera la meme chose a partir
    des memes offsets.
"""

import imgui

from scry import model
from scry.runtime.memory import decode

COLUMNS = ("Nom", "Type", "Offset", "Taille", "Valeur", "Note")

# Les noms de constantes varient un peu selon les versions de pyimgui :
# on degrade proprement plutot que de planter au premier import.
def _flag(name, default=0):
    return getattr(imgui, name, default)


TABLE_FLAGS = (
    _flag("TABLE_BORDERS")
    | _flag("TABLE_ROW_BACKGROUND")
    | _flag("TABLE_RESIZABLE")
    | _flag("TABLE_SIZING_STRETCH_PROP")
    | _flag("TABLE_SCROLL_Y")
)

KIND_COLORS = {
    model.FUNDAMENTAL: (0.75, 0.85, 1.00, 1.0),
    model.ENUM: (0.95, 0.80, 0.50, 1.0),
    model.POINTER: (0.90, 0.60, 0.60, 1.0),
    model.ARRAY: (0.70, 0.90, 0.70, 1.0),
    model.STRUCT: (0.85, 0.85, 0.85, 1.0),
    model.UNION: (0.95, 0.70, 0.95, 1.0),
    model.CLASS: (0.85, 0.85, 0.85, 1.0),
}


def render_tree_and_table(roots, source=None, tree_width=420):
    """roots : liste de TreeNode. source : MemorySource ou None."""
    visible = []

    imgui.begin_child("tree_view", width=tree_width, border=True)
    for root in roots:
        _render_node(root, visible)
    imgui.end_child()

    imgui.same_line()
    _render_table(visible, source)


def _render_node(node, visible, depth=0):
    imgui.push_id(node.id)

    flags = _flag("TREE_NODE_DEFAULT_OPEN") if node.children else _flag("TREE_NODE_LEAF")
    flags |= _flag("TREE_NODE_SPAN_AVAILABLE_WIDTH")

    _, node.checked = imgui.checkbox("##chk", node.checked)
    imgui.same_line()

    color = KIND_COLORS.get(node.field.kind if node.field else model.STRUCT, (1, 1, 1, 1))
    imgui.push_style_color(imgui.COLOR_TEXT, *color)
    opened = imgui.tree_node(node.name, flags)
    imgui.pop_style_color()

    node.expanded = bool(opened)
    if node.is_printable_in_table_view:
        visible.append((node, depth))

    if opened:
        for child in node.children:
            _render_node(child, visible, depth + 1)
        imgui.tree_pop()

    imgui.pop_id()


def _render_table(visible, source):
    imgui.begin_child("table_view", border=True)

    if imgui.begin_table("details_table", len(COLUMNS), TABLE_FLAGS):
        for name in COLUMNS:
            imgui.table_setup_column(name)
        imgui.table_headers_row()

        for node, depth in visible:
            imgui.table_next_row()

            imgui.table_next_column()
            if depth:
                imgui.dummy(depth * 14, 0)
                imgui.same_line()
            imgui.text(node.name)

            imgui.table_next_column()
            imgui.text(node.type_name)

            imgui.table_next_column()
            imgui.text("-" if node.offset is None else str(node.offset))

            imgui.table_next_column()
            imgui.text("-" if node.size is None else "%d o" % node.size)

            imgui.table_next_column()
            value = decode(source, node.field) if (source and node.field) else None
            imgui.text(value if value is not None else "")

            imgui.table_next_column()
            if node.note:
                imgui.text_colored(node.note, 1.0, 0.75, 0.35, 1.0)

        imgui.end_table()
    imgui.end_child()


def render_struct_summary(struct_info):
    """Bandeau ABI : ce que le C++ genere verifiera par static_assert."""
    imgui.text("sizeof = %s o" % struct_info.size)
    imgui.same_line()
    imgui.text("| alignof = %s o" % struct_info.align)
    imgui.same_line()
    pad = struct_info.padding_bytes()
    if pad:
        imgui.text_colored("| padding = %d o" % pad, 1.0, 0.75, 0.35, 1.0)
    else:
        imgui.text("| padding = 0 o")
    if struct_info.is_polymorphic:
        imgui.text_colored(
            "Type polymorphe : un pointeur de vtable occupe le debut de l'objet, "
            "les offsets en tiennent compte.", 1.0, 0.6, 0.4, 1.0)
