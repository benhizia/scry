"""Tests du decodage memoire.

BufferSource suffit : la meme fonction decode() sert ensuite sur une
SharedMemorySource, l'interface etant identique. Aucun castxml requis.
"""

import struct as _struct

from scry import model
from scry.model import Field, Struct
from scry.runtime import memory


def field(name, offset, size, **kw):
    kw.setdefault("type_name", "int")
    kw.setdefault("kind", model.FUNDAMENTAL)
    return Field(name=name, type_name=kw.pop("type_name"), kind=kw.pop("kind"),
                 offset=offset, abs_offset=offset, size=size, **kw)


def src(payload):
    return memory.BufferSource(payload)


# ---------------------------------------------------------------------------
# BufferSource : bornes
# ---------------------------------------------------------------------------

def test_read_dans_les_bornes():
    assert src(b"\x01\x02\x03\x04").read(1, 2) == b"\x02\x03"


def test_read_hors_bornes_retourne_none():
    s = src(b"\x01\x02")
    assert s.read(0, 3) is None
    assert s.read(-1, 1) is None


def test_read_exactement_a_la_limite():
    assert src(b"\x01\x02").read(0, 2) == b"\x01\x02"


# ---------------------------------------------------------------------------
# Scalaires
# ---------------------------------------------------------------------------

def test_decode_int_signe():
    assert memory.decode(src(_struct.pack("<i", -42)), field("a", 0, 4)) == "-42"


def test_decode_double():
    payload = _struct.pack("<d", 3.5)
    assert memory.decode(src(payload), field("d", 0, 8, type_name="double")) == "3.5"


def test_decode_bool():
    assert memory.decode(src(b"\x01"), field("b", 0, 1, type_name="bool")) == "True"


def test_decode_respecte_l_offset():
    payload = b"\x00" * 8 + _struct.pack("<i", 7)
    assert memory.decode(src(payload), field("a", 8, 4)) == "7"


def test_decode_buffer_trop_court_retourne_none():
    assert memory.decode(src(b"\x01\x02"), field("a", 0, 4)) is None


def test_decode_type_non_fondamental_connu_retourne_none():
    assert memory.decode(src(b"\x00" * 8), field("s", 0, 8, kind=model.STRUCT,
                                                 type_name="Inner")) is None


# ---------------------------------------------------------------------------
# Cas que le README signale comme couteux
# ---------------------------------------------------------------------------

def test_decode_statique_retourne_none():
    """Un membre statique n'est pas dans l'instance : son offset ne veut rien dire."""
    assert memory.decode(src(_struct.pack("<i", 5)),
                         field("n", 0, 4, is_static=True)) is None


def test_decode_char_array_comme_chaine():
    payload = b"Bonjour\x00" + b"\xff" * 8
    fld = field("nom", 0, 16, kind=model.ARRAY, array_len=16, elem_type="char")
    assert memory.decode(src(payload), fld) == '"Bonjour"'


def test_decode_char_array_sans_terminateur():
    fld = field("nom", 0, 4, kind=model.ARRAY, array_len=4, elem_type="char")
    assert memory.decode(src(b"abcd"), fld) == '"abcd"'


def test_decode_bitfield_extrait_les_bits():
    # 0b1101 dans le premier octet : largeur 2 a partir du bit 1 -> 0b10 = 2.
    fld = field("f", 0, 4, bit_width=2, bit_offset=1)
    assert memory.decode(src(_struct.pack("<I", 0b1101)), fld) == "2"


def test_decode_bitfield_au_bit_zero():
    fld = field("f", 0, 4, bit_width=1, bit_offset=0)
    assert memory.decode(src(_struct.pack("<I", 0b1101)), fld) == "1"


def test_decode_enum_nomme_la_valeur():
    fld = field("e", 0, 4, kind=model.ENUM, type_name="Couleur",
                enum_values=["ROUGE", "VERT", "BLEU"])
    assert memory.decode(src(_struct.pack("<i", 2)), fld) == "BLEU (2)"


def test_decode_enum_hors_plage_reste_numerique():
    fld = field("e", 0, 4, kind=model.ENUM, type_name="Couleur",
                enum_values=["ROUGE"])
    assert memory.decode(src(_struct.pack("<i", 9)), fld) == "9"


def test_decode_pointeur_en_hexadecimal():
    fld = field("p", 0, 8, kind=model.POINTER, type_name="int *")
    got = memory.decode(src(_struct.pack("<Q", 0xDEADBEEF)), fld)
    assert got == "0x00000000DEADBEEF"


def test_decode_sans_source_retourne_none():
    assert memory.decode(None, field("a", 0, 4)) is None


# ---------------------------------------------------------------------------
# Buffer de demonstration
# ---------------------------------------------------------------------------

def test_demo_buffer_a_la_taille_de_la_structure():
    assert len(memory.make_demo_buffer(Struct(name="S", size=32))) == 32


def test_demo_buffer_vide_si_taille_inconnue():
    assert memory.make_demo_buffer(Struct(name="S", size=None)) == b""


def test_demo_buffer_est_deterministe():
    s = Struct(name="S", size=64)
    assert memory.make_demo_buffer(s) == memory.make_demo_buffer(s)
