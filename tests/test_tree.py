"""Arbre d'affichage : trous de padding, filtre, segments de la carte memoire."""

from scry import model
from scry.ui import tree


def _f(name, offset, size, kind=model.FUNDAMENTAL, children=None, base=0, **kw):
    return model.Field(name=name, type_name=kw.pop("type_name", "int"), kind=kind,
                       offset=offset, abs_offset=base + offset, size=size,
                       children=children or [], **kw)


def test_padding_spans_trou_interieur_et_padding_de_fin():
    fields = [_f("a", 0, 1), _f("b", 4, 4), _f("c", 8, 1)]
    assert model.padding_spans(fields, 12) == [(1, 4), (9, 12)]


def test_padding_spans_union_et_bitfields_sans_faux_trou():
    fields = [_f("x", 0, 4), _f("y", 0, 2), _f("bits", 4, 1, bit_width=3),
              _f("more", 4, 1, bit_width=5)]
    assert model.padding_spans(fields, 8) == [(5, 8)]


def test_padding_bytes_inchange():
    s = model.Struct(name="S", size=12, fields=[_f("a", 0, 1), _f("b", 4, 4), _f("c", 8, 1)])
    assert s.padding_bytes() == 6
    assert model.Struct(name="V", size=None).padding_bytes() is None
    assert model.Struct(name="E", size=4).padding_bytes() == 4


def test_arbre_place_les_trous_parmi_les_membres():
    s = model.Struct(name="S", size=12, fields=[_f("a", 0, 1), _f("b", 4, 4), _f("c", 8, 1)])
    root = tree.build_tree(s)
    labels = [c.label for c in root.children]
    assert labels == ["a", "[padding 3 o]", "b", "c", "[padding 3 o]"]
    pad = root.children[1]
    assert pad.is_padding and pad.offset == 1 and pad.size == 3


def test_trous_dans_un_agregat_imbrique_en_offsets_absolus():
    inner = [_f("x", 0, 1, base=16), _f("y", 8, 8, base=16)]
    s = model.Struct(name="S", size=32, fields=[
        _f("head", 0, 8), _f("in", 16, 16, kind=model.STRUCT, children=inner)])
    root = tree.build_tree(s)
    nested = [c for c in root.children if c.label == "in"][0]
    pad = [c for c in nested.children if c.is_padding][0]
    assert (pad.offset, pad.size) == (17, 7)
    # Trou du premier niveau entre head et in.
    assert [c.label for c in root.children] == ["head", "[padding 8 o]", "in"]


def test_classe_sans_membre_visible_n_est_pas_du_padding():
    # std::string : membres prives, donc aucun enfant avec include_non_public = false.
    s = model.Struct(name="S", size=40, fields=[
        _f("name", 0, 32, kind=model.CLASS, type_name="basic_string<char>"),
        _f("n", 32, 4)])
    root = tree.build_tree(s)
    name = [c for c in root.children if c.label == "name"][0]
    assert name.children == []
    # La racine garde ses trous : ici le padding de fin.
    assert [c.label for c in root.children] == ["name", "n", "[padding 4 o]"]


def test_vptr_nomme_sur_type_polymorphe():
    s = model.Struct(name="P", size=16, is_polymorphic=True, fields=[_f("v", 8, 4)])
    labels = [c.label for c in tree.build_tree(s).children]
    assert labels == ["[vptr 8 o]", "v", "[padding 4 o]"]


def test_pas_de_trous_entre_elements_de_tableau():
    elem = _f("[]", 0, 4, base=0)
    arr = _f("t", 0, 16, kind=model.ARRAY, children=[elem], array_len=4)
    s = model.Struct(name="A", size=16, fields=[arr])
    node = tree.build_tree(s).children[0]
    assert [c.label for c in node.children] == ["[]"]


def test_filtre_garde_les_ancetres():
    inner = [_f("latitude", 0, 8, type_name="double")]
    s = model.Struct(name="S", size=16, fields=[
        _f("a", 0, 4), _f("pos", 8, 8, kind=model.STRUCT, children=inner)])
    root = tree.build_tree(s)
    keep = tree.filter_ids(root, "LAT")
    ids = {n.label for n, _ in root.walk() if n.id in keep}
    assert ids == {"S", "pos", "latitude"}
    assert tree.filter_ids(root, "  ") is None


def test_find_et_segments():
    s = model.Struct(name="S", size=8, fields=[_f("a", 0, 2), _f("b", 4, 4)])
    root = tree.build_tree(s)
    b = [c for c in root.children if c.label == "b"][0]
    assert tree.find(root, b.id) is b
    segs = [(start, end, n.label) for start, end, n in tree.top_level_segments(root)]
    assert segs == [(0, 2, "a"), (2, 4, "[padding 2 o]"), (4, 8, "b")]


def test_base_polymorphe_et_base_virtuelle_dans_l_arbre():
    poly = _f("", 0, 16, kind=model.BASE, type_name="Poly", is_polymorphic=True,
              children=[_f("p", 8, 4)])
    virt = _f("", 0, None, kind=model.BASE, type_name="VB", truncated="virtual")
    s = model.Struct(name="D", size=24, is_polymorphic=True,
                     fields=[poly, virt, _f("x", 16, 4)])
    root = tree.build_tree(s)
    labels = [n.label for n in root.children]
    assert labels == ["(base) Poly", "(base virtuelle) VB", "x", "[padding 4 o]"]
    assert [n.label for n in root.children[0].children] == ["[vptr 8 o]", "p", "[padding 4 o]"]
    assert root.children[1].note == "base virtuelle"
