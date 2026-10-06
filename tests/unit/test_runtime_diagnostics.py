"""Provenance tests use fake application metadata; no native Revit is contacted."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from revit_mcp.runtime_diagnostics import collect_loaded_runtime_metadata


def application():
    return SimpleNamespace(VersionNumber="2025", VersionName="Synthetic Revit",
                           VersionBuild="synthetic-build")


def test_preserves_identity_snapshot_and_captures_loaded_versions(tmp_path):
    source = tmp_path / "loaded_module.py"
    source.write_bytes(b"current bytes on disk")
    loaded = SimpleNamespace(__file__=str(source), __version__="loaded-version")
    snapshot = {"instance_id": "supplied-instance", "runtime_id": "supplied-runtime",
                "documents": [{"document_id": "supplied-doc"}],
                "freshness": {"age_seconds": 7}, "future_field": [1, 2, 3]}
    stamp = {"revision": "stamp-retained-at-initialization"}
    result = collect_loaded_runtime_metadata(application(), snapshot, stamp,
                                            "supplied-pyrevit-version",
                                            {"revit_mcp": loaded, "other": loaded})
    assert result["runtime_snapshot"] == snapshot
    assert result["application"]["version_build"] == "synthetic-build"
    assert result["loaded_build"] == stamp
    assert result["pyrevit_version"] == "supplied-pyrevit-version"
    assert result["loaded_modules"] == [{
        "name": "revit_mcp", "loaded_path": str(source),
        "declared_version": "loaded-version", "file_error_type": None,
        "source_file_sha256_at_capture": hashlib.sha256(source.read_bytes()).hexdigest()}]
    snapshot["documents"].clear()
    stamp["revision"] = "changed"
    assert result["runtime_snapshot"]["documents"]
    assert result["loaded_build"]["revision"] != "changed"
    json.dumps(result)


def test_absent_build_stamp_is_honestly_unknown():
    result = collect_loaded_runtime_metadata(application(), {}, modules={})
    assert result["loaded_build"] is None
    assert result["pyrevit_version"] is None
    assert result["loaded_modules"] == []
    assert result["python_version"]


def test_missing_api_attribute_and_unavailable_source_are_recorded(tmp_path):
    fake = application()
    del fake.VersionBuild
    modules = {"revit_mcp.dialog_policy": SimpleNamespace(__file__=str(tmp_path / "gone")),
               "revit_mcp.empty": None}
    result = collect_loaded_runtime_metadata(fake, {}, modules=modules)
    assert result["application"]["version_build"] is None
    assert result["capture_errors"] == [{"field": "version_build",
                                           "error_type": "AttributeError"}]
    assert result["loaded_modules"][0]["source_file_sha256_at_capture"] is None
    assert result["loaded_modules"][0]["file_error_type"] == "FileNotFoundError"


def test_native_wrappers_are_rejected_instead_of_cached():
    with pytest.raises(TypeError):
        collect_loaded_runtime_metadata(application(), {"document": object()})
    with pytest.raises(ValueError):
        collect_loaded_runtime_metadata(application(), [])


def test_file_hash_does_not_claim_to_be_loaded_code_hash(tmp_path):
    source = tmp_path / "module.py"
    source.write_bytes(b"original")
    modules = {"revit_mcp": SimpleNamespace(__file__=str(source), __version__="still-loaded")}
    before = collect_loaded_runtime_metadata(application(), {}, modules=modules)
    source.write_bytes(b"replaced after load")
    after = collect_loaded_runtime_metadata(application(), {}, modules=modules)
    assert before["loaded_modules"][0]["declared_version"] == after["loaded_modules"][0]["declared_version"]
    assert before["loaded_modules"][0]["source_file_sha256_at_capture"] != after["loaded_modules"][0]["source_file_sha256_at_capture"]
    assert after["loaded_build"] is None
