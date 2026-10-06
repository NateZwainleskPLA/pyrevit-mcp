"""Offline evidence/copy preparation and settings comparison; never runs Revit."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_record(source, destination):
    before = _sha256(source)
    shutil.copy2(source, destination)
    copied = _sha256(destination)
    if before != copied or before != _sha256(source):
        raise RuntimeError(f"Source changed during evidence copy: {source}")
    return {"original_path": str(source), "backup_path": str(destination),
            "originally_exists": True, "sha256": copied}


def prepare_case(fixture, case_dir, runtime_metadata=None, settings=()):
    """Copy an explicitly supplied fixture and named evidence into a fresh folder.

    No original files are written, no Revit process/configuration is changed,
    and no supplied metadata is interpreted as a target binding or handshake.
    On error the incomplete folder is retained as evidence; no recursive deletion.
    """
    fixture = Path(fixture).resolve(strict=True)
    case_dir = Path(case_dir).resolve()
    if not fixture.is_file() or fixture.suffix.lower() not in (".rvt", ".rfa"):
        raise ValueError("Supply an explicit .rvt or .rfa disposable fixture")
    setting_paths = [Path(path).resolve() for path in settings]
    if len(set(setting_paths)) != len(setting_paths):
        raise ValueError("Duplicate settings paths")
    if any(path.exists() and not path.is_file() for path in setting_paths):
        raise ValueError("Settings paths must name individual files")
    supplied_metadata = None
    metadata_path = None
    if runtime_metadata is not None:
        metadata_path = Path(runtime_metadata).resolve(strict=True)
        with metadata_path.open(encoding="utf-8-sig") as source:
            supplied_metadata = json.load(source)
        if not isinstance(supplied_metadata, dict):
            raise ValueError("Runtime metadata must be a JSON object")
    # Exclusive creation prevents overwriting an earlier case, model, or evidence.
    case_dir.mkdir(parents=True, exist_ok=False)
    (case_dir / "fixture").mkdir()
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                "native_validation": "not_run", "settings": [],
                "fixture": _copy_record(fixture, case_dir / "fixture" / fixture.name),
                "runtime_metadata": supplied_metadata,
                "runtime_metadata_source": str(metadata_path) if metadata_path else None,
                "settings_restoration": "not_verified"}
    for index, setting in enumerate(setting_paths):
        if setting.exists():
            destination = case_dir / "settings" / str(index) / setting.name
            destination.parent.mkdir(parents=True)
            record = _copy_record(setting, destination)
        else:
            record = {"original_path": str(setting), "backup_path": None,
                      "originally_exists": False, "sha256": None}
        manifest["settings"].append(record)
    with (case_dir / "case.json").open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2, ensure_ascii=False)
        output.write("\n")
    return manifest


def verify_settings(case_dir):
    """Compare named settings to baseline hashes; report only, never restore."""
    with (Path(case_dir) / "case.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    records = []
    for setting in manifest["settings"]:
        original = Path(setting["original_path"])
        backup = Path(setting["backup_path"]) if setting["backup_path"] else None
        backup_valid = (backup.is_file() and _sha256(backup) == setting["sha256"]
                        if backup else not setting["originally_exists"])
        if not setting["originally_exists"]:
            restored = not original.exists()
        else:
            restored = original.is_file() and _sha256(original) == setting["sha256"]
        records.append({"original_path": str(original), "restored": restored,
                        "backup_valid": backup_valid})
    return {"compared_at_utc": datetime.now(timezone.utc).isoformat(),
            "settings_recorded": len(records), "settings": records,
            "settings_restoration": ("no_settings_recorded" if not records else
                                     "verified" if all(r["restored"] and r["backup_valid"]
                                                       for r in records) else "mismatch")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Prepare a fresh offline case")
    prepare.add_argument("--fixture", required=True)
    prepare.add_argument("--case-dir", required=True)
    prepare.add_argument("--runtime-metadata")
    prepare.add_argument("--record-setting", action="append", default=[])
    verify = commands.add_parser("verify-settings", help="Read-only settings comparison")
    verify.add_argument("--case-dir", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare_case(args.fixture, args.case_dir, args.runtime_metadata,
                              args.record_setting)
    else:
        result = verify_settings(args.case_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("settings_restoration") == "mismatch" else 0


if __name__ == "__main__":
    raise SystemExit(main())
