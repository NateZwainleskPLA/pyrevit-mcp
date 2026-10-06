# -*- coding: utf-8 -*-
"""Read-only provenance capture in API context, for later cached inspection.

No routes, subscriptions, identity allocation or model modifications. This is
IronPython 2.7 compatible. The caller supplies the identity owner's snapshot;
workers may serve the returned primitives without accessing Revit objects.
"""
import hashlib
import json
import sys
import time


def collect_loaded_runtime_metadata(application, runtime_snapshot,
                                    loaded_build=None, pyrevit_version=None,
                                    modules=None):
    """Capture loaded versions/paths, preserving the supplied snapshot verbatim.

    Must run in a valid Revit API context. loaded_build is an optional primitive
    build stamp retained at runtime initialization, never a current git lookup.
    File hashes describe files on disk now and cannot attest to loaded bytecode.
    """
    if not isinstance(runtime_snapshot, dict):
        raise ValueError("runtime_snapshot must be the identity owner's dictionary")
    # JSON round-trip rejects native wrappers rather than leaking them to workers.
    metadata = json.loads(json.dumps({"runtime_snapshot": runtime_snapshot,
                                     "loaded_build": loaded_build,
                                     "pyrevit_version": pyrevit_version}))
    metadata["captured_at_unix"] = time.time()
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
        item = {"name": name, "loaded_path": path,
                "declared_version": getattr(module, "__version__", None),
                "source_file_sha256_at_capture": None, "file_error_type": None}
        if path:
            try:
                digest = hashlib.sha256()
                with open(path, "rb") as source:
                    while True:
                        block = source.read(65536)
                        if not block:
                            break
                        digest.update(block)
                item["source_file_sha256_at_capture"] = digest.hexdigest()
            except Exception as error:
                item["file_error_type"] = type(error).__name__
        metadata["loaded_modules"].append(item)
    # Guarantee the result is cached primitive data, even for unexpected providers.
    return json.loads(json.dumps(metadata))
