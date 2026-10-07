import json
from io import StringIO
from types import SimpleNamespace

import pytest

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


def test_actionable_hints():
    assert "eid(value)" in build_hints("TypeError", "Multiple targets could match: ElementId")[0]
    assert "name_of" in build_hints("AttributeError", "Name")[0]
    assert "id_of" in build_hints("AttributeError", "IntegerValue")[0]


def test_injected_namespace(helpers):
    namespace = helpers.namespace()
    eval(compile("print(to_json({'id': id_of(eid('42'))}))", "test.py", "exec"), namespace)
    assert set(namespace) >= {"System", "json", "eid", "id_of", "name_of", "to_json"}
