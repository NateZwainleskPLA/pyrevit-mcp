# -*- coding: utf-8 -*-
"""Read-only provenance capture in API context, for later cached inspection.

No routes, subscriptions, identity allocation or model modifications. This is
IronPython 2.7 compatible. The caller supplies the identity owner's snapshot;
workers may serve the returned primitives without accessing Revit objects.
Source file I/O is a separate, optional background step after API capture.
"""
import hashlib
import json
import sys
import time

try:
    _string_types = (basestring,)
except NameError:
    _string_types = (str,)


def _source_record(path):
    return {"loaded_path": path, "source_file_sha256_at_capture": None,
            "file_error_type": None}


def collect_loaded_runtime_metadata(application, runtime_snapshot,
                                    loaded_build=None, pyrevit_version=None,
                                    modules=None, extra_paths=()):
    """Capture loaded versions/paths, preserving the supplied snapshot verbatim.

    Must run in a valid Revit API context. loaded_build is an optional primitive
    build stamp retained at runtime initialization, never a current git lookup.
    extra_paths are explicit paths retained by the host (e.g. startup __file__).
    Does no file I/O. Hash paths later with hash_loaded_sources in a worker;
    those hashes describe disk bytes at that later time, never loaded bytecode.
    """
    if not isinstance(runtime_snapshot, dict):
        raise ValueError("runtime_snapshot must be the identity owner's dictionary")
    if (not isinstance(extra_paths, (list, tuple))
            or any(not isinstance(path, _string_types) or not path.strip()
                   for path in extra_paths)):
        raise ValueError("extra_paths must be a list/tuple of nonempty path strings")
    # JSON round-trip rejects native wrappers rather than leaking them to workers.
    metadata = json.loads(json.dumps({"runtime_snapshot": runtime_snapshot,
                                     "loaded_build": loaded_build,
                                     "pyrevit_version": pyrevit_version}))
    metadata["captured_at_unix"] = time.time()
    metadata["source_hashes_captured_at_unix"] = None
    metadata["python_version"] = sys.version
    metadata["python_platform"] = sys.platform
    metadata["application"] = {}
    metadata["capture_errors"] = []
    for field, attribute in (("version_number", "VersionNumber"),
                             ("version_name", "VersionName"),
                             ("version_build", "VersionBuild")):
        try:
            metadata["application"][field] = getattr(application, attribute)
        except Exception as error:
            metadata["application"][field] = None
            metadata["capture_errors"].append({"field": field,
                                                "error_type": type(error).__name__})
    modules = sys.modules if modules is None else modules
    metadata["loaded_modules"] = []
    for name in sorted(modules):
        if name != "revit_mcp" and not name.startswith("revit_mcp."):
            continue
        module = modules[name]
        if module is None:
            continue
        path = getattr(module, "__file__", None)
        item = _source_record(path)
        item["name"] = name
        item["declared_version"] = getattr(module, "__version__", None)
        metadata["loaded_modules"].append(item)
    metadata["extra_sources"] = [_source_record(path) for path in extra_paths]
    # Guarantee the result is cached primitive data, even for unexpected providers.
    return json.loads(json.dumps(metadata))


def hash_loaded_sources(metadata):
    """Copy primitive capture and hash its paths in a background worker.

    Never pass application/doc/module objects here. Each file's errors remain
    visible; previously collected hashes are replaced, not kept on read failure.
    Input snapshots and API capture time remain unchanged. No Revit API access.
    """
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a captured primitive dictionary")
    hashed = json.loads(json.dumps(metadata))
    for item in hashed["loaded_modules"] + hashed["extra_sources"]:
        item["source_file_sha256_at_capture"] = None
        item["file_error_type"] = None
        if item["loaded_path"]:
            try:
                digest = hashlib.sha256()
                with open(item["loaded_path"], "rb") as source:
                    while True:
                        block = source.read(65536)
                        if not block:
                            break
                        digest.update(block)
                item["source_file_sha256_at_capture"] = digest.hexdigest()
            except Exception as error:
                item["file_error_type"] = type(error).__name__
    hashed["source_hashes_captured_at_unix"] = time.time()
    return hashed
