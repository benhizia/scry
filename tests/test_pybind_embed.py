"""Bindings generes, dans un interpreteur Python EMBARQUE dans une appli C++.

C'est l'usage vise : l'application C++ embarque Python, le module genere par
Scry (scry_module.generated.cpp) expose tous ses types et toutes ses variables
globales par reference, et un script les lit et les ecrit dans le cycle de
l'application, sans copie ni IPC.

L'hote (tests/cpp/pybind_host.cpp) definit les globales de
tests/data/pybind_cases.h, execute un script, puis vide les octets de ses
structures : le test les decode aux offsets du modele. Ce que Python a ecrit
doit s'y trouver, ce qui prouve que bindings, modele et compilateur sont
d'accord.

Compile une fois par session (une vingtaine de secondes). Saute sans castxml,
compilateur C++, pybind11, numpy, ou les fichiers de developpement de Python.
"""

import os
import subprocess
import sys
import sysconfig
import textwrap
from pathlib import Path

import pytest

import toolchain
from scry.runtime import memory
from scry.runtime.memory import BufferSource

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "Data"
CASES = ROOT / "tests" / "data" / "pybind_cases.h"
HOST = ROOT / "tests" / "cpp" / "pybind_host.cpp"


def _python_build_flags():
    """(includes, dossiers de bibliotheque, bibliotheques, options) pour
    embarquer l'interpreteur courant, ou None si les fichiers de
    developpement manquent.

    Sous Windows, Python.h et pythonXY.lib vivent dans l'installation de base,
    jamais dans le venv, et l'edition de liens passe par le pragma de
    Python.h : donner le dossier libs suffit. Ailleurs, il faut -l et un rpath
    pour retrouver la bibliotheque a l'execution.
    """
    include = sysconfig.get_paths()["include"]
    if not (Path(include) / "Python.h").is_file():
        return None
    if sys.platform == "win32":
        libdir = Path(sys.base_prefix) / "libs"
        if not list(libdir.glob("python3*.lib")):
            return None
        return [include], [str(libdir)], [], []
    libdir = sysconfig.get_config_var("LIBDIR")
    ldlib = sysconfig.get_config_var("LDLIBRARY") or ""
    if not ldlib.endswith(".so"):
        return None
    name = ldlib[3:-3]                      # libpython3.11.so -> python3.11
    return [include], [libdir], [name], ["-Wl,-rpath,%s" % libdir]


def _host_env():
    """Environnement de l'hote : la DLL de Python et les paquets du venv.

    L'interpreteur embarque part de l'installation de base ; numpy, lui, est
    dans le venv qui lance les tests. Sans PYTHONPATH, les vues numpy des
    bindings ne se creeraient pas."""
    env = dict(os.environ)
    if sys.platform == "win32":
        env["PATH"] = sys.base_prefix + os.pathsep + env.get("PATH", "")
        env["PYTHONHOME"] = sys.base_prefix
    paquets = [d for d in sys.path if d.endswith("site-packages")]
    if paquets:
        env["PYTHONPATH"] = os.pathsep.join(paquets)
    return env


pytestmark = pytest.mark.skipif(
    toolchain.CASTXML is None or toolchain.KIND is None or _python_build_flags() is None,
    reason="castxml, compilateur C++ ou fichiers de developpement de Python absents")


SPANS = ("spans = cases::Piste::bornes: nb_bornes;"
         " cases::Piste::mesures: nb_mesures; cases::Piste::opaque: nb_opaque\n")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    pytest.importorskip("pybind11")
    pytest.importorskip("numpy")
    return _compiler(tmp_path_factory, "pybind_embed")


@pytest.fixture(scope="module")
def built_lecture_seule(tmp_path_factory):
    """Un second module, avec une liste blanche d'ecriture : seuls
    cases::Sample::from et cases::g_speed gardent leur setter."""
    pytest.importorskip("pybind11")
    pytest.importorskip("numpy")
    return _compiler(tmp_path_factory, "pybind_ro",
                     "writable = cases::Sample::from; cases::g_speed\n")


def _compiler(tmp_path_factory, nom: str, pybind_extra: str = ""):
    """Genere les bindings puis compile l'hote. 'pybind_extra' complete la
    section [pybind] du scry.ini de test."""
    import pybind11
    from scry.codegen import pybind
    from scry.config import load_config
    from scry.parsing.introspect import Introspector, index_by_name

    out = tmp_path_factory.mktemp(nom)
    ini = out / "scry.ini"
    ini.write_text(
        toolchain.ini_paths(output="gen")
        + toolchain.ini_castxml(extra=["include_paths = %s" % DATA.as_posix()])
        # include_non_public : les membres prives entrent dans le modele, les
        # bindings doivent les ecarter pour compiler.
        + "[introspection]\nstop_on_error = true\ninclude_non_public = true\n"
        # Paires pointeur + compteur : rien ne permet de les deviner. La
        # derniere vise un void*, non liable : elle doit donner un commentaire,
        # pas un code qui ne compile pas.
        + "[pybind]\n" + SPANS + pybind_extra,
        encoding="utf-8")
    cfg = load_config(ini)
    introspector = Introspector(cfg)
    structs = introspector.parse([str(CASES), str(DATA / "test_structs_complexe.h")])
    pybind.generate(structs, cfg, variables=introspector.variables,
                    functions=introspector.functions)

    gen = out / "gen"
    py_inc, py_libdirs, py_libs, py_extra = _python_build_flags()
    exe = out / toolchain.exe_name("pybind_host")
    # Hors du perimetre : offsetof sur un type qui n'est pas standard-layout
    # dans le header ABI, s_internal inutilise dans le header de test, et
    # C4324, qui signale qu'une struct alignas est completee par du padding.
    quiet = (["/wd4101", "/wd4324"] if toolchain.IS_MSVC
             else ["-Wno-invalid-offsetof", "-Wno-unused-variable"])
    toolchain.check(toolchain.compile_exe(
        [HOST, gen / "scry_module.generated.cpp"], exe,
        includes=[gen, CASES.parent, DATA],
        external=[pybind11.get_include()] + py_inc,
        lib_dirs=py_libdirs, libs=py_libs, extra=quiet + py_extra))
    return exe, index_by_name(structs), introspector.variables, gen, introspector.functions


def run(built, tmp_path, script):
    exe = built[0]
    path = tmp_path / "script.py"
    path.write_text(textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run([str(exe), str(path)], capture_output=True, text=True,
                          timeout=60, env=_host_env())
    out = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(" ")
        out[key] = value
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


def _field(struct_model, name):
    return next(f for f, _ in struct_model.walk() if f.name == name)


def test_variables_collectees_static_ecartee(built):
    names = {v.qualified_name for v in built[2]}
    assert {"cases::g_sample", "cases::g_speed", "cases::g_version",
            "cases::inner::g_ticks", "cases::g_sensors"} <= names
    assert "cases::s_internal" not in names


def test_scalaires_enum_chaine_bits_dans_une_globale(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        s = c.g_sample
        s.speed = c.Speed.Fast
        s.mode, s.armed, s.level = 5, 1, 0xABC
        s.tag = "RWY27"
        s.from_ = -7
        for stmt, exc in [("s.tag = 'x' * 8", ValueError), ("s.pas_un_champ = 1", AttributeError)]:
            try:
                exec(stmt)
                raise SystemExit("aucune erreur : " + stmt)
            except exc:
                pass
    """)
    model_ = built[1]["cases::Sample"]
    src = BufferSource(bytes.fromhex(out["SAMPLE"]))
    assert memory.decode(src, _field(model_, "speed")) == "Fast (10)"
    assert memory.decode(src, _field(model_, "mode")) == "5"
    assert memory.decode(src, _field(model_, "armed")) == "1"
    assert memory.decode(src, _field(model_, "level")) == str(0xABC)
    assert memory.decode(src, _field(model_, "tag")) == '"RWY27"'
    assert memory.decode(src, _field(model_, "from")) == "-7"


def test_vues_numpy_sans_copie(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        s = sut.cases.g_sample
        v = s.values
        v[2] = 4.5                     # ecrit a travers la vue
        assert v.base is not None      # vue, pas copie
        s.grid[1, 2] = -3
        s.vec = [1.0, 2.0, 3.0]
        assert s.grid.shape == (2, 3)
        try:
            s.values = [1.0, 2.0]
            raise SystemExit("taille non verifiee")
        except ValueError:
            pass
        g = sut.cases.g_gains          # tableau numerique global
        g[1] = 20.0
        sut.cases.g_gains = [7, 8, 9]  # affectation complete
    """)
    import struct
    model_ = built[1]["cases::Sample"]
    raw = bytes.fromhex(out["SAMPLE"])
    assert struct.unpack_from("<d", raw, _field(model_, "values").abs_offset + 16)[0] == 4.5
    assert struct.unpack_from("<h", raw, _field(model_, "grid").abs_offset + 5 * 2)[0] == -3
    assert struct.unpack_from("<3f", raw, _field(model_, "vec").abs_offset) == (1.0, 2.0, 3.0)
    assert out["GAINS"] == "7 8 9"


def test_union_et_struct_anonymes(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        s = sut.cases.g_sample
        s.raw = 0x3F800000
        assert s.as_float == 1.0
        s.pair.lo, s.pair.hi = 1, 2
    """)
    import struct
    raw = bytes.fromhex(out["SAMPLE"])
    offset = _field(built[1]["cases::Sample"], "pair").abs_offset
    assert struct.unpack_from("<HH", raw, offset) == (1, 2)


def test_globales_scalaires_constantes_et_namespaces(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        assert c.g_version == 42
        assert c.g_callsign == "F-GKXA"
        c.g_speed = c.Speed.Max
        c.g_callsign = "N123"
        c.inner.g_ticks += 5
        c.inner.g_ticks += 5
        for stmt in ["c.g_version = 1", "c.g_speeed = 1", "c.inner.g_tick = 1"]:
            try:
                exec(stmt)
                raise SystemExit("aucune erreur : " + stmt)
            except AttributeError:
                pass
        assert not hasattr(c, "s_internal")
        assert "g_sample" in type(c).__scry_globals__
    """)
    assert out["SPEED"] == "255"
    assert out["CALLSIGN"] == "N123"
    assert out["TICKS"] == "10"


def test_pointeur_vers_une_structure_decrite(built, tmp_path):
    run(built, tmp_path, """
        import sut
        c = sut.cases
        p = c.g_current                  # g_current = &g_sample, pose par le C++
        assert p is not None
        p.from_ = 11
        assert c.g_sample.from_ == 11    # meme objet C++
        assert p.__address__ == c.g_sample.__address__
    """)


def test_structures_imbriquees_tableaux_de_structs_stl(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        tg, c = sut.testgen, sut.cases
        fp = c.g_plan
        fp.callsign = "AF123"                       # std::string
        fp.legs[2].phase = tg.FlightPlan.Phase.Climb
        fp.legs[2].from_.position.x = 3.0
        fp.payload.raw = 0x00020001
        assert (fp.payload.halves.lo, fp.payload.halves.hi) == (1, 2)
        assert len(fp.legs) == 16
        assert fp.legs[-1].phase == tg.FlightPlan.Phase.Cruise   # initialiseur par defaut
        d = fp.to_dict()
        assert d["legs"][2]["from_"]["position"]["x"] == 3.0
        c.g_sensors[2].value = 7.5                  # tableau global de structures
        assert len(c.g_sensors) == 4
    """)
    callsign, phase, raw = out["PLAN"].split()
    assert (callsign, int(raw)) == ("AF123", 0x00020001)
    assert int(phase) == 2      # Phase::Climb
    import struct
    sensor = built[1]["testgen::SensorSample"]
    raw = bytes.fromhex(out["SENSOR2"])
    assert struct.unpack_from("<d", raw, _field(sensor, "value").abs_offset)[0] == 7.5


def test_empreintes_et_stub(built, tmp_path):
    models = built[1]
    out = run(built, tmp_path, """
        import sut
        print("HASH", sut.__scry_layout_hashes__["cases::Sample"])
        print("SIZE", sut.cases.Sample.__scry_layout__["sizeof"])
    """)
    assert int(out["HASH"]) == models["cases::Sample"].layout_hash
    assert int(out["SIZE"]) == models["cases::Sample"].size
    stub = (built[3] / "sut.pyi").read_text(encoding="utf-8")
    assert 'g_sample: "cases.Sample"' in stub
    assert 'g_version: "int"  # const' in stub
    assert 'g_current: "Optional[cases.Sample]"' in stub


def test_fonctions_collectees_avec_leur_nature(built):
    par_signature = {fn.signature: fn for fn in built[4]}
    assert "void cases::remettre_a_zero()" in par_signature
    assert "int cases::util::doubler(int)" in par_signature
    # Deux surcharges : c'est la signature qui les distingue, pas le nom.
    assert sum(1 for s in par_signature if "cases::additionner(" in s) == 2
    assert par_signature["double cases::compute_trim(::cases::Sample const &)"].is_inline is False
    assert par_signature["int cases::journaliser(char const *, ...)"].is_variadic
    methode = par_signature["double cases::Moteur::marge(double) const"]
    assert (methode.owner, methode.is_const, methode.is_method) == ("cases::Moteur", True, True)
    assert par_signature["int cases::Moteur::version()"].is_static
    assert par_signature["int cases::Moteur::virtuelle()"].is_virtual
    assert par_signature["int cases::Moteur::cachee()"].access == "private"


def test_methodes_appelees_depuis_python(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        m = c.g_moteur
        m.pousser(1.5)                       # defaut repetitions=1
        m.pousser(1.0, 3)                    # argument nomme possible aussi
        m.pousser(delta=0.5, repetitions=2)
        assert m.marge(10.0) == 10.0 - m.regime
        m.choisir(c.Speed.Fast)
        assert m.choisie() == c.Speed.Fast    # enum en retour
        assert c.Moteur.version() == 7        # methode statique
        assert m.calibrer(3) == 3 and m.calibrer(2.9) == 2       # surcharges
        m.echantillon().from_ = 12            # vue sur un membre, pas une copie
        assert m.echantillon().from_ == 12
        assert "Remet le moteur a l'arret." in c.Moteur.couper.__doc__
        for stmt, exc in [("m.virtuelle()", AttributeError),
                          ("m.declaree()", AttributeError),
                          ("m.cachee()", AttributeError)]:
            try:
                exec(stmt)
                raise SystemExit("aucune erreur : " + stmt)
            except exc:
                pass
    """)
    assert out["MOTEUR"] == "5.5 10"     # 1.5 + 3*1.0 + 2*0.5 ; Speed::Fast == 10


def test_fonctions_libres_appelees_depuis_python(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        c.g_sample.from_ = 5
        c.remettre_a_zero()
        assert c.g_sample.from_ == 0
        assert c.etiquette() == "cases"                  # const char* -> str
        assert c.additionner(2, 3) == 5                  # surcharges libres
        assert c.additionner(0.5, 0.25) == 0.75
        assert c.util.doubler(21) == 42                  # namespace imbrique
        # Structure en argument, par reference : la fonction ecrit dedans.
        assert c.appliquer(c.g_moteur, c.Speed.Slow) == 2.5
        assert c.g_moteur.allure == c.Speed.Slow
        # Reference en retour : une VUE, pas une copie.
        vue = c.moteur_courant()
        vue.regime = 99.0
        assert c.g_moteur.regime == 99.0
        assert vue.__address__ == c.g_moteur.__address__
        for stmt in ["c.compute_trim(c.g_sample)", "c.journaliser('x')"]:
            try:
                exec(stmt)
                raise SystemExit("aucune erreur : " + stmt)
            except AttributeError:
                pass
    """)
    assert out["MOTEUR"] == "99 3"       # Speed::Slow == 3


def test_stub_declare_les_fonctions(built):
    stub = (built[3] / "sut.pyi").read_text(encoding="utf-8")
    assert 'def doubler(v: "int") -> "int": ...' in stub
    assert 'def marge(self, plafond: "float") -> "float": ...' in stub
    assert 'def pousser(self, delta: "float", repetitions: "int" = ...) -> "None": ...' in stub
    assert 'def moteur_courant() -> "cases.Moteur": ...' in stub
    assert 'def choisie(self) -> "cases.Speed": ...' in stub
    # Deux surcharges : sans @overload, la seconde masquerait la premiere.
    assert stub.count("@overload") == 4
    assert "@staticmethod\n        def version() -> \"int\": ..." in stub
    # Une fonction non liee n'a rien a promettre dans le stub.
    assert "compute_trim" not in stub


def test_le_header_genere_dit_pourquoi_une_fonction_manque(built):
    header = (built[3] / "scry_pybind.generated.h").read_text(encoding="utf-8")
    assert "cases::compute_trim" in header and "le module ne se lierait pas" in header
    assert "cases::journaliser" in header and "variadique" in header
    assert "cases::Moteur::virtuelle" in header and "methode virtuelle" in header
    assert "cases::Moteur::cachee" in header and "methode private" in header


def test_vector_numerique_est_une_vue_numpy(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        p = sut.cases.g_piste
        assert len(p.gains) == 3 and p.gains[1] == 2.0
        p.gains[2] = 9.5                  # ecrit a travers la vue
        assert p.gains.base is not None    # vue, pas copie
        p.gains = [4.0, 5.0]               # la taille suit la valeur donnee
        assert len(p.gains) == 2
        sut.cases.g_serie = [7.0, 8.0, 9.0]        # vector global
        assert list(sut.cases.g_serie) == [7.0, 8.0, 9.0]
    """)
    assert out["GAINS_N"] == "2"
    assert out["GAINS_V"] == "4 5"
    assert out["SERIE"] == "7 8 9"


def test_vector_de_structures_est_une_sequence_par_reference(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        p = sut.cases.g_piste
        assert len(p.reperes) == 2
        p.reperes[0].lat = 42.0            # reference, pas copie
        assert [r.lon for r in p.reperes] == [2.0, 4.0]   # iterable
        assert p.reperes[-1].lat == 3.0                    # indice negatif
        try:
            p.reperes[2]
            raise SystemExit("indice hors bornes accepte")
        except IndexError:
            pass
        # Chaines et enums dans un vector.
        p.noms[1] = "est"
        assert p.noms[0] == "nord"
        assert p.allures[1] == sut.cases.Speed.Fast
        p.allures[0] = sut.cases.Speed.Max
        # to_dict traverse les vues comme les tableaux.
        assert p.to_dict()["reperes"][0]["lat"] == 42.0
        r = sut.cases.g_reperes                            # vector global
        r[1].lat = 33.0
    """)
    assert out["REPERE0"] == "42 2"
    assert out["NOMS"] == "nord est"
    assert out["ALLURE1"] == "10"
    assert out["REPERES_N"] == "2 33"


def test_une_vue_de_vector_survit_a_un_push_back(built, tmp_path):
    """La raison d'etre de VectorView : elle garde le CONTENEUR, pas ses
    octets. Un push_back du cote C++ peut deplacer tout le tampon ; la vue
    redemande data() et size() a chaque indexation, et reste donc juste."""
    run(built, tmp_path, """
        import sut
        p = sut.cases.g_piste
        vue = p.reperes
        avant = len(vue)
        for i in range(40):                      # de quoi forcer des reallocations
            sut.cases.ajouter_repere(p, float(i), -float(i))
        assert len(vue) == avant + 40            # la longueur est relue
        assert vue[avant].lat == 0.0             # et l'adresse aussi
        assert vue[-1].lon == -39.0
    """)


def test_paire_pointeur_compteur_declaree_en_span(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        p = sut.cases.g_piste
        assert len(p.bornes) == 3                  # Repere* + nb_bornes
        p.bornes[1].lat = 77.0
        assert [b.lon for b in p.bornes] == [20.0, 21.0, 22.0]
        m = p.mesures                               # const double* + nb_mesures
        assert list(m) == [0.5, 1.5, 2.5, 3.5]
        assert m.flags.writeable is False           # le const est garde
        # Le pointeur nul donne une sequence vide, pas un plantage.
        assert len(sut.cases.Piste().bornes) == 0
    """)
    assert out["BORNE1"] == "77 21"


def test_ce_qui_n_est_pas_exposable_est_explique(built):
    header = (built[3] / "scry_pybind.generated.h").read_text(encoding="utf-8")
    assert "drapeaux" in header and "std::vector<bool>" in header
    assert "figes" in header and "const" in header
    assert "opaque" in header and "ni structure decrite, ni nombre" in header
    stub = (built[3] / "sut.pyi").read_text(encoding="utf-8")
    assert 'gains: "numpy.ndarray"' in stub
    assert 'reperes: "VectorView[cases.Repere]"' in stub
    assert 'noms: "VectorView[str]"' in stub
    assert 'bornes: "ArrayView[cases.Repere]"' in stub
    assert 'mesures: "numpy.ndarray"' in stub
    assert "drapeaux" not in stub and "figes" not in stub


def test_heritage_prive_et_docstrings(built, tmp_path):
    out = run(built, tmp_path, """
        import sut
        c = sut.cases
        child = c.g_child
        child.base_value = 3          # membre herite, ecrit en place
        child.weight = 2.5
        child.extra = 9
        assert "base_value" in c.Child.__scry_fields__
        h = c.g_hidden
        assert h.shown == 1
        assert not hasattr(h, "secret_")        # prive : jamais nomme
        assert "valeur portee par la base" in c.Child.base_value.__doc__
        assert c.Base.__doc__ == "Une base documentee."
        assert "enfant documente" in type(c).g_child.__doc__
    """)
    assert out["CHILD"] == "3 2.5 9"


# -- liste blanche d'ecriture -------------------------------------------------
def test_liste_blanche_refuse_les_ecritures_non_autorisees(built_lecture_seule, tmp_path):
    """Un module compile avec 'writable = cases::Sample::from; cases::g_speed'.
    Tout le reste doit se lire et refuser l'ecriture, a l'execution."""
    out = run(built_lecture_seule, tmp_path, """
        import sut
        c = sut.cases
        s = c.g_sample
        # Ce qui est nomme garde son setter.
        s.from_ = 21
        c.g_speed = c.Speed.Fast
        # Tout le reste se lit...
        assert s.mode is not None and s.tag == "" or True
        assert len(s.values) == 4
        assert c.g_callsign == "F-GKXA"
        # ... et refuse l'ecriture.
        refuses = [
            ("s.mode = 1", AttributeError),            # scalaire
            ("s.speed = c.Speed.Max", AttributeError), # enum
            ("s.armed = 1", AttributeError),           # champ de bits
            ("s.tag = 'AB'", AttributeError),          # char[N]
            ("s.values = [1.0] * 4", AttributeError),  # tableau numerique
            ("s.values[0] = 1.0", ValueError),         # ... et sa vue numpy
            ("c.g_callsign = 'N1'", AttributeError),   # chaine globale
            ("c.g_gains = [1.0] * 3", AttributeError), # tableau global
            ("c.g_gains[0] = 1.0", ValueError),
            ("c.inner.g_ticks = 5", AttributeError),   # namespace imbrique
        ]
        for stmt, exc in refuses:
            try:
                exec(stmt)
                raise SystemExit("ecriture acceptee : " + stmt)
            except exc:
                pass
    """)
    model_ = built_lecture_seule[1]["cases::Sample"]
    src = BufferSource(bytes.fromhex(out["SAMPLE"]))
    assert memory.decode(src, _field(model_, "from")) == "21"
    assert out["SPEED"] == "10"
    # Rien n'a bouge la ou l'ecriture etait refusee.
    assert out["CALLSIGN"] == "F-GKXA"
    assert out["GAINS"] == "1 2 3"


def test_liste_blanche_les_vues_de_structures_restent_pilotees_par_leurs_membres(
        built_lecture_seule, tmp_path):
    """La granularite est le type et son membre : ce n'est pas la vue qui est
    fermee, ce sont les membres du type de l'element."""
    run(built_lecture_seule, tmp_path, """
        import sut
        c = sut.cases
        p = c.g_piste
        assert len(p.reperes) == 2 and p.reperes[0].lon == 2.0
        try:
            p.reperes[0].lat = 1.0          # cases::Repere::lat n'est pas nomme
            raise SystemExit("ecriture acceptee dans une vue")
        except AttributeError:
            pass
        assert len(p.bornes) == 3           # un span se lit toujours
    """)


def test_le_header_genere_dit_qui_reste_inscriptible(built_lecture_seule):
    header = (built_lecture_seule[3] / "scry_pybind.generated.h").read_text(encoding="utf-8")
    assert 'detail::field(c' in header
    assert ', false);' in header and ', true);' in header
