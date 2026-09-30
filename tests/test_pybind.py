"""Generation pybind11 : rendu du header, du stub et des noms, sans compiler."""

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
    assert 'detail::field(c0, "count", &T0::count);' in text
    assert "o.flag = v;" in text                              # champ de bits
    assert "detail::char_get(o.label)" in text
    assert "detail::numeric_view(self, self.cast<T0&>().values)" in text
    assert "detail::make_view(o.items)" in text
    assert 'detail::bind_view<' in text and '"_ArrayView_ns_Item"' in text
    assert "reinterpret_cast<std::uintptr_t>(o.next)" in text
    assert 'detail::field(c0, "from_", &T0::from);' in text   # mot-cle Python
    assert 'detail::field(c0, "name", &T0::name);' in text    # std::string
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
        'globals.object("app", "g_s", []() -> auto& { return ::app::g_s; });',
        'globals.value("app", "g_t", []() -> auto& { return ::app::g_t; });',
        'globals.value("app", "g_mode", []() -> auto& { return ::app::g_mode; });',
        'globals.numeric("app", "g_v", []() -> auto& { return ::app::g_v; });',
        'globals.text("app", "g_name", []() -> auto& { return ::app::g_name; });',
        'globals.pointee("app", "g_ptr", []() -> auto& { return ::app::g_ptr; });',
        'globals.address("app", "g_raw", []() -> auto& { return ::app::g_raw; });',
        'globals.value("app::sub", "g_n", []() -> auto& { return ::app::sub::g_n; });',
        'globals.value("", "g_racine", []() -> auto& { return ::g_racine; });',
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
