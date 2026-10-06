# -*- coding: UTF-8 -*-
"""Reusable IronPython/Revit helpers, independent of Routes registration."""
import json
from .execution_output import text_type


class RevitHelpers(object):
    """Bind helpers to Revit/.NET namespaces without changing global modules."""
    def __init__(self, db, system):
        self.db = db
        self.system = system
        self.json = JsonAdapter(self)

    def eid(self, value):
        if isinstance(value, self.db.ElementId):
            return value
        if isinstance(value, (self.db.BuiltInCategory, self.db.BuiltInParameter)):
            return self.db.ElementId(value)
        # Int64 avoids ambiguous enum/integer overloads and preserves 64-bit IDs.
        return self.db.ElementId(self.system.Int64(int(value)))

    def id_of(self, element_or_id):
        if element_or_id is None:
            return None
        value = (element_or_id if isinstance(element_or_id, self.db.ElementId)
                 else element_or_id.Id)
        try:
            return int(value.Value)
        except AttributeError:
            return int(value.IntegerValue)

    def name_of(self, element, default=u""):
        if element is None:
            return default
        try:
            value = element.Name
        except AttributeError:
            try:
                value = self.db.Element.Name.__get__(element)
            except Exception:
                return default
        except Exception:
            return default
        return default if value is None else text_type(value)

    def json_default(self, value):
        if isinstance(value, self.db.ElementId):
            return self.id_of(value)
        if isinstance(value, self.db.XYZ):
            return [float(value.X), float(value.Y), float(value.Z)]
        if isinstance(value, self.system.Boolean):
            return bool(value)
        if isinstance(value, (self.system.Int64, self.system.Int32, self.system.Int16,
                              self.system.Byte, self.system.SByte, self.system.UInt16,
                              self.system.UInt32, self.system.UInt64)):
            return int(value)
        if isinstance(value, (self.system.Double, self.system.Single, self.system.Decimal)):
            return float(value)
        # Unknown objects are programming errors; do not silently stringify them.
        raise TypeError("{0} is not JSON serializable".format(type(value).__name__))

    def to_json(self, value, **kwargs):
        kwargs.setdefault("default", self.json_default)
        return json.dumps(value, **kwargs)

    def namespace(self):
        return {"System": self.system, "json": self.json, "eid": self.eid,
                "id_of": self.id_of, "name_of": self.name_of, "to_json": self.to_json}


class JsonAdapter(object):
    """Local JSON adapter; importing json in a script still imports stdlib json."""
    def __init__(self, helpers):
        self.helpers = helpers

    def dumps(self, value, **kwargs):
        return self.helpers.to_json(value, **kwargs)

    def dump(self, value, fp, **kwargs):
        kwargs.setdefault("default", self.helpers.json_default)
        return json.dump(value, fp, **kwargs)

    def loads(self, value, **kwargs):
        return json.loads(value, **kwargs)

    def load(self, fp, **kwargs):
        return json.load(fp, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


def build_hints(error_type, message):
    if "Multiple targets could match" in message and "ElementId" in message:
        return ["Use eid(value) to select the explicit Int64 ElementId overload."]
    if "not JSON serializable" in message:
        return ["Use id_of(element), to_json(value), or the injected json.dumps for supported Revit/.NET values."]
    if error_type == "AttributeError" and "Name" in message:
        return ["Use name_of(element) for IronPython's hidden Element.Name descriptor."]
    if error_type == "AttributeError" and "IntegerValue" in message:
        return ["Use id_of(element_or_id) for Value/IntegerValue compatibility."]
    if error_type == "InvalidOperationException":
        return ["Use execution.transaction(doc, name) for owned model-edit scopes, or transaction_mode='managed'."]
    if error_type == "NullReferenceException" or "NoneType" in message:
        return ["Check that element/parameter lookups returned an object before accessing properties."]
    return []
