"""Provenance tests use fake application metadata; no native Revit is contacted."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

import pytest

from revit_mcp.runtime_diagnostics import collect_loaded_runtime_metadata, hash_loaded_sources


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
        "source_file_sha256_at_capture": None}]
    assert result["source_hashes_captured_at_unix"] is None
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
    assert result["loaded_modules"][0]["file_error_type"] is None
    hashed = hash_loaded_sources(result)
    assert hashed["loaded_modules"][0]["source_file_sha256_at_capture"] is None
    assert hashed["loaded_modules"][0]["file_error_type"] == "FileNotFoundError"


def test_native_wrappers_are_rejected_instead_of_cached():
    with pytest.raises(TypeError):
        collect_loaded_runtime_metadata(application(), {"document": object()})
    with pytest.raises(ValueError):
        collect_loaded_runtime_metadata(application(), [])


def test_file_hash_does_not_claim_to_be_loaded_code_hash(tmp_path):
    source = tmp_path / "module.py"
    source.write_bytes(b"original")
    modules = {"revit_mcp": SimpleNamespace(__file__=str(source), __version__="still-loaded")}
    capture = collect_loaded_runtime_metadata(application(), {}, modules=modules)
    before = hash_loaded_sources(capture)
    source.write_bytes(b"replaced after load")
    after = hash_loaded_sources(capture)
    assert before["loaded_modules"][0]["declared_version"] == after["loaded_modules"][0]["declared_version"]
    assert before["loaded_modules"][0]["source_file_sha256_at_capture"] != after["loaded_modules"][0]["source_file_sha256_at_capture"]
    assert after["loaded_build"] is None
    assert before["captured_at_unix"] == after["captured_at_unix"] == capture["captured_at_unix"]
    assert capture["loaded_modules"][0]["source_file_sha256_at_capture"] is None


def test_api_capture_reads_no_files_even_for_extra_startup_path(tmp_path, monkeypatch):
    import builtins

    def forbidden_read(*args, **kwargs):
        pytest.fail("File I/O during API capture")

    source = str(tmp_path / "cloud-backed-module.py")
    startup = str(tmp_path / "startup.py")
    monkeypatch.setattr(builtins, "open", forbidden_read)
    result = collect_loaded_runtime_metadata(
        application(), {}, modules={"revit_mcp": SimpleNamespace(__file__=source)},
        extra_paths=(startup,))
    assert result["loaded_modules"][0]["loaded_path"] == source
    assert result["extra_sources"] == [{"loaded_path": startup,
                                         "source_file_sha256_at_capture": None,
                                         "file_error_type": None}]
    assert result["source_hashes_captured_at_unix"] is None


def test_background_step_hashes_module_and_entry_point_without_mutating_capture(tmp_path, monkeypatch):
    import builtins

    module = tmp_path / "module.py"
    module.write_bytes(b"loaded module disk bytes")
    startup = tmp_path / "startup.py"
    startup.write_bytes(b"entry point disk bytes")
    capture = collect_loaded_runtime_metadata(
        application(), {"future_field": [1]},
        modules={"revit_mcp": SimpleNamespace(__file__=str(module))},
        extra_paths=(str(startup),))
    real_open = builtins.open
    reading_threads = []

    def record_thread(*args, **kwargs):
        reading_threads.append(threading.get_ident())
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", record_thread)
    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(hash_loaded_sources, capture).result()
    assert len(reading_threads) == 2
    assert all(reader != threading.get_ident() for reader in reading_threads)
    assert result["loaded_modules"][0]["source_file_sha256_at_capture"] == hashlib.sha256(module.read_bytes()).hexdigest()
    assert result["extra_sources"][0]["source_file_sha256_at_capture"] == hashlib.sha256(startup.read_bytes()).hexdigest()
    assert result["source_hashes_captured_at_unix"] >= capture["captured_at_unix"]
    assert result["runtime_snapshot"] == capture["runtime_snapshot"]
    assert capture["source_hashes_captured_at_unix"] is None
    assert capture["extra_sources"][0]["source_file_sha256_at_capture"] is None


def test_background_hash_records_each_failure_and_continues(tmp_path, monkeypatch):
    import builtins

    denied = str(tmp_path / "denied.py")
    missing = str(tmp_path / "missing.py")
    healthy = tmp_path / "startup.py"
    healthy.write_bytes(b"available")
    real_open = builtins.open

    def guarded_open(path, *args, **kwargs):
        if path == denied:
            raise PermissionError("cannot read")
        return real_open(path, *args, **kwargs)

    capture = collect_loaded_runtime_metadata(
        application(), {}, modules={"revit_mcp": SimpleNamespace(__file__=denied)},
        extra_paths=(missing, str(healthy)))
    monkeypatch.setattr(builtins, "open", guarded_open)
    result = hash_loaded_sources(capture)
    assert result["loaded_modules"][0]["file_error_type"] == "PermissionError"
    assert result["extra_sources"][0]["file_error_type"] == "FileNotFoundError"
    assert result["extra_sources"][1]["file_error_type"] is None
    assert result["extra_sources"][1]["source_file_sha256_at_capture"] == hashlib.sha256(b"available").hexdigest()


def test_rehash_failure_clears_previous_digest(tmp_path):
    source = tmp_path / "module.py"
    source.write_bytes(b"original")
    captured = collect_loaded_runtime_metadata(
        application(), {}, modules={"revit_mcp": SimpleNamespace(__file__=str(source))})
    first = hash_loaded_sources(captured)
    source.unlink()
    second = hash_loaded_sources(first)
    assert first["loaded_modules"][0]["source_file_sha256_at_capture"]
    assert second["loaded_modules"][0]["source_file_sha256_at_capture"] is None
    assert second["loaded_modules"][0]["file_error_type"] == "FileNotFoundError"


@pytest.mark.parametrize("invalid", ["startup.py", (object(),), ("",)])
def test_extra_paths_require_explicit_primitive_paths(invalid):
    with pytest.raises(ValueError, match="extra_paths"):
        collect_loaded_runtime_metadata(application(), {}, modules={}, extra_paths=invalid)
