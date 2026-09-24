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


def test_render_inclut_chaque_header_et_jamais_une_chaine_vide(tmp_path):
    structs = [
        model.Struct(name="A", size=4, align=4, header="Data/a.h"),
        model.Struct(name="B", size=4, align=4, header="Data/b.h"),
    ]
    ini = tmp_path / "scry.ini"
    ini.write_text("[codegen]\nemit_abi_checks = false\n", encoding="utf-8")
    # Les sources sont incluses par le header ABI, ou directement par le
    # header ImGui quand les assertions sont desactivees : jamais les deux,
    # sans quoi un header tiers sans garde d'inclusion serait redefini.
    abi = generator.render(structs, _cfg(), "abi_checks.h.j2")
    for text in (abi, generator.render(structs, load_config(ini))):
        assert '#include "a.h"' in text
        assert '#include "b.h"' in text
        assert '#include ""' not in text
    assert '#include "a.h"' not in generator.render(structs, _cfg())


# -- offsetof et templates ---------------------------------------------------
def test_offsetof_passe_par_un_alias_sans_virgule():
    s = model.Struct(name="ns::Ring<ns::T, 8>", size=16, align=8, header="r.h")
    s.fields = [model.Field(name="head", type_name="int", kind=model.FUNDAMENTAL,
                            offset=8, abs_offset=8, size=4)]
    text = generator.render([s], _cfg(), "abi_checks.h.j2")
    alias = generator.struct_context(s, _cfg())["alias"]
    assert "," not in alias
    assert "using %s = ns::Ring<ns::T, 8>;" % alias in text
    assert "offsetof(%s, head)" % alias in text
    assert "alignof(%s) == 8u" % alias in text
    # Le nom complet reste dans le message, jamais comme argument de la macro.
    assert "static_assert(offsetof(ns::Ring" not in text


def test_rendu_cpp_en_tree_table_avec_padding_et_registre():
    s = model.Struct(name="P", size=16, align=8, header="p.h", fields=[
        model.Field(name="a", type_name="int", kind=model.FUNDAMENTAL, offset=0,
                    abs_offset=0, size=4, access_path="obj.a"),
        model.Field(name="d", type_name="double", kind=model.FUNDAMENTAL, offset=8,
                    abs_offset=8, size=8, access_path="obj.d"),
    ])
    text = generator.render([s], _cfg())
    # Memes lignes que l'IHM Python : le trou entre a et d est une ligne.
    assert '"[padding 4 o]##pad4"' in text
    assert text.index('"a##0"') < text.index("##pad4") < text.index('"d##8"')
    assert 'ImGui::Text("%.6g"' in text
    assert "inline const StructInfo kStructs[]" in text
    assert "&detail::default_instance<P>" in text


def test_header_abi_sans_imgui_et_inclus_par_le_header_imgui():
    s = model.Struct(name="A", size=4, align=4, header="Data/a.h")
    abi = generator.render([s], _cfg(), "abi_checks.h.j2")
    assert "imgui" not in abi.lower().replace("imgui ni code", "")
    assert '#include "a.h"' in abi
    ui = generator.render([s], _cfg())
    assert '#include "%s"' % _cfg().abi_header in ui
    assert "static_assert" not in ui


# -- standard transmis a cl --------------------------------------------------
def test_cl_std_flag():
    assert msvc_env._cl_std_flag("c++14") == "/std:c++14"
    assert msvc_env._cl_std_flag("c++17") == "/std:c++17"
    assert msvc_env._cl_std_flag("gnu++20") == "/std:c++20"
    assert msvc_env._cl_std_flag("c++23") == "/std:c++latest"


def test_cl_command_donne_la_syntaxe_castxml_une_fois_entre_guillemets():
    # pygccxml ecrit --castxml-cc-msvc "<compiler_path>" : le resultat final
    # doit etre la forme ( cc options ) de castxml.
    cl = Path("C:/Program Files/VS/cl.exe")
    quoted = '"%s"' % msvc_env._cl_command(cl, "c++17")
    assert quoted == '"(" "%s" /std:c++17 ")"' % cl


def test_cl_command_transmet_cl_flags():
    cl = Path("C:/VS/cl.exe")
    quoted = '"%s"' % msvc_env._cl_command(cl, "c++17", "  /MDd /D_DEBUG ")
    assert quoted == '"(" "%s" /std:c++17 /MDd /D_DEBUG ")"' % cl


def test_membre_non_public_sans_offsetof():
    s = model.Struct(name="C", size=8, align=4, header="c.h", fields=[
        model.Field(name="pub", type_name="int", kind=model.FUNDAMENTAL, offset=0,
                    abs_offset=0, size=4, access_path="obj.pub"),
        model.Field(name="priv_", type_name="int", kind=model.FUNDAMENTAL, offset=4,
                    abs_offset=4, size=4, access_path="obj.priv_", access="private"),
    ])
    abi = generator.render([s], _cfg(), "abi_checks.h.j2")
    assert "offsetof(abi_C, pub)" in abi
    assert "priv_" not in abi


def test_pas_d_instance_si_un_constructeur_est_hors_du_header():
    ok = model.Struct(name="Ok", size=4, align=4, header="o.h")
    ko = model.Struct(name="Ko", size=4, align=4, header="o.h", inline_constructible=False)
    text = generator.render([ok, ko], _cfg())
    assert "&detail::default_instance<Ok>" in text
    assert "&detail::default_instance<Ko>" not in text
    assert "&detail::no_instance}" in text


def _base(type_name, offset, children, **kw):
    return model.Field(name="", type_name=type_name, kind=model.BASE, offset=offset,
                       abs_offset=offset, size=16, access_path="obj",
                       children=children, **kw)


def test_offsetof_des_membres_herites_et_noms_ambigus():
    a = _base("A", 0, [
        model.Field(name="x", type_name="int", kind=model.FUNDAMENTAL, offset=0,
                    abs_offset=0, size=4, access_path="obj.x"),
        model.Field(name="dup", type_name="int", kind=model.FUNDAMENTAL, offset=4,
                    abs_offset=4, size=4, access_path="obj.dup"),
    ])
    virt = _base("V", 0, [], truncated="virtual")
    priv = _base("P", 0, [
        model.Field(name="hidden", type_name="int", kind=model.FUNDAMENTAL, offset=0,
                    abs_offset=0, size=4, access_path="obj.hidden")], access="private")
    fields = [a, virt, priv,
              model.Field(name="dup", type_name="int", kind=model.FUNDAMENTAL, offset=16,
                          abs_offset=16, size=4, access_path="obj.dup")]
    assert generator._offsetof_targets(fields) == [("x", 0)]
    assert generator._offsetof_targets(fields, inherited=False) == [("dup", 16)]


def test_base_polymorphe_rendue_avec_son_vptr():
    base = _base("Poly", 0, [
        model.Field(name="p", type_name="int", kind=model.FUNDAMENTAL, offset=8,
                    abs_offset=8, size=4, access_path="obj.p")], is_polymorphic=True)
    s = model.Struct(name="D", size=16, align=8, header="d.h", is_polymorphic=True,
                     fields=[base])
    text = generator.render([s], _cfg())
    assert '"[vptr 8 o]##pad0"' in text
    assert '"(base) Poly##0"' in text
    assert "detail::kColorBase" in text
