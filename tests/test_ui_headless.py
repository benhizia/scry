"""IHM Python executee sans fenetre : contexte ImGui, frames, trois sources.

Aucun OpenGL : new_frame, draw, render, sans rendu des draw lists. Saute si
pyimgui ou castxml manque.
"""

import shutil
import struct
import uuid
from multiprocessing import shared_memory

import pytest

imgui = pytest.importorskip("imgui")
pytest.importorskip("glfw")
pytestmark = pytest.mark.skipif(not shutil.which("castxml"), reason="castxml absent")

from scry.config import load_config  # noqa: E402
from scry.runtime import shm  # noqa: E402

HEADER_H = "#pragma once\nnamespace demo { struct Etat { int mode; double vitesse; }; " \
           "struct Autre { char c; }; }\n"


@pytest.fixture
def ui(tmp_path):
    from scry.ui import app
    (tmp_path / "demo.h").write_text(HEADER_H, encoding="utf-8")
    segment = "scry_ui_%s" % uuid.uuid4().hex[:8]
    ini = tmp_path / "scry.ini"
    ini.write_text("[paths]\nheaders = demo.h\ncache =\n[castxml]\ncompiler = gcc\n"
                   "extra_cflags = -Wno-pragma-once-outside-header\n"
                   "[shm]\nname = %s\n" % segment, encoding="utf-8")
    ctx = imgui.create_context()
    io = imgui.get_io()
    io.display_size = (1600, 900)
    io.fonts.get_tex_data_as_rgba32()
    state = app.AppState(cfg=load_config(ini))
    yield app, state, segment
    state.disconnect_shm()
    imgui.destroy_context(ctx)


def _frames(app, state, n=3):
    for _ in range(n):
        imgui.new_frame()
        app.draw(state)
        imgui.render()


def test_frames_sans_memoire_et_en_demo(ui):
    app, state, _ = ui
    assert [s.name for s in state.structs] == ["demo::Autre", "demo::Etat"]
    _frames(app, state)
    state.set_memory(app.MEMORY_DEMO)
    _frames(app, state)
    assert state.source is not None


def test_memoire_partagee(ui):
    app, state, segment = ui
    state.set_memory(app.MEMORY_SHM)
    assert state.memory == app.MEMORY_NONE and "producteur" in state.shm_error
    _frames(app, state)

    payload = struct.pack("<i4xd", 7, 2.5)
    head = struct.pack("<IIIIQQ", shm.MAGIC, shm.VERSION, 128, len(payload), 2, 0)
    raw = head + b"demo::Etat".ljust(96, b"\0") + payload
    seg = shared_memory.SharedMemory(name=segment, create=True, size=len(raw))
    try:
        seg.buf[:len(raw)] = raw
        state.set_memory(app.MEMORY_SHM)
        # La structure annoncee par le segment est selectionnee.
        assert state.memory == app.MEMORY_SHM and state.current.name == "demo::Etat"
        _frames(app, state)
        from scry.runtime.memory import decode
        mode = state.current.fields[0]
        assert decode(state.source, mode) == "7"
        # Nouvelle publication : relue a la frame suivante.
        struct.pack_into("<i", seg.buf, 128, 9)
        struct.pack_into("<Q", seg.buf, 16, 4)
        _frames(app, state, 1)
        assert decode(state.source, mode) == "9"
        assert state.shm.publications == 2
        # Autre structure, autre taille : pas de decodage.
        state.select_struct(0)
        assert state.source is None
        _frames(app, state)
        state.set_memory(app.MEMORY_NONE)
        assert state.shm is None
    finally:
        state.disconnect_shm()
        seg.close()
        seg.unlink()
