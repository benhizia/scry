"""BuffyPyGen - visualiseur et generateur d'introspection C++.

Demonstrateur du couple castxml + pygccxml : a partir d'un simple .h fourni par
un tiers, sans y toucher, on obtient la structure complete avec offsets et
tailles, un visualiseur, et le code C++ capable de lire ces memes donnees en
memoire.

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
from scry.runtime import memory
from scry.ui.tree import build_tree
from scry.config import load_config
from scry.parsing.introspect import IntrospectionError, Introspector
from scry.ui.render import render_struct_summary, render_tree_and_table


class AppState(object):
    """Tout l'etat mutable au meme endroit, plutot que dispersé dans la boucle."""

    def __init__(self, cfg=None, header=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.header = header
        self.files = []          # headers effectivement parses
        self.structs = []
        self.error = ""
        self.selected = 0
        self.tree = None
        self.source = None
        self.use_demo_memory = False
        self.last_generated = ""
        self.reload()

    def headers_label(self):
        return ", ".join(os.path.basename(p) for p in self.files) or "aucun header"

    @property
    def current(self):
        if 0 <= self.selected < len(self.structs):
            return self.structs[self.selected]
        return None

    def reload(self):
        self.error = ""
        introspector = Introspector(self.cfg)
        try:
            self.structs = introspector.parse(self.header)
            self.files = list(introspector.report.parsed)
            # Echecs partiels et conflits d'ABI : le modele est la, mais
            # incomplet ou douteux, cela doit se voir.
            problems = introspector.report.lines()
            if problems:
                self.error = "\n".join(problems)
            elif not self.structs:
                self.error = ("Aucune structure de premier niveau dans %s"
                              % self.headers_label())
        except IntrospectionError as exc:
            self.structs, self.error = [], str(exc)
        except Exception as exc:  # castxml, MSVC, template : on affiche au lieu de crasher
            self.structs = []
            self.error = "%s\n%s" % (exc, traceback.format_exc(limit=3))
        self.selected = 0
        self.rebuild()

    def rebuild(self):
        current = self.current
        if current is None:
            self.tree, self.source = None, None
            return
        self.tree = build_tree(current)
        self.source = (memory.BufferSource(memory.make_demo_buffer(current))
                       if self.use_demo_memory else None)

    def generate(self):
        try:
            self.last_generated = codegen.generate(self.structs, self.cfg)
        except Exception as exc:
            self.error = "Generation impossible : %s" % exc


def draw_control_panel(state):
    imgui.begin("Controles")

    imgui.text_disabled(state.headers_label())
    imgui.text_disabled("%s %s / %s" % (state.cfg.compiler, state.cfg.arch, state.cfg.std))
    imgui.separator()

    if state.error:
        imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.45, 0.4, 1.0)
        imgui.text_wrapped(state.error)
        imgui.pop_style_color()
        imgui.separator()

    if imgui.button("Recharger le header"):
        state.reload()
    imgui.same_line()
    if imgui.button("Generer le C++"):
        state.generate()

    if state.structs:
        names = [s.name for s in state.structs]
        changed, state.selected = imgui.combo("Structure", state.selected, names)
        if changed:
            state.rebuild()

        toggled, state.use_demo_memory = imgui.checkbox(
            "Memoire de demonstration", state.use_demo_memory)
        if toggled:
            state.rebuild()
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Remplit un buffer avec un motif connu et le decode via les offsets.\n"
                "Remplacer BufferSource par SharedMemorySource pour du live.")

        imgui.separator()
        if state.current is not None:
            render_struct_summary(state.current)

    if state.last_generated:
        imgui.separator()
        imgui.text_wrapped("Genere : %s" % os.path.basename(state.last_generated))

    imgui.end()


def main(cfg=None, header=None):
    state = AppState(cfg=cfg, header=header)

    if not glfw.init():
        raise SystemExit("glfw.init a echoue")

    window = glfw.create_window(1600, 900, "BuffyPyGen - introspection C++", None, None)
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

            draw_control_panel(state)

            imgui.begin("Hierarchie")
            if state.tree is not None:
                render_tree_and_table([state.tree], state.source)
            else:
                imgui.text_disabled("Rien a afficher.")
            imgui.end()

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
