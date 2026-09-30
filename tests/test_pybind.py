"""Generation pybind11 : rendu du header, du stub et des noms, sans compiler."""

import re
from pathlib import Path

from scry import model
from scry.codegen import pybind
from scry.config import load_config

EXAMPLE_INI = Path(__file__).resolve().parent.parent / "scry.ini.example"


def F(name, offset, size, kind=model.FUNDAMENTAL, type_name="int", **kw):
    return model.Field(name=name, type_name=type_name, kind=kind, offset=offset,
                       abs_offset=offset, size=size, access_path="obj." + name, **kw)


def _struct():
    item = F("[]", 0, 8, model.STRUCT, "Item", qualified_type="ns::Item",
             children=[F("id", 0, 8, type_name="long long int")])
    return model.Struct(name="ns::S", size=160, align=8, header="s.h", fields=[
        F("count", 0, 4),
        F("mode", 4, 1, model.ENUM, "Mode", enum_items=[("Off", 0), ("On", 10)],
          enum_type="ns::Mode", qualified_type="ns::Mode"),
        F("flag", 5, 1, type_name="bool", bit_width=1, bit_offset=0),
        F("label", 8, 8, model.ARRAY, "char [8]", array_len=8, elem_type="char"),
        F("values", 16, 32, model.ARRAY, "double [4]", array_len=4, elem_type="double"),
        F("items", 48, 16, model.ARRAY, "ns::Item [2]", array_len=2, elem_type="ns::Item",
          children=[item]),
        F("next", 64, 8, model.POINTER, "ns::S *"),
        F("from", 72, 4),
        F("origin", 80, 16, model.STRUCT, "<struct anonyme>", is_anonymous=True,
          children=[F("lat", 0, 8, type_name="double")]),
        F("inner", 96, 8, model.STRUCT, "Inner", qualified_type="ns::S::Inner",
          children=[F("x", 0, 8, type_name="double")]),
        F("name", 104, 32, model.CLASS, "basic_string<char>",
          qualified_type="std::basic_string<char, std::char_traits<char>, std::allocator<char>>"),
        F("list", 136, 24, model.CLASS, "vector<int>",
          qualified_type="std::vector<int, std::allocator<int>>"),
    ])


def _vec(name, offset, qualified, elem, is_const=False):
    """Membre std::vector : son element est decrit a part, car il n'est pas
    dans la structure."""
    return F(name, offset, 24, model.CLASS, qualified.split("::")[-1],
             qualified_type=qualified, container="vector", elem=elem, is_const=is_const)


def _struct_stl():
    item = F("[]", 0, 8, model.STRUCT, "Item", qualified_type="ns::Item",
             children=[F("id", 0, 8, type_name="long long int")])
    return model.Struct(name="ns::P", size=240, align=8, header="p.h", fields=[
        _vec("gains", 0, "std::vector<double>", F("[]", 0, 8, type_name="double")),
        _vec("items", 24, "std::vector<ns::Item>", item),
        _vec("noms", 48, "std::vector<std::basic_string<char>>",
             F("[]", 0, 32, model.CLASS, "basic_string<char>",
               qualified_type="std::basic_string<char>")),
        _vec("modes", 72, "std::vector<ns::Mode>",
             F("[]", 0, 1, model.ENUM, "Mode", enum_type="ns::Mode",
               qualified_type="ns::Mode", enum_items=[("Off", 0), ("On", 10)])),
        _vec("drapeaux", 96, "std::vector<bool>", F("[]", 0, 1, type_name="bool")),
        _vec("figes", 120, "std::vector<ns::Item>", item, is_const=True),
        _vec("inconnus", 144, "std::vector<autre::T>",
             F("[]", 0, 8, model.STRUCT, "T", qualified_type="autre::T")),
        F("bornes", 168, 8, model.POINTER, "ns::Item *", qualified_type="ns::Item"),
        F("nb_bornes", 176, 4),
        F("mesures", 184, 8, model.POINTER, "double const *"),
        F("nb_mesures", 192, 2, type_name="short unsigned int"),
        F("opaque", 200, 8, model.POINTER, "void *"),
    ])


def _render():
    s = _struct()
    return s, pybind.render([s], load_config(EXAMPLE_INI))


def test_noms():
    assert pybind.split_last("a::B<c::D, 8>::E") == ("a::B<c::D, 8>", "E")
    assert pybind.py_type_name("RingBuffer<testgen::SensorSample, 8>") == "RingBuffer_SensorSample_8"
    assert pybind.py_identifier("from") == "from_"
    assert pybind.py_identifier("lat") == "lat"


def test_types_portees_et_enums():
    _, text = _render()
    assert "using T0 = ns::S;" in text
    assert 'py::module_ m_ns = m.def_submodule("ns");' in text
    assert 'detail::class_t<T0> c0(m_ns, "S");' in text
    # Type imbrique : porte par la classe parente.
    assert '(c0, "Inner");' in text
    # Type anonyme : decltype, nomme d'apres le membre.
    assert "decltype(T0::origin)" in text and '"origin_t"' in text
    assert 'py::enum_<E0>(m_ns, "Mode")' in text
    assert '.value("On", E0::On)' in text


def test_regles_des_membres():
    _, text = _render()
    assert 'detail::field(c0, "count", &T0::count, true);' in text
    assert "o.flag = v;" in text                              # champ de bits
    assert "detail::char_get(o.label)" in text
    assert "detail::numeric_view(self, self.cast<T0&>().values, true)" in text
    assert "detail::make_view(o.items)" in text
    assert 'detail::bind_view<' in text and '"_ArrayView_ns_Item"' in text
    assert "reinterpret_cast<std::uintptr_t>(o.next)" in text
    assert 'detail::field(c0, "from_", &T0::from, true);' in text   # mot-cle Python
    assert 'detail::field(c0, "name", &T0::name, true);' in text    # std::string
    assert "// list : std::vector non liee" in text


def test_services_et_empreinte():
    s, text = _render()
    assert 'offsets["from_"] = 72;' in text
    assert 'layout["layout_hash"] = py::int_(0x%016Xull);' % s.layout_hash in text
    assert 'hashes["ns::S"] = py::int_(0x%016Xull);' % s.layout_hash in text
    assert '"ns.S", py::make_tuple("count", "mode", "flag", "label"' in text


def test_stub_pyi():
    s = _struct()
    stub = pybind.render_stub(pybind.Binder([s]), [("inputs", "ns::S")])
    assert "class ns:  # namespace ns" in stub
    assert "    class S:  # ns::S" in stub
    assert '        from_: "int"' in stub
    assert '        label: "str"' in stub
    assert '        values: "numpy.ndarray"' in stub
    assert '        items: "ArrayView[ns.Item]"' in stub
    assert '        mode: "ns.Mode"' in stub
    assert 'inputs: "ns.S"' in stub
    compile(stub, "sut.pyi", "exec")          # syntaxe Python valide


# -- variables globales ----------------------------------------------------------
def V(qualified, field, is_const=False):
    field.access_path = qualified
    return model.Variable(name=qualified.rpartition("::")[2], qualified_name=qualified,
                          field=field, is_const=is_const, header="app/vars.h")


def _variables():
    s = _struct()
    return s, [
        V("app::g_s", F("g_s", 0, 160, model.STRUCT, "S", qualified_type="ns::S",
                        children=list(s.fields))),
        V("app::g_t", F("g_t", 0, 8, type_name="double")),
        V("app::g_mode", F("g_mode", 0, 1, model.ENUM, "Mode", enum_type="ns::Mode",
                           enum_items=[("Off", 0), ("On", 10)], qualified_type="ns::Mode")),
        V("app::g_v", F("g_v", 0, 24, model.ARRAY, "double [3]", array_len=3, elem_type="double")),
        V("app::g_name", F("g_name", 0, 8, model.ARRAY, "char [8]", array_len=8, elem_type="char")),
        V("app::g_ptr", F("g_ptr", 0, 8, model.POINTER, "ns::S *", qualified_type="ns::S")),
        V("app::g_raw", F("g_raw", 0, 8, model.POINTER, "void *")),
        V("app::sub::g_n", F("g_n", 0, 4), is_const=True),
        V("g_racine", F("g_racine", 0, 4, type_name="float")),
        V("app::g_list", F("g_list", 0, 24, model.CLASS, "vector<int>",
                           qualified_type="std::vector<int>")),
    ]


def test_globales_une_propriete_par_nature():
    s, variables = _variables()
    text = pybind.render([s], load_config(EXAMPLE_INI), variables=variables)
    expected = [
        'globals.object("app", "g_s", []() -> auto& { return ::app::g_s; }, true);',
        'globals.value("app", "g_t", []() -> auto& { return ::app::g_t; }, true);',
        'globals.value("app", "g_mode", []() -> auto& { return ::app::g_mode; }, true);',
        'globals.numeric("app", "g_v", []() -> auto& { return ::app::g_v; }, true);',
        'globals.text("app", "g_name", []() -> auto& { return ::app::g_name; }, true);',
        'globals.pointee("app", "g_ptr", []() -> auto& { return ::app::g_ptr; }, true);',
        'globals.address("app", "g_raw", []() -> auto& { return ::app::g_raw; }, true);',
        'globals.value("app::sub", "g_n", []() -> auto& { return ::app::sub::g_n; }, true);',
        'globals.value("", "g_racine", []() -> auto& { return ::g_racine; }, true);',
        "// app::g_list : std::vector non liee (STL, pas un POD)",
    ]
    for line in expected:
        assert line in text, line
    assert "inline void register_all(py::module_& m)" in text
    # Plus de chemin 'buffer Python' : les vues ne visent que la memoire C++.
    assert "from_buffer" not in text and "to_bytes" not in text


def test_filtres_expose_et_hide(tmp_path):
    _, variables = _variables()
    ini = tmp_path / "scry.ini"
    ini.write_text("[pybind]\nexpose = app::*\nhide = app::g_raw; *::sub::*\n",
                   encoding="utf-8")
    kept = [v.qualified_name for v in pybind.select_variables(variables, load_config(ini))]
    assert "g_racine" not in kept and "app::g_raw" not in kept and "app::sub::g_n" not in kept
    assert "app::g_s" in kept
    assert len(pybind.select_variables(variables, load_config(EXAMPLE_INI))) == len(variables)


# -- fonctions ---------------------------------------------------------------
def R(cpp, kind=model.FUNDAMENTAL, type_name="int", size=4, **kw):
    """TypeRef d'un type de signature. cpp porte const, & et *, base le type nu."""
    base = None if kind is None else model.Field(name="", type_name=type_name, kind=kind,
                                                 size=size, **kw)
    return model.TypeRef(cpp=cpp, base=base, is_reference=cpp.endswith("&"),
                         is_pointer=cpp.endswith("*"), is_const="const" in cpp)


def A(name, ref, default=""):
    return model.Argument(name=name, type=ref, default=default)


VOID = model.TypeRef(cpp="void")
INT = R("int")
DOUBLE = R("double", type_name="double", size=8)
ETAT = R("::ns::S &", model.STRUCT, "S", 160, qualified_type="ns::S")
MODE = R("::ns::Mode", model.ENUM, "Mode", 1, enum_type="ns::Mode",
         qualified_type="ns::Mode", enum_items=[("Off", 0), ("On", 10)])
CSTR = R("char const *", type_name="char", size=1)


def Fn(qualified, returns=VOID, args=(), owner="", **kw):
    kw.setdefault("is_inline", True)
    return model.Function(name=qualified.rpartition("::")[2], qualified_name=qualified,
                          returns=returns, args=list(args), owner=owner,
                          header="app/api.h", **kw)


def _functions():
    return [
        Fn("ns::reset"),
        Fn("ns::regler", args=[A("m", MODE), A("v", DOUBLE, default="1.5")]),
        Fn("ns::courant", returns=ETAT),
        Fn("ns::nom", returns=CSTR),
        Fn("ns::somme", returns=INT, args=[A("a", INT)]),
        Fn("ns::somme", returns=DOUBLE, args=[A("a", DOUBLE)]),
        Fn("ns::sub::doubler", returns=INT, args=[A("v", INT)]),
        Fn("ns::S::marge", returns=DOUBLE, args=[A("p", DOUBLE)], owner="ns::S",
           is_const=True, doc="Marge restante."),
        Fn("ns::S::version", returns=INT, owner="ns::S", is_static=True),
        # Chacune non liable, pour une raison differente.
        Fn("ns::externe", returns=INT, is_inline=False),
        Fn("ns::trace", returns=INT, args=[A("f", CSTR)], is_variadic=True),
        Fn("ns::S::virtuelle", returns=INT, owner="ns::S", is_virtual=True),
        Fn("ns::S::cachee", returns=INT, owner="ns::S", access="private"),
        Fn("ns::listes", returns=R("::std::vector<int>", model.CLASS, "vector<int>", 24,
                                   qualified_type="std::vector<int>")),
        Fn("ns::inconnue", args=[A("t", R("::autre::T &", model.STRUCT, "T", 8,
                                          qualified_type="autre::T"))]),
    ]


def _render_functions(ini=None):
    s = _struct()
    return pybind.render([s], load_config(ini or EXAMPLE_INI), functions=_functions())


def test_fonctions_libres_et_methodes():
    text = _render_functions()
    expected = [
        'detail::submodule(m, "ns").def("reset", &::ns::reset);',
        'detail::submodule(m, "ns").def("regler", &::ns::regler, py::arg("m"),'
        ' py::arg("v") = 1.5);',
        # Reference en retour : une vue, sinon pybind11 copierait l'objet.
        'detail::submodule(m, "ns").def("courant", &::ns::courant,'
        ' py::return_value_policy::reference);',
        'detail::submodule(m, "ns").def("nom", &::ns::nom);',
        'detail::submodule(m, "ns::sub").def("doubler", &::ns::sub::doubler, py::arg("v"));',
        # Methode : sur l'objet py::class_ de sa classe, avec son commentaire.
        'c0.def("marge", &T0::marge, "Marge restante.", py::arg("p"));',
        'c0.def_static("version", &T0::version);',
    ]
    for line in expected:
        assert line in text, line
    assert "inline void register_functions(py::module_& m)" in text
    # register_globals ferme le module : il doit passer apres les fonctions.
    assert text.index("register_functions(m);") < text.index("register_globals(m);")


def test_surcharges_levees_par_la_signature():
    text = _render_functions()
    assert ('detail::submodule(m, "ns").def("somme", static_cast<int (*)(int)>(&::ns::somme),'
            ' py::arg("a"));') in text
    assert ('detail::submodule(m, "ns").def("somme",'
            ' static_cast<double (*)(double)>(&::ns::somme), py::arg("a"));') in text


def test_chaque_refus_est_explique_dans_le_code_genere():
    text = _render_functions()
    for fragment in [
            "ns::externe() : declaree sans definition dans le header",
            "variadique, sans equivalent en Python",
            "methode virtuelle",
            "methode private",
            "std::vector non liee (STL, pas un POD)",
            "type autre::T absent du module",
    ]:
        assert fragment in text, fragment


def test_une_fonction_seulement_declaree_se_force_par_son_nom(tmp_path):
    functions = _functions()
    ini = tmp_path / "scry.ini"
    # Nomme sans joker : autorisation explicite de lier un symbole externe.
    ini.write_text("[pybind]\nfunctions = ns::externe; ns::S::*\n", encoding="utf-8")
    bound = pybind.select_functions(functions, load_config(ini))
    noms = {bf.fn.qualified_name for bf in bound}
    assert noms == {"ns::externe", "ns::S::marge", "ns::S::version", "ns::S::virtuelle",
                    "ns::S::cachee"}
    assert [bf.explicit for bf in bound if bf.fn.qualified_name == "ns::externe"] == [True]

    text = pybind.render([_struct()], load_config(ini), functions=functions)
    assert 'detail::submodule(m, "ns").def("externe", &::ns::externe);' in text

    # Un joker ne suffit pas : il ne dit pas que l'on assume l'edition de liens.
    large = tmp_path / "large.ini"
    large.write_text("[pybind]\nfunctions = ns::*\n", encoding="utf-8")
    text = pybind.render([_struct()], load_config(large), functions=functions)
    assert "ns::externe() : declaree sans definition dans le header" in text


def test_hide_functions_emporte_sur_functions(tmp_path):
    ini = tmp_path / "scry.ini"
    ini.write_text("[pybind]\nfunctions = ns::*\nhide_functions = *::somme; ns::sub::*\n",
                   encoding="utf-8")
    noms = {bf.fn.qualified_name for bf in
            pybind.select_functions(_functions(), load_config(ini))}
    assert "ns::somme" not in noms and "ns::sub::doubler" not in noms
    assert "ns::reset" in noms


def test_defaut_non_reproductible_devient_obligatoire():
    risque = Fn("ns::bizarre", args=[A("a", INT), A("m", MODE, default="(Mode)0"),
                                     A("v", DOUBLE, default="2.0")])
    text = pybind.render([_struct()], load_config(EXAMPLE_INI), functions=[risque])
    # '(Mode)0' ne se reecrit pas sans risque : ni lui ni ce qui suit ne
    # recoit de defaut, car le C++ comme pybind11 les veulent en queue.
    assert ('def("bizarre", &::ns::bizarre, py::arg("a"), py::arg("m"), py::arg("v"));'
            in text)
    sur = Fn("ns::sur", args=[A("m", MODE, default="::ns::Mode::On")])
    text = pybind.render([_struct()], load_config(EXAMPLE_INI), functions=[sur])
    assert 'py::arg("m") = ::ns::Mode::On' in text


def test_stub_declare_fonctions_et_surcharges():
    binder = pybind.Binder([_struct()], (),
                           pybind.select_functions(_functions(), load_config(EXAMPLE_INI)))
    stub = pybind.render_stub(binder)
    assert 'def reset() -> "None": ...' in stub
    assert 'def regler(m: "ns.Mode", v: "float" = ...) -> "None": ...' in stub
    assert 'def courant() -> "ns.S": ...' in stub
    assert 'def marge(self, p: "float") -> "float": ...' in stub
    assert '@staticmethod\n        def version() -> "int": ...' in stub
    assert stub.count("@overload") == 2
    # Un namespace qui n'a qu'une fonction existe quand meme dans le stub.
    assert "class sub:  # namespace ns::sub" in stub
    assert 'def doubler(v: "int") -> "int": ...' in stub
    assert "externe" not in stub and "virtuelle" not in stub
    compile(stub, "sut.pyi", "exec")


# -- conteneurs STL et paires pointeur + compteur ----------------------------
def _item_struct():
    return model.Struct(name="ns::Item", size=8, align=8, header="p.h",
                        fields=[F("id", 0, 8, type_name="long long int")])


def _render_stl(tmp_path=None, spans=""):
    structs = [_struct_stl(), _item_struct()]
    if spans:
        ini = tmp_path / "scry.ini"
        ini.write_text("[pybind]\nspans = %s\n" % spans, encoding="utf-8")
        cfg = load_config(ini)
    else:
        cfg = load_config(EXAMPLE_INI)
    return structs, cfg, pybind.render(structs, cfg)


def test_vector_numerique_en_vue_numpy_et_structures_en_sequence():
    _, _, text = _render_stl()
    assert 'detail::vector_member(c0, "gains", &T0::gains, true);' in text
    assert 'detail::vector_member(c0, "items", &T0::items, true);' in text
    # Une classe de vue par TYPE de vector, et le type vient du membre :
    # reecrire 'std::vector<...>' laisserait l'allocateur a deviner.
    assert 'detail::bind_vector_view<decltype(T0::items)>(m, "_VectorView_ns_Item", true);' in text
    assert 'detail::bind_vector_view<decltype(T0::noms)>(m, "_VectorView_str", true);' in text
    assert 'detail::bind_vector_view<decltype(T0::modes)>(m, "_VectorView_ns_Mode", true);' in text
    # Numerique : aucune classe de vue, c'est numpy qui la porte.
    assert "decltype(T0::gains)" not in text


def test_vector_non_exposable_est_explique():
    _, _, text = _render_stl()
    assert "drapeaux : std::vector<bool> : specialisation a champs de bits" in text
    assert "figes : std::vector const d'elements non numeriques" in text
    assert "inconnus : std::vector : type autre::T absent du module" in text
    # Aucune classe de vue n'est enregistree pour ce que l'on n'expose pas.
    assert "_VectorView_autre_T" not in text
    assert "decltype(T0::figes)" not in text


def test_une_seule_vue_par_type_de_vector():
    """Deux membres du meme type de vector partagent une classe Python : la
    declarer deux fois serait refuse a l'execution par pybind11."""
    s = _struct_stl()
    item = s.fields[1].elem
    s.fields.append(_vec("autres", 208, "std::vector<ns::Item>", item))
    text = pybind.render([s, _item_struct()], load_config(EXAMPLE_INI))
    assert text.count('bind_vector_view<decltype(T0::items)>') == 1
    assert "_VectorView_ns_Item" in text
    assert 'detail::vector_member(c0, "autres", &T0::autres, true);' in text


def test_span_pairs_lit_la_configuration(tmp_path):
    ini = tmp_path / "scry.ini"
    ini.write_text("[pybind]\nspans = ns::P::bornes: nb_bornes; ns::P::mesures:nb_mesures;"
                   " incomplet; ns::P::x: 3invalide\n", encoding="utf-8")
    # Le separateur est un ':' seul : celui de 'ns::P' n'en est pas un.
    assert pybind.span_pairs(load_config(ini)) == {
        ("ns::P", "bornes"): "nb_bornes", ("ns::P", "mesures"): "nb_mesures"}


def test_span_pointeur_et_compteur(tmp_path):
    _, _, text = _render_stl(tmp_path, "ns::P::bornes: nb_bornes; ns::P::mesures: nb_mesures")
    assert 'detail::span_member(c0, "bornes", &T0::bornes, &T0::nb_bornes);' in text
    assert 'detail::span_member(c0, "mesures", &T0::mesures, &T0::nb_mesures);' in text
    # Le type pointe recoit sa vue, comme un tableau de structures.
    assert 'detail::bind_view<T1>(m, "_ArrayView_ns_Item", true);' in text
    # Sans declaration, un pointeur reste une adresse en lecture seule.
    _, _, sans = _render_stl()
    assert 'reinterpret_cast<std::uintptr_t>(o.bornes)' in sans


def test_span_mal_declare_donne_un_commentaire_pas_un_build_casse(tmp_path):
    """Une faute de frappe dans scry.ini ne doit pas casser la compilation de
    l'application : elle doit se lire dans le code genere."""
    _, _, text = _render_stl(tmp_path, "ns::P::bornes: nb_bidon; ns::P::opaque: nb_bornes;"
                                       " ns::P::nb_bornes: nb_bornes; ns::Absente::p: n")
    assert "bornes : [pybind] spans : compteur 'nb_bidon' introuvable" in text
    assert "opaque : [pybind] spans : pointeur vers void * : ni structure decrite" in text
    assert "n'est pas un membre pointeur de ns::P" in text
    assert "ns::Absente::p : [pybind] spans : classe ns::Absente absente du module" in text
    # Aucun appel genere : seule la definition du modele reste dans detail.
    assert "detail::span_member(" not in text
    # Le pointeur garde son exposition ordinaire, une adresse en lecture seule.
    assert "reinterpret_cast<std::uintptr_t>(o.bornes)" in text


def test_span_sur_un_membre_sans_adresse(tmp_path):
    """span_member prend deux pointeurs sur membre. Un membre non public,
    statique ou champ de bits n'en a pas : le C++ ne compilerait pas."""
    ini = tmp_path / "scry.ini"
    ini.write_text("[pybind]\nspans = ns::P::bornes: nb_bornes\n", encoding="utf-8")
    cfg = load_config(ini)
    for attribut, valeur, attendu in [("access", "private", "un membre private"),
                                      ("is_static", True, "un membre statique")]:
        s = _struct_stl()
        setattr(_par_nom(s, "bornes"), attribut, valeur)
        text = pybind.render([s, _item_struct()], cfg)
        assert attendu in text, attendu
        assert "detail::span_member(" not in text
    # Un compteur en champ de bits est refuse pour la meme raison.
    s = _struct_stl()
    _par_nom(s, "nb_bornes").bit_width = 12
    text = pybind.render([s, _item_struct()], cfg)
    assert "un champ de bits" in text and "detail::span_member(" not in text


def _par_nom(struct, name):
    return next(f for f in struct.fields if f.name == name)


def test_stub_distingue_les_deux_sortes_de_vues(tmp_path):
    structs, cfg, _ = _render_stl(tmp_path, "ns::P::bornes: nb_bornes")
    binder = pybind.Binder(structs, (), (), pybind.span_pairs(cfg))
    stub = pybind.render_stub(binder)
    assert 'gains: "numpy.ndarray"' in stub
    assert 'items: "VectorView[ns.Item]"' in stub
    assert 'noms: "VectorView[str]"' in stub
    assert 'modes: "VectorView[ns.Mode]"' in stub
    assert 'bornes: "ArrayView[ns.Item]"' in stub
    # Les deux generiques sont declares, et leur difference dite.
    assert "class VectorView(Generic[_T])" in stub and "push_back" in stub
    assert "class ArrayView(Generic[_T])" in stub
    assert "drapeaux" not in stub and "figes" not in stub and "inconnus" not in stub
    compile(stub, "sut.pyi", "exec")


def test_vector_global(tmp_path):
    s = _struct_stl()
    variables = [
        V("app::g_serie", F("g_serie", 0, 24, model.CLASS, "vector<double>",
                            qualified_type="std::vector<double>", container="vector",
                            elem=F("[]", 0, 8, type_name="double"))),
        V("app::g_items", F("g_items", 0, 24, model.CLASS, "vector<Item>",
                            qualified_type="std::vector<ns::Item>", container="vector",
                            elem=s.fields[1].elem)),
    ]
    text = pybind.render([s, _item_struct()], load_config(EXAMPLE_INI), variables=variables)
    for nom in ("g_serie", "g_items"):
        assert ('globals.vector("app", "%s", []() -> auto& { return ::app::%s; }, true);'
                % (nom, nom)) in text
    binder = pybind.Binder([s, _item_struct()], variables)
    stub = pybind.render_stub(binder)
    assert 'g_serie: "numpy.ndarray"' in stub
    assert 'g_items: "VectorView[ns.Item]"' in stub


def test_membre_non_public_jamais_nomme_meme_dans_un_decltype():
    """include_non_public fait entrer les membres prives dans le modele. Le
    C++ genere ne doit pas les nommer, decltype compris : hors de la classe,
    'decltype(T::prive_)' ne compile pas plus que '&T::prive_'."""
    item = F("[]", 0, 8, model.STRUCT, "Item", qualified_type="ns::Item",
             children=[F("id", 0, 8, type_name="long long int")])
    s = model.Struct(name="ns::Q", size=56, align=8, header="q.h", fields=[
        _vec("cache", 0, "std::vector<ns::Item>", item),
        F("tableau", 24, 16, model.ARRAY, "ns::Item [2]", array_len=2,
          elem_type="ns::Item", children=[item]),
        F("ouvert", 40, 4),
    ])
    for f in s.fields[:2]:
        f.access = "private"
    text = pybind.render([s, _item_struct()], load_config(EXAMPLE_INI))
    assert "cache : membre private, non expose" in text
    assert "tableau : membre private, non expose" in text
    assert "decltype(T0::cache)" not in text and "T0::tableau" not in text
    assert 'detail::field(c0, "ouvert", &T0::ouvert, true);' in text


def test_type_imbrique_vu_seulement_comme_element_de_vector():
    """Sans cela, un std::vector<Truc> dont Truc n'apparait nulle part ailleurs
    serait ecarte pour un type « absent du module »."""
    interne = F("[]", 0, 8, model.STRUCT, "Interne", qualified_type="ns::P::Interne",
                children=[F("v", 0, 8, type_name="double")])
    s = model.Struct(name="ns::P", size=24, align=8, header="p.h", fields=[
        _vec("morceaux", 0, "std::vector<ns::P::Interne>", interne)])
    text = pybind.render([s], load_config(EXAMPLE_INI))
    assert "using T1 = ns::P::Interne;" in text
    # Portee : le type imbrique est un attribut de sa classe parente.
    assert 'detail::class_t<T1> c1(c0, "Interne");' in text
    assert 'detail::field(c1, "v", &T1::v, true);' in text
    assert 'detail::vector_member(c0, "morceaux", &T0::morceaux, true);' in text
    assert '_VectorView_ns_P_Interne' in text


def test_vector_mode_decide_du_traitement():
    assert pybind.vector_mode(F("[]", 0, 8, type_name="double")) == "numeric"
    assert pybind.vector_mode(F("[]", 0, 8, model.STRUCT, "Item",
                                qualified_type="ns::Item")) == "view"
    # vector<bool> est une specialisation a champs de bits : pas de data().
    assert pybind.vector_mode(F("[]", 0, 1, type_name="bool")) == ""
    assert pybind.vector_mode(None) == ""


def test_stub_et_module_embarque():
    s, variables = _variables()
    binder = pybind.Binder([s], variables)
    stub = pybind.render_stub(binder)
    assert 'g_s: "ns.S"' in stub
    assert 'g_mode: "ns.Mode"' in stub
    assert 'g_ptr: "Optional[ns.S]"' in stub
    assert 'g_n: "int"  # const' in stub
    assert "class sub:  # namespace app::sub" in stub
    source = pybind.render_module(load_config(EXAMPLE_INI))
    assert "PYBIND11_EMBEDDED_MODULE(sut, m)" in source
    assert "scry::bind::register_all(m);" in source
    assert '#include "scry_pybind.generated.h"' in source


# -- liste blanche d'ecriture et lecture seule -------------------------------
def _ini(tmp_path, corps):
    path = tmp_path / "scry.ini"
    path.write_text("[pybind]\n" + corps, encoding="utf-8")
    return load_config(path)


def test_sans_liste_blanche_tout_reste_inscriptible():
    s, variables = _variables()
    text = pybind.render([s], load_config(EXAMPLE_INI), variables=variables)
    assert 'detail::field(c0, "count", &T0::count, true);' in text
    assert 'globals.value("app", "g_t", []() -> auto& { return ::app::g_t; }, true);' in text


def test_read_only_ferme_tout(tmp_path):
    s, variables = _variables()
    text = pybind.render([s], _ini(tmp_path, "read_only = true\n"), variables=variables)
    # Membres : plus aucun setter, quelle que soit la nature.
    assert 'detail::field(c0, "count", &T0::count, false);' in text
    assert 'detail::field(c0, "name", &T0::name, false);' in text
    assert 'def_property_readonly("flag"' in text          # champ de bits
    assert 'def_property_readonly("label"' in text          # char[N]
    assert 'def_property_readonly("values"' in text         # tableau numerique
    # La vue numpy elle-meme est fermee : sinon on ecrirait a travers elle.
    assert "detail::numeric_view(self, self.cast<T0&>().values, false)" in text
    assert "detail::numeric_assign" not in text.split("namespace detail")[-1].split(
        "inline void register_types")[1]
    # Variables globales.
    assert 'globals.value("app", "g_t", []() -> auto& { return ::app::g_t; }, false);' in text
    assert 'globals.numeric("app", "g_v", []() -> auto& { return ::app::g_v; }, false);' in text
    assert 'globals.text("app", "g_name", []() -> auto& { return ::app::g_name; }, false);' in text
    # Les vues perdent __setitem__ : remplacer un element est une ecriture.
    assert 'detail::bind_view<T1>(m, "_ArrayView_ns_Item", false);' in text


def test_read_only_par_la_ligne_de_commande_sans_toucher_au_ini():
    s, variables = _variables()
    cfg = load_config(EXAMPLE_INI)
    assert pybind.read_only_config(cfg) is False
    text = pybind.render([s], cfg, variables=variables, read_only=True)
    assert 'detail::field(c0, "count", &T0::count, false);' in text


def test_liste_blanche_sur_les_membres(tmp_path):
    s = _struct()
    cfg = _ini(tmp_path, "writable = ns::S::count; ns::S::label\n")
    text = pybind.render([s], cfg)
    assert 'detail::field(c0, "count", &T0::count, true);' in text
    assert 'detail::field(c0, "mode", &T0::mode, false);' in text
    # char[N] nomme : son setter reste.
    assert 'detail::char_set(o.label' in text
    # Le tableau numerique, non nomme, perd le sien et sa vue est fermee.
    assert "detail::numeric_view(self, self.cast<T0&>().values, false)" in text


def test_liste_blanche_sur_les_globales(tmp_path):
    s, variables = _variables()
    cfg = _ini(tmp_path, "writable = app::g_t; app::sub::*\n")
    text = pybind.render([s], cfg, variables=variables)
    assert 'globals.value("app", "g_t", []() -> auto& { return ::app::g_t; }, true);' in text
    assert 'globals.value("app::sub", "g_n", []() -> auto& { return ::app::sub::g_n; }, true);' \
        in text
    assert 'globals.value("app", "g_mode", []() -> auto& { return ::app::g_mode; }, false);' \
        in text


def test_un_motif_sans_joker_autorise_ce_qu_il_contient(tmp_path):
    """Meme convention que le filtrage des types et que [pybind] functions :
    nommer une portee, c'est nommer son contenu."""
    s = _struct()
    text = pybind.render([s], _ini(tmp_path, "writable = ns::S\n"))
    assert 'detail::field(c0, "count", &T0::count, true);' in text
    assert 'detail::field(c0, "mode", &T0::mode, true);' in text
    # Mais pas une autre classe.
    autre = model.Struct(name="ns::Autre", size=4, align=4, header="a.h",
                         fields=[F("x", 0, 4)])
    text = pybind.render([s, autre], _ini(tmp_path, "writable = ns::S\n"))
    assert re.search(r'detail::field\(c\d+, "x", &T\d+::x, false\);', text)


def test_read_only_l_emporte_sur_la_liste_blanche(tmp_path):
    s = _struct()
    cfg = _ini(tmp_path, "writable = ns::S::*\nread_only = true\n")
    text = pybind.render([s], cfg)
    assert 'detail::field(c0, "count", &T0::count, false);' in text


def test_vector_et_span_suivent_la_liste_blanche(tmp_path):
    structs = [_struct_stl(), _item_struct()]
    cfg = _ini(tmp_path, "writable = ns::P::gains\n"
                         "spans = ns::P::bornes: nb_bornes\n")
    text = pybind.render(structs, cfg)
    assert 'detail::vector_member(c0, "gains", &T0::gains, true);' in text
    assert 'detail::vector_member(c0, "items", &T0::items, false);' in text
    # Un span reste une vue : l'ecriture se joue sur les membres des elements.
    assert 'detail::span_member(c0, "bornes", &T0::bornes, &T0::nb_bornes);' in text


def test_la_granularite_est_le_type_et_non_le_chemin(tmp_path):
    """Il n'y a qu'un py::class_ par type : deux membres du meme type partagent
    donc leurs regles d'ecriture. C'est une limite, elle doit se voir."""
    inner = F("x", 0, 4)
    interne = model.Struct(name="ns::In", size=4, align=4, header="i.h", fields=[inner])
    s = model.Struct(name="ns::S2", size=8, align=4, header="s.h", fields=[
        F("a", 0, 4, model.STRUCT, "In", qualified_type="ns::In", children=[inner]),
        F("b", 4, 4, model.STRUCT, "In", qualified_type="ns::In", children=[inner]),
    ])
    text = pybind.render([s, interne], _ini(tmp_path, "writable = ns::S2::a\n"))
    # 'a' et 'b' se distinguent, eux, car ce sont des membres de ns::S2.
    assert 'detail::field(c0, "a", &T0::a, true);' in text
    assert 'detail::field(c0, "b", &T0::b, false);' in text
    # Mais leur contenu est le meme type : une seule regle pour ns::In::x.
    assert text.count('detail::field(c1, "x", &T1::x,') == 1
