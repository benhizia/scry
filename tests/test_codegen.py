"""Generation C++ et ligne de commande castxml, sans lancer castxml ni cl."""

import os
from pathlib import Path

from scry import model
from scry.codegen import generator
from scry.config import load_config
from scry.parsing import msvc_env

EXAMPLE_INI = Path(__file__).resolve().parent.parent / "scry.ini.example"


def _cfg():
    return load_config(EXAMPLE_INI)


# -- headers inclus par le C++ genere ---------------------------------------
def test_source_headers_viennent_des_structs():
    structs = [
        model.Struct(name="A", header=os.path.join("X:", "Data", "a.h")),
        model.Struct(name="B", header=os.path.join("X:", "Data", "b.h")),
        model.Struct(name="C", header=os.path.join("X:", "Data", "a.h")),
    ]
    assert generator.source_headers(structs) == ["a.h", "b.h"]


def test_source_headers_repli_sur_liste_h():
    # -H est cumulable : le parametre header arrive sous forme de liste.
    structs = [model.Struct(name="A")]
    assert generator.source_headers(structs, header=["Data/x.h", "Data/y.h"]) == ["x.h", "y.h"]


def test_render_inclut_chaque_header_et_jamais_une_chaine_vide():
    structs = [
        model.Struct(name="A", size=4, align=4, header="Data/a.h"),
        model.Struct(name="B", size=4, align=4, header="Data/b.h"),
    ]
    text = generator.render(structs, _cfg())
    assert '#include "a.h"' in text
    assert '#include "b.h"' in text
    assert '#include ""' not in text


# -- offsetof et templates ---------------------------------------------------
def test_offsetof_passe_par_un_alias_sans_virgule():
    s = model.Struct(name="ns::Ring<ns::T, 8>", size=16, align=8, header="r.h")
    s.fields = [model.Field(name="head", type_name="int", kind=model.FUNDAMENTAL,
                            offset=8, abs_offset=8, size=4)]
    text = generator.render([s], _cfg())
    alias = generator.struct_context(s, _cfg())["alias"]
    assert "," not in alias
    assert "using %s = ns::Ring<ns::T, 8>;" % alias in text
    assert "offsetof(%s, head)" % alias in text
    assert "offsetof(ns::Ring" not in text


# -- standard transmis a cl --------------------------------------------------
def test_cl_std_flag():
    assert msvc_env._cl_std_flag("c++14") == "/std:c++14"
    assert msvc_env._cl_std_flag("c++17") == "/std:c++17"
    assert msvc_env._cl_std_flag("gnu++20") == "/std:c++20"
    assert msvc_env._cl_std_flag("c++23") == "/std:c++latest"


def test_cl_with_std_donne_la_syntaxe_castxml_une_fois_entre_guillemets():
    # pygccxml ecrit --castxml-cc-msvc "<compiler_path>" : le resultat final
    # doit etre la forme ( cc options ) de castxml.
    cl = Path("C:/Program Files/VS/cl.exe")
    quoted = '"%s"' % msvc_env._cl_with_std(cl, "c++17")
    assert quoted == '"(" "%s" /std:c++17 ")"' % cl
