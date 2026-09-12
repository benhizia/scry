"""Scry - visualiseur d'introspection C++.

A partir d'un .h fourni par un tiers, sans y toucher : la structure complete
avec offsets, tailles et padding, un inspecteur par membre, et le code C++
capable de lire ces memes donnees en memoire.

La fenetre est entierement occupee par une vue racine redimensionnee a chaque
frame : barre d'outils, puis trois colonnes a separateurs deplacables
(structures, membres, inspecteur), puis une barre d'etat.

Lancement : scry ui
Sans interface graphique : scry --help
"""

import os
import traceback

import glfw
import imgui
import OpenGL.GL as gl
from imgui.integrations.glfw import GlfwRenderer

from scry.codegen import generator as codegen
from scry.config import load_config
from scry.parsing.introspect import IntrospectionError, Introspector
from scry.runtime import memory
from scry.ui import inspector, render
from scry.ui import tree as tree_mod

MEMORY_NONE = "none"
MEMORY_DEMO = "demo"

ERROR_COLOR = (1.0, 0.45, 0.40, 1.0)
PADDING_COLOR = (0.95, 0.60, 0.25, 1.0)


def _flag(name):
    return getattr(imgui, name, 0)


ROOT_FLAGS = (_flag("WINDOW_NO_TITLE_BAR") | _flag("WINDOW_NO_RESIZE") | _flag("WINDOW_NO_MOVE")
              | _flag("WINDOW_NO_COLLAPSE") | _flag("WINDOW_NO_SAVED_SETTINGS")
              | _flag("WINDOW_NO_BRING_TO_FRONT_ON_FOCUS") | _flag("WINDOW_NO_SCROLLBAR")
              | _flag("WINDOW_NO_SCROLL_WITH_MOUSE"))
LAYOUT_FLAGS = _flag("TABLE_RESIZABLE") | _flag("TABLE_BORDERS_INNER_VERTICAL")
LIST_FLAGS = (_flag("TABLE_ROW_BACKGROUND") | _flag("TABLE_SCROLL_Y")
              | _flag("TABLE_SIZING_STRETCH_PROP"))
STRETCH = _flag("TABLE_COLUMN_WIDTH_STRETCH")
FIXED = _flag("TABLE_COLUMN_WIDTH_FIXED")


class AppState(object):
    """Tout l'etat mutable au meme endroit, plutot que disperse dans la boucle."""

    def __init__(self, cfg=None, header=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.header = header
        self.files = []          # headers effectivement parses
        self.structs = []
        self.problems = []       # rapport de parsing : echecs partiels, conflits
        self.error = ""          # erreur bloquante
        self.selected = 0        # index de la structure courante
        self.selection = None    # id du noeud selectionne dans l'arbre
        self.tree = None
        self.source = None
        self.memory = MEMORY_NONE
        self.filter = ""
        self._visible = (None, None, None)
        self.last_generated = ""
        self.reload()

    # -- lecture ------------------------------------------------------------
    def headers_label(self):
        return ", ".join(os.path.basename(p) for p in self.files) or "aucun header"

    @property
    def current(self):
        if 0 <= self.selected < len(self.structs):
            return self.structs[self.selected]
        return None

    @property
    def selected_node(self):
        if self.tree is None:
            return None
        return tree_mod.find(self.tree, self.selection) or self.tree

    def visible_ids(self):
        """Filtre memorise : recalcule seulement si l'arbre ou le texte change."""
        key = (id(self.tree), self.filter)
        if self._visible[:2] != key:
            ids = tree_mod.filter_ids(self.tree, self.filter) if self.tree else None
            self._visible = (key[0], key[1], ids)
        return self._visible[2]

    # -- actions ------------------------------------------------------------
    def reload(self):
        previous = self.current.name if self.current is not None else None
        self.error, self.problems = "", []
        introspector = Introspector(self.cfg)
        try:
            self.structs = introspector.parse(self.header)
            self.files = list(introspector.report.parsed)
            # Echecs partiels et conflits d'ABI : le modele est la, mais
            # incomplet ou douteux, cela doit se voir.
            self.problems = introspector.report.lines()
            if not self.structs:
                self.error = ("Aucune structure de premier niveau dans %s"
                              % self.headers_label())
        except IntrospectionError as exc:
            self.structs, self.error = [], str(exc)
        except Exception as exc:  # castxml, MSVC, template : on affiche au lieu de crasher
            self.structs = []
            self.error = "%s\n%s" % (exc, traceback.format_exc(limit=3))
        names = [s.name for s in self.structs]
        self.selected = names.index(previous) if previous in names else 0
        self.selection = None
        self.rebuild()

    def select_struct(self, index):
        if index != self.selected:
            self.selected = index
            self.selection = None
            self.rebuild()

    def set_memory(self, mode):
        if mode != self.memory:
            self.memory = mode
            self.rebuild()

    def rebuild(self):
        current = self.current
        if current is None:
            self.tree, self.source = None, None
            return
        self.tree = tree_mod.build_tree(current)
        if tree_mod.find(self.tree, self.selection) is None:
            self.selection = self.tree.id
        self.source = (memory.BufferSource(memory.make_demo_buffer(current))
                       if self.memory == MEMORY_DEMO else None)

    def generate(self):
        try:
            self.last_generated = codegen.generate(self.structs, self.cfg)
        except Exception as exc:
            self.error = "Generation impossible : %s" % exc


# ---------------------------------------------------------------------------
# Panneaux
# ---------------------------------------------------------------------------
def _toolbar(state, width):
    if imgui.button("Recharger"):
        state.reload()
    imgui.same_line()
    if imgui.button("Generer le C++"):
        state.generate()

    imgui.same_line()
    imgui.text_disabled("|")
    imgui.same_line()
    imgui.text("Memoire")
    imgui.same_line()
    if imgui.radio_button("aucune", state.memory == MEMORY_NONE):
        state.set_memory(MEMORY_NONE)
    imgui.same_line()
    if imgui.radio_button("motif de demo", state.memory == MEMORY_DEMO):
        state.set_memory(MEMORY_DEMO)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Buffer rempli par (i * 7 + 3) % 251, decode via les offsets.\n"
                          "Le visualiseur C++ (scry viewer) lit exactement les memes "
                          "octets :\nles valeurs des deux IHM doivent coincider.")

    imgui.same_line()
    imgui.text_disabled("|")
    imgui.same_line()
    imgui.text("Filtre")
    imgui.same_line()
    imgui.push_item_width(220)
    _, state.filter = imgui.input_text("##filtre", state.filter, 256)
    imgui.pop_item_width()

    cfg = state.cfg
    info = "%s    %s %s %s%s" % (state.headers_label(), cfg.compiler, cfg.arch, cfg.std,
                                 (" " + cfg.cl_flags) if cfg.cl_flags else "")
    x = width - imgui.calc_text_size(info)[0] - 16
    imgui.same_line()
    if x > imgui.get_cursor_pos_x():
        imgui.set_cursor_pos_x(x)
    imgui.text_disabled(info)
    imgui.separator()


def _problems(state):
    lines = ([state.error] if state.error else []) + list(state.problems)
    if not lines:
        return
    imgui.push_style_color(imgui.COLOR_TEXT, *ERROR_COLOR)
    expanded, _ = imgui.collapsing_header("%d incident(s)" % len(lines), None,
                                          _flag("TREE_NODE_DEFAULT_OPEN"))
    if expanded:
        for line in lines:
            imgui.text_wrapped(line)
    imgui.pop_style_color()


def _structs_panel(state, reserve):
    imgui.text("Structures")
    imgui.same_line()
    imgui.text_disabled("(%d)" % len(state.structs))
    if not imgui.begin_table("liste_structures", 3, LIST_FLAGS, 0.0, -reserve):
        return
    imgui.table_setup_scroll_freeze(0, 1)
    imgui.table_setup_column("Nom", STRETCH, 1.0)
    imgui.table_setup_column("sizeof", FIXED, 52)
    imgui.table_setup_column("pad", FIXED, 36)
    imgui.table_headers_row()
    for index, s in enumerate(state.structs):
        imgui.table_next_row()
        imgui.table_next_column()
        name = s.name + ("  (v)" if s.is_polymorphic else "")
        clicked, _ = imgui.selectable("%s##s%d" % (name, index), index == state.selected,
                                      _flag("SELECTABLE_SPAN_ALL_COLUMNS"))
        if clicked:
            state.select_struct(index)
        if imgui.is_item_hovered():
            imgui.set_tooltip("%s\n%s%s" % (s.name, s.header,
                                            "\n(v) : polymorphe, vptr a l'offset 0"
                                            if s.is_polymorphic else ""))
        imgui.table_next_column()
        imgui.text("-" if s.size is None else str(s.size))
        imgui.table_next_column()
        pad = s.padding_bytes()
        if pad:
            imgui.text_colored(str(pad), *PADDING_COLOR)
        else:
            imgui.text_disabled("0")
    imgui.end_table()


def _members_panel(state, reserve):
    s = state.current
    if s is None or state.tree is None:
        imgui.text_disabled("Aucune structure.")
        return
    imgui.text(s.name)
    imgui.same_line()
    imgui.text_disabled("sizeof %s   alignof %s   padding %s%s"
                        % (s.size, s.align, s.padding_bytes(),
                           "   polymorphe" if s.is_polymorphic else ""))
    picked = render.render_memory_map(state.tree, state.selected_node)
    if picked:
        state.selection = picked
    picked = render.render_members(state.tree, state.selection, state.source,
                                   state.visible_ids(), -reserve)
    if picked:
        state.selection = picked


def _inspector_panel(state, reserve):
    imgui.text("Inspecteur")
    imgui.begin_child("inspecteur", 0, -reserve, False)
    inspector.render(state.selected_node, state.current, state.source,
                     state.cfg.cpp_namespace)
    imgui.end_child()


def _status_bar(state):
    imgui.separator()
    parts = ["%d structure(s)" % len(state.structs),
             "%d header(s)" % len(state.files)]
    if state.source is not None:
        parts.append("memoire : motif de demo")
    if state.last_generated:
        parts.append("genere : %s" % state.last_generated)
    imgui.text_disabled("   |   ".join(parts))


def draw(state):
    io = imgui.get_io()
    width, height = io.display_size
    imgui.set_next_window_position(0, 0)
    imgui.set_next_window_size(width, height)
    imgui.push_style_var(imgui.STYLE_WINDOW_ROUNDING, 0.0)
    imgui.begin("Scry", False, ROOT_FLAGS)
    imgui.pop_style_var()

    _toolbar(state, width)
    _problems(state)

    # Hauteur laissee sous les colonnes pour la barre d'etat.
    reserve = imgui.get_frame_height() + 8
    if imgui.begin_table("layout", 3, LAYOUT_FLAGS):
        imgui.table_setup_column("Structures", STRETCH, 0.22)
        imgui.table_setup_column("Membres", STRETCH, 0.50)
        imgui.table_setup_column("Inspecteur", STRETCH, 0.28)
        imgui.table_next_row()
        imgui.table_next_column()
        _structs_panel(state, reserve)
        imgui.table_next_column()
        _members_panel(state, reserve)
        imgui.table_next_column()
        _inspector_panel(state, reserve)
        imgui.end_table()

    _status_bar(state)
    imgui.end()


def main(cfg=None, header=None):
    state = AppState(cfg=cfg, header=header)

    if not glfw.init():
        raise SystemExit("glfw.init a echoue")

    window = glfw.create_window(1600, 900, "Scry - introspection C++", None, None)
    if not window:
        glfw.terminate()
        raise SystemExit("Creation de la fenetre impossible")

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    try:
        while not glfw.window_should_close(window):
            glfw.poll_events()
            impl.process_inputs()
            imgui.new_frame()

            draw(state)

            gl.glClearColor(0.10, 0.10, 0.12, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            imgui.render()
            impl.render(imgui.get_draw_data())
            glfw.swap_buffers(window)
    finally:
        impl.shutdown()
        glfw.terminate()


if __name__ == "__main__":
    main()
