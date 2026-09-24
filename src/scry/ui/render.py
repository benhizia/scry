"""Rendu ImGui des membres : carte memoire et tree-table.

Une seule table, l'arbre dans la premiere colonne : chaque noeud occupe
exactement une ligne, l'arbre et les colonnes ne peuvent donc pas se decaler.
L'ancienne version juxtaposait deux vues, avec deux defilements et des
hauteurs de ligne differentes.

Les trous de padding sont des lignes a part entiere, a leur offset : on voit
ou ils sont, pas seulement combien il y en a.
"""

import imgui

from scry import model
from scry.runtime.memory import decode
from scry.ui import tree as tree_mod


# Les noms de constantes varient un peu selon les versions de pyimgui :
# on degrade proprement plutot que de planter au premier import.
def _flag(name, default=0):
    return getattr(imgui, name, default)


KIND_COLORS = {
    model.FUNDAMENTAL: (0.75, 0.85, 1.00, 1.0),
    model.ENUM: (0.95, 0.80, 0.50, 1.0),
    model.POINTER: (0.90, 0.60, 0.60, 1.0),
    model.ARRAY: (0.70, 0.90, 0.70, 1.0),
    model.STRUCT: (0.85, 0.85, 0.85, 1.0),
    model.UNION: (0.95, 0.70, 0.95, 1.0),
    model.CLASS: (0.85, 0.85, 0.85, 1.0),
    model.BASE: (0.65, 0.80, 0.90, 1.0),
    tree_mod.PADDING: (0.95, 0.60, 0.25, 0.85),
}
DEFAULT_COLOR = (0.85, 0.85, 0.85, 1.0)
NOTE_COLOR = (0.55, 0.55, 0.60, 1.0)

MEMBER_TABLE_FLAGS = (
    _flag("TABLE_BORDERS_INNER_VERTICAL")
    | _flag("TABLE_ROW_BACKGROUND")
    | _flag("TABLE_RESIZABLE")
    | _flag("TABLE_SCROLL_Y")
    | _flag("TABLE_SIZING_STRETCH_PROP")
)
TREE_BRANCH = (_flag("TREE_NODE_SPAN_FULL_WIDTH") | _flag("TREE_NODE_OPEN_ON_ARROW")
               | _flag("TREE_NODE_OPEN_ON_DOUBLE_CLICK"))
TREE_LEAF = (_flag("TREE_NODE_SPAN_FULL_WIDTH") | _flag("TREE_NODE_LEAF")
             | _flag("TREE_NODE_NO_TREE_PUSH_ON_OPEN"))
STRETCH = _flag("TABLE_COLUMN_WIDTH_STRETCH")
FIXED = _flag("TABLE_COLUMN_WIDTH_FIXED")


def color_of(node):
    return KIND_COLORS.get(node.kind, DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Tree-table
# ---------------------------------------------------------------------------
def render_members(root, selection, source=None, visible=None, height=0.0):
    """Tree-table des membres. Retourne l'id du noeud clique, ou None.

    height suit la convention ImGui : 0 remplit la hauteur restante, une
    valeur negative la remplit moins cette marge.
    """
    if not imgui.begin_table("membres", 5, MEMBER_TABLE_FLAGS, 0.0, height):
        return None
    imgui.table_setup_scroll_freeze(0, 1)
    imgui.table_setup_column("Nom", STRETCH, 3.0)
    imgui.table_setup_column("Type", STRETCH, 2.0)
    imgui.table_setup_column("Offset", FIXED, 60)
    imgui.table_setup_column("Taille", FIXED, 60)
    imgui.table_setup_column("Valeur", STRETCH, 2.0)
    imgui.table_headers_row()

    picked = []
    _row(root, selection, source, visible, picked, depth=0)
    imgui.end_table()
    return picked[-1] if picked else None


def _toggled_open():
    fn = getattr(imgui, "is_item_toggled_open", None)
    return bool(fn()) if fn else False


def _row(node, selection, source, visible, picked, depth):
    if visible is not None and node.id not in visible:
        return

    imgui.table_next_row()
    imgui.table_next_column()
    # L'id doit rester pousse jusqu'apres tree_pop : la pile d'ids est LIFO.
    imgui.push_id(node.id)

    leaf = not node.children
    flags = TREE_LEAF if leaf else TREE_BRANCH
    if not leaf and depth < 2:
        flags |= _flag("TREE_NODE_DEFAULT_OPEN")
    if node.id == selection:
        flags |= _flag("TREE_NODE_SELECTED")
    set_open = getattr(imgui, "set_next_item_open", None)
    if visible is not None and not leaf and set_open is not None:
        set_open(True)  # un filtre actif deplie les branches qui correspondent

    imgui.push_style_color(imgui.COLOR_TEXT, *color_of(node))
    opened = imgui.tree_node(node.label, flags)
    imgui.pop_style_color()
    if imgui.is_item_clicked() and not _toggled_open():
        picked.append(node.id)
    if imgui.is_item_hovered() and node.field is not None and node.field.access_path:
        imgui.set_tooltip(node.field.access_path)

    imgui.table_next_column()
    imgui.text(node.type_name)
    if node.note:
        imgui.same_line()
        imgui.text_colored("[%s]" % node.note, *NOTE_COLOR)

    imgui.table_next_column()
    if node.offset is not None:
        imgui.text(str(node.offset))
        if imgui.is_item_hovered():
            imgui.set_tooltip("0x%X" % node.offset)

    imgui.table_next_column()
    if node.size is not None:
        imgui.text("%d o" % node.size)

    imgui.table_next_column()
    if source is not None and node.field is not None:
        value = decode(source, node.field)
        if value is not None:
            imgui.text(value)

    if opened and not leaf:
        for child in node.children:
            _row(child, selection, source, visible, picked, depth + 1)
        imgui.tree_pop()
    imgui.pop_id()


# ---------------------------------------------------------------------------
# Carte memoire
# ---------------------------------------------------------------------------
def _u32(rgb, alpha=1.0, factor=1.0):
    r, g, b = rgb[:3]
    return imgui.get_color_u32_rgba(r * factor, g * factor, b * factor, alpha)


def render_memory_map(root, selected=None, height=24.0):
    """Barre de sizeof octets : un segment par membre de premier niveau,
    padding hachure en orange, plage du noeud selectionne encadree.
    Retourne l'id du segment clique, ou None."""
    struct = root.struct
    total = struct.size if struct is not None else None
    if not total:
        return None

    width = max(imgui.get_content_region_available()[0], 50.0)
    x0, y0 = imgui.get_cursor_screen_pos()
    imgui.invisible_button("carte_memoire", width, height)
    hovered = imgui.is_item_hovered()
    clicked = imgui.is_item_clicked()
    mouse_x = imgui.get_mouse_pos()[0]

    draw = imgui.get_window_draw_list()
    scale = width / float(total)
    y1 = y0 + height
    under_mouse = None

    for index, (start, end, node) in enumerate(tree_mod.top_level_segments(root)):
        a = x0 + start * scale
        b = max(x0 + end * scale, a + 1.0)
        if node.is_padding:
            draw.add_rect_filled(a, y0, b, y1, _u32(KIND_COLORS[tree_mod.PADDING], 0.25))
            x = a
            while x < b:
                x_end = min(x + height, b)
                draw.add_line(x, y1, x_end, y1 - (x_end - x),
                              _u32(KIND_COLORS[tree_mod.PADDING], 0.9))
                x += 6.0
        else:
            # Deux teintes alternees pour distinguer des membres voisins.
            factor = 0.55 if index % 2 else 0.42
            draw.add_rect_filled(a, y0, b, y1, _u32(color_of(node), 1.0, factor))
        draw.add_line(a, y0, a, y1, _u32((0.08, 0.08, 0.10)))
        if hovered and a <= mouse_x < b:
            under_mouse = node

    draw.add_rect(x0, y0, x0 + width, y1, _u32((0.5, 0.5, 0.55)))

    if selected is not None and selected.offset is not None and selected.size:
        a = x0 + selected.offset * scale
        b = max(x0 + (selected.offset + selected.size) * scale, a + 2.0)
        draw.add_rect(a - 1, y0 - 2, b + 1, y1 + 2, _u32((1.0, 1.0, 1.0)), 0.0, 0, 2.0)

    if under_mouse is not None:
        imgui.set_tooltip("%s\n@%d  %d o" % (under_mouse.label, under_mouse.offset,
                                             under_mouse.size))

    # Graduations dessinees directement : un same_line positionne dans une
    # cellule de table depend de l'origine de la colonne et se perd.
    muted = _u32((0.55, 0.55, 0.60))
    line_h = imgui.get_text_line_height()
    draw.add_text(x0, y1 + 2, muted, "0")
    end_label = "%d o" % total
    draw.add_text(x0 + width - imgui.calc_text_size(end_label)[0], y1 + 2, muted, end_label)
    if selected is not None and selected.offset and selected.size and not selected.is_root:
        mark = "@%d" % selected.offset
        mx = min(max(x0 + selected.offset * scale, x0 + 20),
                 x0 + width - imgui.calc_text_size(end_label)[0] - imgui.calc_text_size(mark)[0] - 12)
        draw.add_text(mx, y1 + 2, _u32((1.0, 1.0, 1.0)), mark)
    imgui.dummy(width, line_h + 6)

    if clicked and under_mouse is not None:
        return under_mouse.id
    return None
