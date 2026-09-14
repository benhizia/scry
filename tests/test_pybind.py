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
    assert 'py::class_<T0> c0(m_ns, "S");' in text
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
