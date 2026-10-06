"""Filesystem-only diagnostics checks; fake fixture bytes are never opened in Revit."""
import hashlib
import json

import pytest

from tools.diagnostic_case import main, prepare_case, verify_settings


def fixture(tmp_path):
    path = tmp_path / "explicit-fixture.rfa"
    path.write_bytes(b"Synthetic fixture bytes, not a native family")
    return path


def test_prepare_preserves_originals_and_supplied_runtime_schema(tmp_path):
    model = fixture(tmp_path)
    original = model.read_bytes()
    setting = tmp_path / "named.ini"
    setting.write_bytes(b"exact\r\nsettings\r\n")
    absent_setting = tmp_path / "originally-absent.addin"
    metadata = tmp_path / "metadata.json"
    snapshot = {"runtime_snapshot": {"instance_id": "supplied", "future": [1, 2]},
                "loaded_build": {"revision": "supplied"}}
    metadata.write_text(json.dumps(snapshot), encoding="utf-8-sig")
    case = tmp_path / "fresh-case"
    manifest = prepare_case(model, case, metadata, [setting, absent_setting])
    assert model.read_bytes() == original
    assert (case / "fixture" / model.name).read_bytes() == original
    assert manifest["fixture"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["runtime_metadata"] == snapshot
    assert manifest["native_validation"] == "not_run"
    assert manifest["settings_restoration"] == "not_verified"
    assert not absent_setting.exists()
    assert json.loads((case / "case.json").read_text(encoding="utf-8")) == manifest
    result = verify_settings(case)
    assert result["settings_restoration"] == "verified"
    assert result["settings_recorded"] == 2


def test_case_folder_is_never_overwritten(tmp_path):
    model = fixture(tmp_path)
    case = tmp_path / "case"
    prepare_case(model, case)
    (case / "fixture" / model.name).write_bytes(b"diagnostic edits")
    with pytest.raises(FileExistsError):
        prepare_case(model, case)
    assert (case / "fixture" / model.name).read_bytes() == b"diagnostic edits"


@pytest.mark.parametrize("change", ["modified", "missing", "created_absent", "corrupt_backup"])
def test_verification_reports_mismatch_without_restoring_anything(tmp_path, change):
    setting = tmp_path / "named.ini"
    setting.write_bytes(b"baseline")
    absent = tmp_path / "new.addin"
    case = tmp_path / "case"
    prepare_case(fixture(tmp_path), case, settings=[setting, absent])
    if change == "modified":
        setting.write_bytes(b"changed")
    elif change == "missing":
        setting.unlink()
    elif change == "created_absent":
        absent.write_bytes(b"new configuration")
    else:
        (case / "settings" / "0" / setting.name).write_bytes(b"corrupt backup")
    before = setting.read_bytes() if setting.exists() else None
    result = verify_settings(case)
    assert result["settings_restoration"] == "mismatch"
    assert (setting.read_bytes() if setting.exists() else None) == before
    if change == "created_absent":
        assert absent.read_bytes() == b"new configuration"


def test_empty_settings_does_not_claim_restoration(tmp_path):
    case = tmp_path / "case"
    prepare_case(fixture(tmp_path), case)
    assert verify_settings(case)["settings_restoration"] == "no_settings_recorded"


@pytest.mark.parametrize("invalid", ["wrong_extension", "directory_setting", "duplicate_setting", "invalid_metadata"])
def test_invalid_input_is_rejected_before_case_creation(tmp_path, invalid):
    model = fixture(tmp_path)
    case = tmp_path / "case"
    kwargs = {}
    if invalid == "wrong_extension":
        model = tmp_path / "wrong.txt"
        model.write_bytes(b"not a fixture")
    elif invalid == "directory_setting":
        kwargs["settings"] = [tmp_path]
    elif invalid == "duplicate_setting":
        kwargs["settings"] = [tmp_path / "absent.ini"] * 2
    else:
        metadata = tmp_path / "array.json"
        metadata.write_text("[]", encoding="utf-8")
        kwargs["runtime_metadata"] = metadata
    with pytest.raises(ValueError):
        prepare_case(model, case, **kwargs)
    assert not case.exists()


def test_cli_reports_mismatched_settings_as_nonzero(tmp_path, capsys):
    model = fixture(tmp_path)
    setting = tmp_path / "baseline.ini"
    setting.write_bytes(b"original")
    case = tmp_path / "case"
    assert main(["prepare", "--fixture", str(model), "--case-dir", str(case),
                 "--record-setting", str(setting)]) == 0
    assert json.loads(capsys.readouterr().out)["native_validation"] == "not_run"
    setting.write_bytes(b"changed")
    assert main(["verify-settings", "--case-dir", str(case)]) == 1
    assert json.loads(capsys.readouterr().out)["settings_restoration"] == "mismatch"
    assert setting.read_bytes() == b"changed"


def test_source_change_during_copy_cannot_produce_a_valid_case(tmp_path, monkeypatch):
    import tools.diagnostic_case as module

    model = fixture(tmp_path)
    case = tmp_path / "case"
    real_copy = module.shutil.copy2

    def copy_then_change_source(source, destination):
        real_copy(source, destination)
        source.write_bytes(b"external edit during copy")

    monkeypatch.setattr(module.shutil, "copy2", copy_then_change_source)
    with pytest.raises(RuntimeError, match="Source changed"):
        prepare_case(model, case)
    assert case.is_dir()  # incomplete evidence is retained, never deleted
    assert not (case / "case.json").exists()
