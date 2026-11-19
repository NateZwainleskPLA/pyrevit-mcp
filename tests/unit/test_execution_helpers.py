import json
import re
from collections import OrderedDict
from io import StringIO
from types import SimpleNamespace

import pytest

from revit_mcp import execution_helpers
from revit_mcp.execution_helpers import RevitHelpers, build_hints


class Int64:
    def __init__(self, value):
        self.value = value
    def __int__(self):
        return self.value


class DotNetFloat:
    def __init__(self, value):
        self.value = value
    def __float__(self):
        return self.value


class DotNetBool:
    def __init__(self, value):
        self.value = value
    def __bool__(self):
        return self.value


class Category:
    pass


class Parameter:
    pass


class ElementId:
    def __init__(self, value):
        self.input = value
        self.Value = value


class XYZ:
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class NameDescriptor:
    def __get__(self, element):
        return element.hidden_name


@pytest.fixture
def helpers():
    db = SimpleNamespace(ElementId=ElementId, BuiltInCategory=Category,
                         BuiltInParameter=Parameter, XYZ=XYZ,
                         Element=SimpleNamespace(Name=NameDescriptor()))
    system = SimpleNamespace(**{name: Int64 for name in
        ["Int64", "Int32", "Int16", "Byte", "SByte", "UInt16", "UInt32", "UInt64"]})
    system.Double = system.Single = system.Decimal = DotNetFloat
    system.Boolean = DotNetBool
    return RevitHelpers(db, system)


def test_explicit_int64_and_large_id_roundtrip(helpers):
    value = 2**55 + 7
    identity = helpers.eid(str(value))
    assert isinstance(identity.input, Int64)
    assert helpers.id_of(identity) == value
    assert helpers.id_of(SimpleNamespace(Id=identity)) == value
    assert helpers.eid(identity) is identity


@pytest.mark.parametrize("enum", [Category(), Parameter()])
def test_enum_overload_is_preserved(helpers, enum):
    assert helpers.eid(enum).input is enum


def test_legacy_id_accessor(helpers):
    legacy = ElementId(0)
    del legacy.Value
    legacy.IntegerValue = 125
    assert helpers.id_of(legacy) == 125
    assert helpers.id_of(None) is None


def test_unicode_name_and_hidden_descriptor(helpers):
    assert helpers.name_of(SimpleNamespace(Name="Étage 雪")) == "Étage 雪"
    assert helpers.name_of(SimpleNamespace(hidden_name="隐藏")) == "隐藏"
    assert helpers.name_of(None, "absent") == "absent"
    assert helpers.name_of(object(), "absent") == "absent"


def test_supported_json_values_and_unicode(helpers):
    values = {"id": helpers.eid(2**55 + 7), "point": XYZ(1, 2, 3),
              "integer": Int64(9), "fraction": DotNetFloat(1.5),
              "bool": DotNetBool(False), "name": "café 雪"}
    serialized = helpers.to_json(values, ensure_ascii=False)
    decoded = json.loads(serialized)
    assert decoded == {"id": 2**55 + 7, "point": [1, 2, 3], "integer": 9,
                       "fraction": 1.5, "bool": False, "name": "café 雪"}
    assert "café 雪" in serialized
    buffer = StringIO()
    helpers.json.dump(values, buffer)
    buffer.seek(0)
    assert helpers.json.load(buffer) == decoded
    assert helpers.json.loads(helpers.json.dumps(values)) == decoded


def test_custom_json_default_and_unknown_object(helpers):
    value = object()
    with pytest.raises(TypeError, match="not JSON serializable"):
        helpers.to_json(value)
    assert helpers.to_json(value, default=lambda obj: "custom") == '"custom"'
    # Adapter must not modify the process-wide json module.
    with pytest.raises(TypeError):
        json.dumps(helpers.eid(3))


class IronPythonJson:
    """IronPython 2.7's json.dumps, as far as non-ASCII text goes.

    IronPython's str is unicode, but its stdlib encoder (CPython 2.7's) still
    runs s.decode('utf-8') on any str holding a character in \\x80-\\xff when
    ensure_ascii is on. That decode is where the audited calls failed.
    """
    calls = []

    @classmethod
    def dumps(cls, value, **kwargs):
        cls.calls.append(kwargs.get("ensure_ascii", True))
        if kwargs.get("ensure_ascii", True):
            cls._check(value)
        return json.dumps(value, **kwargs)

    @classmethod
    def _check(cls, value):
        if isinstance(value, str) and re.search("[\x80-\xff]", value):
            value.encode("latin-1", "replace").decode("utf-8")  # raises as IronPython does
        elif isinstance(value, dict):
            for key, item in value.items():
                cls._check(key)
                cls._check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                cls._check(item)


@pytest.fixture
def ironpython_json(monkeypatch):
    IronPythonJson.calls = []
    monkeypatch.setattr(execution_helpers, "json", IronPythonJson)
    return IronPythonJson


def test_ironpython_json_emulation_reproduces_the_audited_failure(ironpython_json):
    with pytest.raises(UnicodeDecodeError, match="can't decode byte 0xb0"):
        ironpython_json.dumps({"angle": "90.00°"})


def test_to_json_accepts_non_ascii_text_under_ironpython_json(helpers, ironpython_json):
    value = {"angle": "90.00°", "rooms": [{"Étage": ("Café", "雪 😀")}], "id": helpers.eid(5)}
    serialized = helpers.to_json(value)
    # Identical to CPython's own ensure_ascii output, escapes and surrogates included.
    assert serialized == json.dumps({"angle": "90.00°", "rooms": [{"Étage": ["Café", "雪 😀"]}], "id": 5})
    assert "\\u00b0" in serialized and serialized.isascii()
    assert ironpython_json.calls == [False]
    assert json.loads(helpers.to_json(value, ensure_ascii=False))["angle"] == "90.00°"
    assert "90.00°" in helpers.to_json(value, ensure_ascii=False)


def test_to_json_decodes_byte_strings_in_keys_and_values(helpers, monkeypatch):
    # Pin the code page so the result does not depend on this machine's ANSI page.
    monkeypatch.setattr(execution_helpers, "_BINARY_ENCODINGS", ("utf-8", "cp1252"))
    value = {b"Winkel \xb0": [b"90\xc2\xb0", (b"\xb0", {"deep": bytearray(b"\x81")})],
             "text": "unchanged"}
    assert json.loads(helpers.to_json(value)) == {
        "Winkel °": ["90°", ["°", {"deep": "\x81"}]], "text": "unchanged"}


def test_to_json_byte_strings_use_the_windows_code_page_before_latin1():
    assert execution_helpers._BINARY_ENCODINGS[:2] == ("utf-8", "mbcs")
    assert execution_helpers._decode_binary(b"\xe2\x82\xac") == "€"
    assert execution_helpers._decode_binary(b"\x81") == "\x81"  # undefined in cp1252


def test_to_json_keeps_order_kwargs_and_unchanged_structures(helpers):
    ordered = OrderedDict([("z", b"1"), ("a", 2)])
    assert helpers.to_json(ordered) == '{"z": "1", "a": 2}'
    assert helpers.to_json(ordered, sort_keys=True, indent=1) == '{\n "a": 2,\n "z": "1"\n}'
    plain = {"a": [1, "b"]}
    assert execution_helpers._text_strings(plain) is plain


def test_to_json_keeps_type_errors_and_circular_checks(helpers):
    with pytest.raises(TypeError, match="object is not JSON serializable"):
        helpers.to_json({"nested": [object()]})
    with pytest.raises(TypeError, match="not JSON serializable"):
        helpers.to_json(object(), default=None)
    assert helpers.to_json(object(), default=lambda obj: b"\xb0") == '"\\u00b0"'
    loop = []
    loop.append(loop)
    with pytest.raises(ValueError, match="Circular reference"):
        helpers.to_json(loop)


def test_injected_json_dump_matches_to_json(helpers, ironpython_json):
    buffer = StringIO()
    helpers.json.dump({"angle": "45°"}, buffer)
    assert buffer.getvalue() == helpers.json.dumps({"angle": "45°"}) == '{"angle": "45\\u00b0"}'


def test_actionable_hints():
    assert "eid(value)" in build_hints("TypeError", "Multiple targets could match: ElementId")[0]
    assert "name_of" in build_hints("AttributeError", "Name")[0]
    assert "id_of" in build_hints("AttributeError", "IntegerValue")[0]


def test_injected_namespace(helpers):
    namespace = helpers.namespace()
    eval(compile("print(to_json({'id': id_of(eid('42'))}))", "test.py", "exec"), namespace)
    assert set(namespace) >= {"System", "json", "eid", "id_of", "name_of", "to_json"}
