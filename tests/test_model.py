"""Tests du modele intermediaire.

Le modele ne depend ni de castxml ni de pygccxml : les fixtures sont
construites a la main, donc la suite tourne partout, y compris en CI sans
Visual Studio. Elle couvre en priorite les cas que le README signale comme les
plus couteux en iterations : padding par fusion d'intervalles, champs de bits,
unions, membres statiques et types anonymes.
"""

from scry import model
from scry.model import Field, Struct


def f(name, offset, size, **kw):
    """Champ de premier niveau. abs_offset suit offset sauf mention contraire."""
    kw.setdefault("type_name", "int")
    kw.setdefault("kind", model.FUNDAMENTAL)
    kw.setdefault("abs_offset", offset)
    return Field(name=name, offset=offset, size=size, **kw)


# ---------------------------------------------------------------------------
# padding_bytes : fusion d'intervalles, pas somme des tailles
# ---------------------------------------------------------------------------

def test_padding_trou_entre_deux_champs():
    # int @0, double @8 : 4 octets d'alignement perdus apres le premier.
    s = Struct(name="S", size=16, fields=[f("a", 0, 4), f("b", 8, 8, type_name="double")])
    assert s.padding_bytes() == 4


def test_padding_nul_quand_la_structure_est_pleine():
    s = Struct(name="S", size=8, fields=[f("a", 0, 4), f("b", 4, 4)])
    assert s.padding_bytes() == 0


def test_padding_union_ne_compte_pas_deux_fois():
    """Une somme naive des tailles donnerait 8 couverts sur 4, donc -4."""
    s = Struct(name="U", kind=model.UNION, size=4,
               fields=[f("i", 0, 4), f("fl", 0, 4, type_name="float")])
    assert s.padding_bytes() == 0


def test_padding_bitfields_partageant_une_unite_de_stockage():
    """Trois champs de bits dans le meme int : couverture de 4 octets, pas 12."""
    s = Struct(name="B", size=4, fields=[
        f("a", 0, 4, bit_width=1, bit_offset=0),
        f("b", 0, 4, bit_width=2, bit_offset=1),
        f("c", 0, 4, bit_width=3, bit_offset=3),
    ])
    assert s.padding_bytes() == 0


def test_padding_ignore_les_membres_statiques():
    """byte_offset d'un membre statique vaut 0.0 et ne signifie rien."""
    s = Struct(name="S", size=4, fields=[
        f("compteur", 0, 4, is_static=True),
        f("a", 0, 4),
    ])
    assert s.padding_bytes() == 0


def test_padding_ignore_les_champs_de_taille_inconnue():
    s = Struct(name="S", size=8, fields=[f("a", 0, 4), f("opaque", 4, None)])
    assert s.padding_bytes() == 4


def test_padding_inconnu_si_taille_de_structure_inconnue():
    assert Struct(name="S", size=None, fields=[f("a", 0, 4)]).padding_bytes() is None


def test_padding_structure_sans_membre_est_entierement_du_padding():
    assert Struct(name="Vide", size=1, fields=[]).padding_bytes() == 1


def test_padding_champs_non_tries_par_offset():
    """La fusion trie elle-meme : l'ordre de declaration ne doit pas compter."""
    s = Struct(name="S", size=16, fields=[f("b", 8, 8, type_name="double"), f("a", 0, 4)])
    assert s.padding_bytes() == 4


# ---------------------------------------------------------------------------
# walk : parcours prefixe, profondeur, ordre de declaration
# ---------------------------------------------------------------------------

def _nested():
    petit = Field(name="inner", type_name="Inner", kind=model.STRUCT, offset=4,
                  abs_offset=4, size=8, children=[
                      f("x", 0, 4), f("y", 4, 4),
                  ])
    # Les enfants portent un offset relatif au parent et un abs_offset absolu.
    petit.children[0].abs_offset = 4
    petit.children[1].abs_offset = 8
    return Struct(name="Outer", size=12, fields=[f("id", 0, 4), petit])


def test_walk_ordre_prefixe_et_profondeur():
    noms = [(n.name, d) for n, d in _nested().walk()]
    assert noms == [("id", 0), ("inner", 0), ("x", 1), ("y", 1)]


def test_walk_conserve_l_ordre_de_declaration():
    s = Struct(name="S", fields=[f("a", 0, 4), f("b", 4, 4), f("c", 8, 4)])
    assert [n.name for n, _ in s.walk()] == ["a", "b", "c"]


def test_offset_relatif_et_absolu_ne_sont_pas_confondus():
    """Confondre les deux donne un affichage juste sur le 1er element, faux ensuite."""
    inner = _nested().fields[1]
    assert (inner.children[1].offset, inner.children[1].abs_offset) == (4, 8)


def test_leaves_ne_retient_que_le_lisible():
    s = _nested()
    assert [n.name for n in s.leaves()] == ["id", "x", "y"]


# ---------------------------------------------------------------------------
# label : champs de bits, tableaux, anonymes
# ---------------------------------------------------------------------------

def test_label_bitfield_affiche_la_largeur():
    assert f("flags", 0, 4, bit_width=3, bit_offset=0).label() == "flags : 3"


def test_label_tableau_affiche_la_longueur():
    assert f("nom", 0, 50, kind=model.ARRAY, array_len=50, elem_type="char").label() == "nom[50]"


def test_label_anonyme_est_signale():
    assert f("", 0, 4, is_anonymous=True).label() == "<anonyme>"


def test_label_bitfield_prioritaire_sur_tableau():
    assert f("b", 0, 4, bit_width=2, array_len=8).label() == "b : 2"


# ---------------------------------------------------------------------------
# is_readable : ce que le lecteur memoire peut decoder par offset
# ---------------------------------------------------------------------------

def test_is_readable_vrai_pour_un_scalaire():
    assert f("a", 0, 4).is_readable


def test_is_readable_faux_pour_un_statique():
    assert not f("a", 0, 4, is_static=True).is_readable


def test_is_readable_faux_sans_taille():
    assert not f("a", 0, None).is_readable


def test_is_readable_faux_pour_un_agregat():
    assert not f("s", 0, 8, kind=model.STRUCT).is_readable


# ---------------------------------------------------------------------------
# Serialisation : le modele doit rester exportable en JSON
# ---------------------------------------------------------------------------

def test_to_dict_est_serialisable_et_recursif():
    import json
    d = _nested().to_dict()
    json.dumps(d)  # ne doit pas lever
    assert d["padding"] == 0
    assert [c["name"] for c in d["fields"][1]["children"]] == ["x", "y"]


def test_to_dict_expose_le_padding_calcule():
    s = Struct(name="S", size=16, fields=[f("a", 0, 4)])
    assert s.to_dict()["padding"] == 12


# ---------------------------------------------------------------------------
# printf_for : correspondance type C++ -> format
# ---------------------------------------------------------------------------

def test_printf_for_connu_et_inconnu():
    assert model.printf_for("int")[0] == "%d"
    assert model.printf_for("MaStruct") is None


def test_printf_for_tolere_les_espaces():
    assert model.printf_for("  double  ")[0] == "%.6f"


def test_printf_for_float_promeut_en_double():
    """%f attend un double : passer un float sans cast est un comportement indefini."""
    fmt, expr = model.printf_for("float")
    assert "static_cast<double>" in expr
