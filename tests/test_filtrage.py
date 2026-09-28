"""Filtrage des types : motifs, selection, configuration et ligne de commande.

Un header tiers et ce qu'il inclut apportent des centaines de types. Le filtre
s'applique dans Introspector.parse, donc toutes les commandes en heritent : ce
qui est ecarte n'est ni affiche, ni exporte, ni genere.
"""

import os
import shutil
from pathlib import Path

import pytest

from scry import cli, model
from scry.config import load_config
from scry.parsing.introspect import Introspector

NOMS = ["testgen::Vec3", "testgen::FlightPlan", "testgen::FlightPlan::Leg",
        "testgen::detail::RingBuffer<testgen::SensorSample, 8>", "autre::Truc"]


def _structs(noms=NOMS):
    return [model.Struct(name=n, size=4) for n in noms]


def _noms(structs):
    return [s.name for s in structs]


# -- motifs -------------------------------------------------------------------
def test_motifs_glob_et_nom_exact():
    assert model.matches_type("testgen::Vec3", ["testgen::*"])
    assert model.matches_type("testgen::Vec3", ["*::Vec3"])
    assert model.matches_type("testgen::Vec3", ["testgen::Vec3"])
    assert not model.matches_type("testgen::Vec3", ["autre::*"])
    assert not model.matches_type("testgen::Vec3", [])


def test_motif_sans_joker_garde_les_types_imbriques():
    # Sinon, filtrer une structure ferait disparaitre ses propres types.
    assert model.matches_type("testgen::FlightPlan::Leg", ["testgen::FlightPlan"])
    # Un motif avec joker, lui, ne fait rien de plus que ce qu'il dit.
    assert not model.matches_type("testgen::FlightPlanBis", ["testgen::FlightPlan"])


# -- selection ----------------------------------------------------------------
def test_sans_motif_tout_est_garde():
    gardes, ecartes = model.select_types(_structs())
    assert _noms(gardes) == NOMS and ecartes == []


def test_include_garde_l_ordre_et_annonce_les_ecartes():
    gardes, ecartes = model.select_types(_structs(), ["testgen::*"])
    assert _noms(gardes) == NOMS[:4]
    assert ecartes == ["autre::Truc"]


def test_exclude_l_emporte_sur_include():
    gardes, ecartes = model.select_types(_structs(), ["testgen::*"], ["*detail*"])
    assert _noms(gardes) == NOMS[:3]
    assert ecartes == [NOMS[3], "autre::Truc"]


def test_exclude_seul():
    gardes, _ = model.select_types(_structs(), (), ["autre::*"])
    assert _noms(gardes) == NOMS[:4]


def test_motifs_vides_ignores():
    gardes, ecartes = model.select_types(_structs(), ["", "  "], [""])
    assert _noms(gardes) == NOMS and ecartes == []


# -- configuration ------------------------------------------------------------
def _cfg(tmp_path, corps):
    ini = tmp_path / "scry.ini"
    ini.write_text(corps, encoding="utf-8")
    return load_config(ini)


def test_motifs_lus_dans_la_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRY_INTROSPECTION_INCLUDE_TYPES", raising=False)
    cfg = _cfg(tmp_path, "[introspection]\ninclude_types = sim::*; moteur::Etat\n"
                         "exclude_types = *::detail::*\n")
    it = Introspector(cfg)
    assert it.include_types == ["sim::*", "moteur::Etat"]
    assert it.exclude_types == ["*::detail::*"]


def test_options_priment_sur_la_configuration(tmp_path):
    cfg = _cfg(tmp_path, "[introspection]\ninclude_types = sim::*\n")
    it = Introspector(cfg, include_types=["autre::*"], exclude_types=["x::*"])
    assert it.include_types == ["autre::*"] and it.exclude_types == ["x::*"]
    # Une liste vide explicite (-t absent) n'efface pas la configuration.
    assert Introspector(cfg).include_types == ["sim::*"]


def test_rapport_verbeux_nomme_les_types_ecartes():
    from scry.parsing.introspect import ParseReport
    rapport = ParseReport()
    rapport.filtered = ["a::B", "a::C"]
    assert rapport.lines() == []                       # pas de bruit par defaut
    ligne = rapport.lines(verbose=True)[0]
    assert ligne.startswith("[filtre] 2 type(s) ecarte(s)") and "a::C" in ligne


# -- filtre d'affichage de l'IHM ------------------------------------------------
def test_filtre_d_affichage_texte_et_glob():
    from scry.ui import tree
    structs = _structs()
    assert [s.name for _, s in tree.filter_structs(structs, "")] == NOMS
    # Texte : sans egard a la casse, n'importe ou dans le nom qualifie.
    assert [s.name for _, s in tree.filter_structs(structs, "flight")] == NOMS[1:3]
    # Glob : sur le nom complet.
    assert [s.name for _, s in tree.filter_structs(structs, "autre::*")] == ["autre::Truc"]
    # Les index rendus sont ceux du modele, pas ceux de la liste affichee.
    assert [i for i, _ in tree.filter_structs(structs, "autre::*")] == [4]


# -- bout en bout, avec castxml ------------------------------------------------
def _castxml_present() -> bool:
    """castxml se cherche comme Scry le fait : la variable, puis [paths]
    castxml du depot, puis le PATH. Un poste Windows l'a rarement dans le
    PATH, et ces tests doivent quand meme tourner."""
    import configparser
    candidats = [os.environ.get("SCRY_PATHS_CASTXML", "")]
    ini = Path(__file__).resolve().parent.parent / "scry.ini"
    if ini.is_file():
        lecteur = configparser.ConfigParser()
        lecteur.read(ini, encoding="utf-8")
        candidats.append(lecteur.get("paths", "castxml", fallback="").strip())
    for candidat in candidats:
        chemin = Path(candidat) if candidat else None
        if chemin is None:
            continue
        if chemin.is_dir():
            chemin = chemin / "castxml.exe"
        if chemin.is_file():
            os.environ.setdefault("SCRY_PATHS_CASTXML", str(chemin))
            return True
    return bool(shutil.which("castxml"))


HAS_CASTXML = _castxml_present()
HEADER = ("#pragma once\nnamespace sim {\n"
          "struct Etat { int mode; };\n"
          "struct Autre { double x; };\n"
          "namespace detail { struct Interne { char c; }; }\n"
          "}\n")


@pytest.mark.skipif(not HAS_CASTXML, reason="castxml absent")
@pytest.mark.parametrize("options, attendus", [
    ([], ["sim::Autre", "sim::Etat", "sim::detail::Interne"]),
    (["-t", "sim::Etat"], ["sim::Etat"]),
    (["-t", "sim::*", "-x", "*detail*"], ["sim::Autre", "sim::Etat"]),
    (["-x", "sim::Autre"], ["sim::Etat", "sim::detail::Interne"]),
])
def test_dump_filtre_par_la_ligne_de_commande(tmp_path, capsys, options, attendus):
    (tmp_path / "demo.h").write_text(HEADER, encoding="utf-8")
    ini = tmp_path / "scry.ini"
    ini.write_text("[paths]\nheaders = demo.h\ncache =\n"
                   "[castxml]\nextra_cflags = -Wno-pragma-once-outside-header\n",
                   encoding="utf-8")
    assert cli.main(["dump", "-c", str(ini)] + options) == 0
    sortie = capsys.readouterr().out
    vus = sorted(ligne.split()[1] for ligne in sortie.splitlines() if ligne.startswith("=== "))
    assert vus == attendus
