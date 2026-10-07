# -*- coding: utf-8 -*-
"""Primitive identity wire contract shared by the connector and MCP directory.

This module deliberately imports no Revit objects and supports IronPython 2.7.
"""
import copy
import math
import uuid
try:
    from urllib.parse import urlsplit
except ImportError:
    from urlparse import urlsplit
try:
    string_types = (basestring,)
    integer_types = (int, long)
except NameError:
    string_types = (str,)
    integer_types = (int,)


class IdentityError(ValueError):
    def __init__(self, code, message):
        ValueError.__init__(self, message)
        self.code = code


def full_uuid(value, field):
    """Accept only canonical, full UUID strings; never prefixes or aliases."""
    try:
        if not isinstance(value, string_types) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise IdentityError("invalid_identity", "%s must be a canonical full UUID" % field)
    return value


def endpoint_url(value):
    if not isinstance(value, string_types):
        raise IdentityError("invalid_metadata", "endpoint must be an HTTP URL")
    parsed = urlsplit(value)
    try:
        valid = (parsed.scheme in ("http", "https") and parsed.hostname
                 and parsed.port and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and parsed.path.rstrip("/") == "/revit_mcp")
    except ValueError:
        valid = False
    if not valid:
        raise IdentityError("invalid_metadata", "endpoint must include host, port and /revit_mcp")
    return value.rstrip("/")


def validate_snapshot(value):
    """Validate then copy only primitive wire fields, excluding arbitrary objects."""
    if not isinstance(value, dict):
        raise IdentityError("invalid_metadata", "metadata must be an object")
    result = {}
    for field in ("instance_id", "runtime_id"):
        result[field] = full_uuid(value.get(field), field)
    pid = value.get("process_id")
    if isinstance(pid, bool) or not isinstance(pid, integer_types) or pid <= 0:
        raise IdentityError("invalid_metadata", "process_id must be a positive integer")
    result["process_id"] = pid
    for field in ("process_started_at", "revit_version"):
        if not isinstance(value.get(field), string_types) or not value[field]:
            raise IdentityError("invalid_metadata", "%s must be a nonempty string" % field)
        result[field] = value[field]
    result["endpoint"] = endpoint_url(value.get("endpoint"))
    known = value.get("documents_known")
    stamp = value.get("snapshot_at")
    if not isinstance(known, bool):
        raise IdentityError("invalid_metadata", "documents_known must be boolean")
    if stamp is not None and (isinstance(stamp, bool) or not isinstance(stamp, (float,) + integer_types)
                              or math.isnan(stamp) or math.isinf(stamp) or stamp < 0):
        raise IdentityError("invalid_metadata", "snapshot_at must be UTC epoch seconds")
    if known and stamp is None:
        raise IdentityError("invalid_metadata", "known documents need a snapshot timestamp")
    result.update(documents_known=known, snapshot_at=stamp, documents=[])
    docs = value.get("documents")
    if not isinstance(docs, list) or (not known and docs):
        raise IdentityError("invalid_metadata", "documents must be a primitive list")
    seen = set()
    for doc in docs:
        if not isinstance(doc, dict):
            raise IdentityError("invalid_metadata", "document must be an object")
        token = full_uuid(doc.get("document_id"), "document_id")
        if token in seen:
            raise IdentityError("invalid_metadata", "duplicate document token")
        seen.add(token)
        if not all(isinstance(doc.get(k), string_types) for k in ("title", "path")):
            raise IdentityError("invalid_metadata", "document title/path must be strings")
        if not isinstance(doc.get("is_active"), bool):
            raise IdentityError("invalid_metadata", "is_active must be boolean")
        family = doc.get("is_family_document", False)
        if not isinstance(family, bool):
            raise IdentityError("invalid_metadata", "is_family_document must be boolean")
        descriptor = {k: doc[k] for k in ("document_id", "title", "path", "is_active")}
        descriptor["is_family_document"] = family
        result["documents"].append(descriptor)
    if sum(d["is_active"] for d in result["documents"]) > 1:
        raise IdentityError("invalid_metadata", "multiple active documents")
    for field in ("revit_build", "engine_version", "connector_version", "snapshot_error"):
        if isinstance(value.get(field), string_types):
            result[field] = value[field]
    return copy.deepcopy(result)
