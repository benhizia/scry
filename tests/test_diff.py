"""scry diff : comparaison de modeles exportes, sans castxml."""

import json
from pathlib import Path

import pytest

from scry import cli, diff, model
from scry.config import load_config

EXAMPLE_INI = Path(__file__).resolve().parent.parent / "scry.ini.example"


def _struct(name="S", b_offset=8, size=16, extra=None):
    fields = [
        model.Field(name="a", type_name="int", kind=model.FUNDAMENTAL, offset=0,
                    abs_offset=0, size=4, access_path="obj.a"),
        model.Field(name="b", type_name="double", kind=model.FUNDAMENTAL, offset=b_offset,
                    abs_offset=b_offset, size=8, access_path="obj.b"),
    ] + (extra or [])
    return model.Struct(name=name, size=size, align=8, fields=fields)


def _doc(*structs, cfg=None):
    return diff.document(list(structs), cfg or load_config(EXAMPLE_INI), ["Data/s.h"])


def test_document_porte_la_plateforme():
    d = _doc(_struct())
    assert (d["format"], d["version"]) == ("scry-model", 1)
    assert d["platform"]["compiler"] == "msvc"
    assert d["platform"]["headers"] == ["Data/s.h"]
    assert d["structs"][0]["name"] == "S"


def test_identiques():
    result = diff.compare(_doc(_struct()), _doc(_struct()))
    assert result.empty and not result.breaking
    assert diff.report(result) == ["Layouts identiques."]


def test_offset_deplace_casse():
    result = diff.compare(_doc(_struct()), _doc(_struct(b_offset=12, size=24)))
    assert result.breaking
    (s,) = result.structs
    assert ("S", "size", 16, 24) in s.changes
    assert ("obj.b", "abs_offset", 8, 12) in s.changes


def test_ajouts_seuls_ne_cassent_pas():
    extra = [model.Field(name="c", type_name="char", kind=model.FUNDAMENTAL, offset=4,
                         abs_offset=4, size=1, access_path="obj.c")]
    result = diff.compare(_doc(_struct()), _doc(_struct(extra=extra), _struct("T")))
    assert not result.breaking and not result.empty
    assert result.added == ["T"]
    assert result.structs[0].added == ["obj.c"]


def test_suppressions_cassent():
    ref = _doc(_struct(), _struct("T"))
    result = diff.compare(ref, _doc(_struct()))
    assert result.breaking and result.removed == ["T"]


def test_statiques_ignores():
    static = [model.Field(name="k", type_name="int", kind=model.FUNDAMENTAL,
                          access_path="obj.k", is_static=True)]
    assert diff.compare(_doc(_struct()), _doc(_struct(extra=static))).empty


def test_cibles_differentes_signalees(tmp_path):
    ini = tmp_path / "scry.ini"
    ini.write_text("[castxml]\ncompiler = msvc\ncl_flags = /MDd\n", encoding="utf-8")
    result = diff.compare(_doc(_struct()), _doc(_struct(), cfg=load_config(ini)))
    assert ("cl_flags", "", "/MDd") in result.platform
    assert diff.report(result)[0].startswith("[attention]")


def test_ancien_format_liste_accepte(tmp_path):
    path = tmp_path / "ancien.json"
    path.write_text(json.dumps([_struct().to_dict()]), encoding="utf-8")
    loaded = diff.load(str(path))
    assert loaded["version"] == 0 and loaded["structs"][0]["name"] == "S"
    assert diff.compare(loaded, _doc(_struct())).empty


def test_fichier_etranger_refuse(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="scry json"):
        diff.load(str(path))


def test_cli_code_de_retour(tmp_path, capsys):
    ref, same, moved, added = (tmp_path / n for n in ("r.json", "s.json", "m.json", "a.json"))
    ref.write_text(json.dumps(_doc(_struct())), encoding="utf-8")
    same.write_text(json.dumps(_doc(_struct())), encoding="utf-8")
    moved.write_text(json.dumps(_doc(_struct(b_offset=12))), encoding="utf-8")
    added.write_text(json.dumps(_doc(_struct(), _struct("T"))), encoding="utf-8")
    cfg = ["-c", str(EXAMPLE_INI)]
    assert cli.main(["diff", str(ref), str(same)] + cfg) == 0
    assert cli.main(["diff", str(ref), str(moved)] + cfg) == 1
    assert cli.main(["diff", str(ref), str(added)] + cfg) == 0
    assert cli.main(["diff", str(ref), str(added), "--strict"] + cfg) == 1
    assert "[CASSE ] S" in capsys.readouterr().out


@pytest.mark.skipif(not __import__("shutil").which("castxml"), reason="castxml absent")
def test_deux_livraisons_d_un_header(tmp_path, capsys):
    v1 = "#pragma once\nstruct Etat { int mode; double vitesse; char nom[8]; };\n"
    # Livraison 2 : un int loge dans le trou de padding, rien ne bouge.
    v2 = "#pragma once\nstruct Etat { int mode; int drapeaux; double vitesse; char nom[8]; };\n"
    # Livraison 3 : un double insere, tout ce qui suit se decale.
    v3 = "#pragma once\nstruct Etat { int mode; double t; double vitesse; char nom[8]; };\n"
    header = tmp_path / "tiers.h"
    ini = tmp_path / "scry.ini"
    ini.write_text("[paths]\nheaders = tiers.h\ncache =\n[castxml]\ncompiler = gcc\n"
                   "extra_cflags = -Wno-pragma-once-outside-header\n", encoding="utf-8")
    ref = tmp_path / "ref.json"
    header.write_text(v1, encoding="utf-8")
    assert cli.main(["json", str(ref), "-c", str(ini)]) == 0
    assert cli.main(["diff", str(ref), "-c", str(ini)]) == 0
    header.write_text(v2, encoding="utf-8")
    assert cli.main(["diff", str(ref), "-c", str(ini)]) == 0
    assert "+ obj.drapeaux" in capsys.readouterr().out
    header.write_text(v3, encoding="utf-8")
    assert cli.main(["diff", str(ref), "-c", str(ini)]) == 1
    out = capsys.readouterr().out
    assert "[CASSE ] Etat" in out
    assert "obj.vitesse" in out and "8 -> 16" in out
