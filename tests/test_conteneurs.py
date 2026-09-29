"""Conteneurs STL decrits par le modele, via le vrai castxml.

Les elements d'un std::vector ne sont pas dans la structure : ils vivent au
bout d'un pointeur, et leur nombre change a l'execution. Le modele ne peut donc
pas les placer comme ceux d'un tableau. Ce qu'il fait, et ce que ce fichier
verifie, c'est decrire l'element : c'est ce qui permet aux bindings de choisir
entre une vue numpy et une sequence par reference.

Le type de l'element est lu sur le typedef 'value_type' de la classe, et non
devine en decoupant '<...>' : la reponse vient du compilateur, allocateur et
alias compris.
"""

from pathlib import Path

import pytest

import toolchain
from scry import model
from scry.config import load_config
from scry.parsing.introspect import Introspector, index_by_name

ROOT = Path(__file__).resolve().parent.parent
COMPLEXE = ROOT / "Data" / "test_structs_complexe.h"

pytestmark = toolchain.needs_castxml


@pytest.fixture(scope="module")
def modele(tmp_path_factory):
    out = tmp_path_factory.mktemp("conteneurs")
    ini = out / "scry.ini"
    ini.write_text(toolchain.ini_paths(output=(out / "gen").as_posix())
                   + toolchain.ini_castxml()
                   + "[introspection]\nstop_on_error = true\n", encoding="utf-8")
    introspector = Introspector(load_config(ini))
    return index_by_name(introspector.parse([str(COMPLEXE)]))


def _field(struct, name):
    return next(f for f, _ in struct.walk() if f.name == name)


def test_vector_de_structures_decrit_son_element(modele):
    path = _field(modele["testgen::Waypoint"], "approach_path")
    assert path.container == "vector"
    assert path.qualified_type.startswith("std::vector<")
    assert path.elem is not None
    assert (path.elem.kind, path.elem.qualified_type) == (model.STRUCT, "testgen::Vec3")


def test_l_element_est_decrit_sans_etre_place(modele):
    """Un element de vector n'a pas d'offset dans la structure englobante : ses
    offsets sont comptes depuis son propre debut, et il ne figure pas dans le
    parcours du parent. Un vector ne place pas son contenu."""
    path = _field(modele["testgen::Waypoint"], "approach_path")
    assert (path.elem.offset, path.elem.abs_offset) == (0, 0)
    assert [c.name for c in path.elem.children] == ["x", "y", "z"]
    taille = path.elem.children[0].size
    assert [c.abs_offset for c in path.elem.children] == [0, taille, 2 * taille]
    assert path.elem.name not in [f.name for f, _ in modele["testgen::Waypoint"].walk()]


def test_un_type_imbrique_vu_seulement_comme_element(modele):
    """TelemetryFrame::Channel n'apparait nulle part ailleurs que comme element
    du vector : sans ses membres, le membre serait ecarte faute de type."""
    channels = _field(modele["testgen::TelemetryFrame"], "channels")
    assert channels.elem.qualified_type == "testgen::TelemetryFrame::Channel"
    assert [c.name for c in channels.elem.children][:1] == ["id"]


def test_un_autre_conteneur_n_est_pas_pris_pour_un_vector(modele):
    """std::map, std::string et std::optional n'ont pas de tampon contigu a
    exposer : container doit rester vide."""
    plan = modele["testgen::FlightPlan"]
    for name in ("callsign", "named_constraints"):
        assert _field(plan, name).container == ""
    assert _field(modele["testgen::Waypoint"], "altitude_ft").container == ""


def test_un_tableau_n_est_pas_un_conteneur(modele):
    """Un std::array est de taille fixe et vit dans la structure : il garde son
    traitement de tableau, elem_type et enfants, sans passer par container."""
    legs = _field(modele["testgen::FlightPlan"], "legs")
    assert legs.container == "" and legs.elem is None


def test_serialisation_du_conteneur(modele):
    d = _field(modele["testgen::Waypoint"], "approach_path").to_dict()
    assert d["container"] == "vector"
    assert d["elem"]["qualified_type"] == "testgen::Vec3"
    assert _field(modele["testgen::FlightPlan"], "legs").to_dict()["elem"] is None
