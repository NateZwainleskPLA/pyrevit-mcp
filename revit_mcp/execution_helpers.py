# -*- coding: UTF-8 -*-
"""Reusable IronPython/Revit helpers, independent of Routes registration."""
import json
import re
from collections import OrderedDict
from .execution_output import text_type

_BINARY_TYPES = tuple(t for t in (bytes, bytearray) if t is not text_type)
# Windows ANSI code page where it exists, then cp1252; latin-1 never fails.
_BINARY_ENCODINGS = ("utf-8", "mbcs", "cp1252")
_NON_ASCII = re.compile(r"[^\x00-\x7f]")


def _decode_binary(value):
    for encoding in _BINARY_ENCODINGS:
        try:
            return value.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    return value.decode("latin-1")


def _escape_char(match):
    code = ord(match.group(0))
    if code > 0xFFFF:  # CPython 3; IronPython strings already hold surrogates.
        code -= 0x10000
        return u"\\u{0:04x}\\u{1:04x}".format(0xD800 | (code >> 10), 0xDC00 | (code & 0x3FF))
    return u"\\u{0:04x}".format(code)


def _text_strings(value, active=None):
    """value with byte strings decoded to text, in keys and values at any depth.

    Containers without byte strings are returned unchanged. A container
    already being walked is left for json's own circular-reference check.
    """
    if isinstance(value, _BINARY_TYPES):
        return _decode_binary(value)
    if not isinstance(value, (dict, list, tuple)):
        return value
    active = set() if active is None else active
    if id(value) in active:
        return value
    active.add(id(value))
    try:
        if isinstance(value, dict):
            pairs = [(_text_strings(k, active), _text_strings(v, active))
                     for k, v in value.items()]
            changed = any(new[0] is not k or new[1] is not v
                          for new, (k, v) in zip(pairs, value.items()))
            return OrderedDict(pairs) if changed else value
        items = [_text_strings(item, active) for item in value]
        changed = any(new is not old for new, old in zip(items, value))
        return items if changed else value
    finally:
        active.discard(id(value))


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
        """json.dumps that accepts non-ASCII text and byte strings anywhere in value.

        IronPython 2.7's json treats every str as UTF-8 bytes when ensure_ascii
        is on, so text such as u"90°" (from AsValueString) raises
        UnicodeDecodeError. Encode with ensure_ascii off, which never decodes,
        and escape non-ASCII afterwards: the result is what CPython's json
        returns. Byte strings are decoded as UTF-8, then the Windows code page,
        then latin-1, so no data is dropped.
        """
        default = kwargs.pop("default", None) or self.json_default
        ensure_ascii = kwargs.pop("ensure_ascii", True)
        kwargs["default"] = lambda obj: _text_strings(default(obj))
        text = json.dumps(_text_strings(value), ensure_ascii=False, **kwargs)
        return _NON_ASCII.sub(_escape_char, text) if ensure_ascii else text

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
        fp.write(self.helpers.to_json(value, **kwargs))

    def loads(self, value, **kwargs):
        return json.loads(value, **kwargs)

    def load(self, fp, **kwargs):
        return json.load(fp, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


def build_hints(error_type, message):
    if "NoneType" in message and "ActiveView" in message:
        return ["UI view access requires allow_ui_change=True and an eligible supplied UIDocument; inactive-document work has no uidoc."]
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
