"""Sources de Dear ImGui : jamais de telechargement implicite, sans reseau."""

from pathlib import Path

import pytest

from scry.config import load_config
from scry.viewer import build as vb


@pytest.fixture(autouse=True)
def _sans_surcharge(monkeypatch):
    for key in ("SCRY_VIEWER_AUTO_DOWNLOAD", "SCRY_VIEWER_IMGUI_DIR", "SCRY_VIEWER_IMGUI_TAG"):
        monkeypatch.delenv(key, raising=False)


def _cfg(tmp_path, extra=""):
    ini = tmp_path / "scry.ini"
    ini.write_text("[viewer]\nimgui_dir = imgui\n" + extra, encoding="utf-8")
    return load_config(ini)


def _sans_git(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("git ne doit pas etre lance")
    monkeypatch.setattr(vb.subprocess, "run", interdit)


def _imgui(root: Path, version=19291):
    for rel in vb.REQUIRED_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (root / "imgui.h").write_text("#define IMGUI_VERSION_NUM %d\n" % version, encoding="utf-8")


def _silence(*_):
    pass


def test_absent_sans_demande_donne_la_marche_a_suivre(tmp_path, monkeypatch):
    _sans_git(monkeypatch)
    with pytest.raises(vb.ViewerError) as exc:
        vb.ensure_imgui(_cfg(tmp_path), log=_silence)
    message = str(exc.value)
    for attendu in ("--fetch-imgui", "imgui.cpp", "v1.92.9b", "auto_download",
                    str(tmp_path / "imgui")):
        assert attendu in message


def test_sources_deposees_a_la_main(tmp_path, monkeypatch):
    _sans_git(monkeypatch)
    _imgui(tmp_path / "imgui")
    assert vb.ensure_imgui(_cfg(tmp_path)) == tmp_path / "imgui"


def test_dossier_incomplet_liste_ce_qui_manque(tmp_path, monkeypatch):
    _sans_git(monkeypatch)
    (tmp_path / "imgui").mkdir()
    (tmp_path / "imgui" / "imgui.cpp").write_text("", encoding="utf-8")
    with pytest.raises(vb.ViewerError, match="backends/imgui_impl_dx11.cpp"):
        vb.ensure_imgui(_cfg(tmp_path), fetch=True)   # meme --fetch n'ecrase rien


def test_version_trop_ancienne(tmp_path, monkeypatch):
    _sans_git(monkeypatch)
    _imgui(tmp_path / "imgui", version=19000)
    with pytest.raises(vb.ViewerError, match="1.92 minimum"):
        vb.ensure_imgui(_cfg(tmp_path))


def _faux_clone(monkeypatch, appels):
    class Resultat:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, **kwargs):
        appels.append(cmd)
        _imgui(Path(cmd[-1]))
        return Resultat()
    monkeypatch.setattr(vb.subprocess, "run", run)


def test_fetch_lance_le_clone(tmp_path, monkeypatch):
    appels = []
    _faux_clone(monkeypatch, appels)
    vb.ensure_imgui(_cfg(tmp_path), fetch=True, log=_silence)
    assert appels[0][:2] == ["git", "clone"] and "v1.92.9b" in appels[0]


def test_auto_download_par_la_config(tmp_path, monkeypatch):
    appels = []
    _faux_clone(monkeypatch, appels)
    vb.ensure_imgui(_cfg(tmp_path, "auto_download = true\n"), log=_silence)
    assert len(appels) == 1
