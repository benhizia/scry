"""Localisation de castxml et origine affichee par 'scry check'."""

from pathlib import Path

import pytest
from pygccxml import utils

from scry.config import load_config
from scry.parsing import msvc_env

EXAMPLE_INI = Path(__file__).resolve().parent.parent / "scry.ini.example"


@pytest.fixture(autouse=True)
def _sans_surcharge(monkeypatch):
    # Une variable positionnee sur le poste fausserait l'origine attendue.
    monkeypatch.delenv(msvc_env.ENV_CASTXML, raising=False)


def _ini(tmp_path, castxml):
    ini = tmp_path / "scry.ini"
    ini.write_text("[paths]\ncastxml = %s\n" % castxml, encoding="utf-8")
    return load_config(ini)


def test_cle_vide_castxml_trouve_dans_le_path(monkeypatch):
    monkeypatch.setattr(utils, "find_xml_generator",
                        lambda *a, **k: ("C:/outils/castxml.exe", "castxml"))
    path, origin = msvc_env.locate_castxml(load_config(EXAMPLE_INI))
    assert path == Path("C:/outils/castxml.exe")
    assert "PATH" in origin


def test_cle_renseignee_prise_depuis_le_ini(tmp_path):
    exe = tmp_path / "castxml.exe"
    exe.write_bytes(b"")
    path, origin = msvc_env.locate_castxml(_ini(tmp_path, exe))
    assert path == exe
    assert "scry.ini" in origin


def test_variable_d_environnement_prioritaire(tmp_path, monkeypatch):
    exe = tmp_path / "castxml.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv(msvc_env.ENV_CASTXML, str(exe))
    path, origin = msvc_env.locate_castxml(load_config(EXAMPLE_INI))
    assert path == exe
    assert msvc_env.ENV_CASTXML in origin


def test_cle_renseignee_fichier_absent(tmp_path):
    with pytest.raises(msvc_env.MsvcNotFound, match="scry.ini"):
        msvc_env.locate_castxml(_ini(tmp_path, tmp_path / "absent.exe"))


def test_introuvable_nulle_part(monkeypatch):
    monkeypatch.setattr(utils, "find_xml_generator", lambda *a, **k: (None, None))
    with pytest.raises(msvc_env.MsvcNotFound, match="PATH"):
        msvc_env.locate_castxml(load_config(EXAMPLE_INI))
