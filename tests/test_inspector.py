"""Inspecteur : facts() est pur et se teste sans imgui."""

from scry import model
from scry.runtime.memory import BufferSource, make_demo_buffer
from scry.ui import inspector, tree


def _f(name, offset, size, **kw):
    kw.setdefault("type_name", "int")
    kw.setdefault("kind", model.FUNDAMENTAL)
    kw.setdefault("abs_offset", offset)
    kw.setdefault("access_path", "obj.%s" % name)
    return model.Field(name=name, offset=offset, size=size, **kw)


def _struct(name="S"):
    return model.Struct(name=name, size=16, align=8, header="Data/s.h", fields=[
        _f("a", 0, 4), _f("b", 8, 4)])


def _node(root, label):
    return next(n for n, _ in root.walk() if n.label == label)


def test_racine():
    s = _struct()
    d = dict(inspector.facts(tree.build_tree(s), s))
    assert d["sizeof"] == "16 o"
    assert d["Padding"] == "8 o"
    assert d["Trous"] == "4 o @4, 4 o @12"
    assert d["Header"] == "Data/s.h"


def test_membre_offsets_offsetof_lecture():
    s = _struct()
    d = dict(inspector.facts(_node(tree.build_tree(s), "b"), s))
    assert d["Chemin"] == "obj.b"
    assert d["Offset absolu"] == "8  (0x8)"
    assert d["offsetof"] == "offsetof(S, b)"
    assert d["Lecture C++"] == "read_at<int>(base, 8)"


def test_offsetof_d_un_template_passe_par_l_alias():
    s = _struct("ns::R<int, 8>")
    d = dict(inspector.facts(_node(tree.build_tree(s), "a"), s))
    assert d["offsetof"] == "offsetof(scry::abi::abi_ns__R_int__8_, a)"


def test_champ_de_bits():
    s = model.Struct(name="B", size=8, fields=[
        _f("bits", 4, 1, type_name="unsigned char", bit_width=3, bit_offset=2)])
    d = dict(inspector.facts(_node(tree.build_tree(s), "bits : 3"), s))
    assert d["Bits"] == "octet 4, bit 2, largeur 3"
    assert d["Masque"] == "0x1C sur une unite de 1 o"
    assert "offsetof" not in d          # invalide sur un champ de bits
    assert d["Lecture C++"] == "read_bits(base, 4, 1, 2, 3)"


def test_raison_du_padding():
    s = _struct()
    root = tree.build_tree(s)
    holes = [n for n in root.children if n.is_padding]
    assert dict(inspector.facts(holes[0], s))["Raison"].startswith("octets inseres")
    assert dict(inspector.facts(holes[1], s))["Raison"].startswith("padding de fin")


def test_valeur_et_octets_avec_une_source():
    s = _struct()
    source = BufferSource(make_demo_buffer(s))
    d = dict(inspector.facts(_node(tree.build_tree(s), "a"), s, source))
    assert d["Octets"] == "03 0A 11 18"
    assert d["Valeur"] == str(int.from_bytes(bytes([3, 10, 17, 24]), "little", signed=True))
