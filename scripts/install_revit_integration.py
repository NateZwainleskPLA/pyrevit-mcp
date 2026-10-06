"""Install a version-scoped integration dispatcher, preserving local setup.

The existing extension stays enabled. Other Revit years execute its exact
backed-up startup; selected years retain its pre-registration guards and then
load this checkout. No models, pyRevit binaries or add-in manifests are changed.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_file(path, data):
    staging = path.with_suffix(path.suffix + ".integration.tmp")
    staging.write_bytes(data)
    staging.replace(path)


def restore(case):
    manifest = json.loads((case / "installation.json").read_text())
    for item in manifest["changed_files"]:
        path = Path(item["path"])
        if digest(path.read_bytes()) != item["installed_sha256"]:
            raise RuntimeError("Changed since installation; refusing to overwrite: " + str(path))
    for item in manifest["changed_files"]:
        data = (case / item["backup"]).read_bytes()
        if digest(data) != item["original_sha256"]:
            raise RuntimeError("Backup checksum mismatch")
        replace_file(Path(item["path"]), data)
    print("Restored original startup and client configuration; restart Revit/client to load them.")


def install(args):
    source = args.source.resolve()
    startup = args.legacy_extension.resolve() / "startup.py"
    legacy = startup.read_bytes()
    if b"Revit MCP integration dispatcher" in legacy:
        raise RuntimeError("Already installed; restore the previous installation first")
    marker = b"# Initialize the main API"
    if marker not in legacy:
        raise RuntimeError("Cannot separate the existing local pre-registration setup")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source).strip():
        raise RuntimeError("Commit the integration checkout before installing")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    python = source / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError("Missing integration client virtual environment")
    case = args.backup_root.resolve() / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    case.mkdir(parents=True, exist_ok=False)
    (case / "legacy-startup.py").write_bytes(legacy)
    (case / "local-guards.py").write_bytes(legacy.split(marker, 1)[0])
    manifest = {"source": str(source), "integration_sha": sha, "versions": args.versions,
                "backup_directory": str(case), "changed_files": []}
    settings = {"source": str(source), "legacy": str(case / "legacy-startup.py"),
                "guards": str(case / "local-guards.py"), "case": str(case),
                "sha": sha, "versions": args.versions}
    dispatcher = '''# -*- coding: utf-8 -*-
# Revit MCP integration dispatcher. Restore using the installation manifest.
import json, os, sys, traceback
from pyrevit import HOST_APP
_integration_settings = json.loads(%r)
def _integration_exec(path):
    with open(path, "rb") as stream:
        code = stream.read()
    exec(compile(code, path, "exec"), globals())
if str(HOST_APP.version) not in _integration_settings["versions"]:
    _integration_exec(_integration_settings["legacy"])
else:
    _integration_receipt = {"integration_sha": _integration_settings["sha"],
                            "revit_version": str(HOST_APP.version),
                            "source": _integration_settings["source"],
                            "process_id": int(HOST_APP.proc_id)}
    try:
        # Retain the user's existing host-specific Routes setup, not old routes.
        _integration_exec(_integration_settings["guards"])
        sys.path.insert(0, _integration_settings["source"])
        for _name, _module in list(sys.modules.items()):
            if _name == "revit_mcp" or _name.startswith("revit_mcp."):
                _loaded = os.path.abspath(getattr(_module, "__file__", ""))
                if not _loaded.lower().startswith(_integration_settings["source"].lower() + os.sep):
                    raise RuntimeError("Foreign connector module already loaded: " + _name)
        __file__ = os.path.join(_integration_settings["source"], "startup.py")
        _integration_exec(__file__)
        from revit_mcp.target_registry import get_registry
        _integration_receipt["metadata"] = get_registry().snapshot()
        _integration_receipt["loaded_modules"] = dict((name, str(getattr(module, "__file__", "")))
            for name, module in list(sys.modules.items())
            if name == "revit_mcp" or name.startswith("revit_mcp."))
        _integration_receipt["status"] = "loaded"
    except Exception:
        _integration_receipt["status"] = "failed"
        _integration_receipt["error"] = traceback.format_exc()
        raise
    finally:
        _receipt_path = os.path.join(_integration_settings["case"],
            "loaded-%%s.json" %% _integration_receipt["process_id"])
        with open(_receipt_path, "w") as _receipt_stream:
            json.dump(_integration_receipt, _receipt_stream, ensure_ascii=True, indent=2)
''' % json.dumps(settings)
    changes = [(startup, legacy, dispatcher.encode("utf-8"), "legacy-startup.py")]
    if args.codex_config:
        config = args.codex_config.resolve()
        original = config.read_bytes()
        text = original.decode("utf-8")
        client = tomllib.loads(text)["mcp_servers"]["revit-mcp-python"]
        if client.get("env"):
            raise RuntimeError("Existing client environment needs explicit reconciliation")
        pattern = r"(?ms)^\[mcp_servers\.revit-mcp-python\]\r?\n.*?(?=^\[|\Z)"
        match = re.search(pattern, text)
        if not match:
            raise RuntimeError("Existing revit-mcp-python client section not found")
        section = match.group()
        section = re.sub(r"(?m)^command\s*=.*$", lambda _: "command = " + json.dumps(str(python)), section)
        section = re.sub(r"(?m)^args\s*=.*$", lambda _: "args = " + json.dumps([str(source / "main.py")]), section)
        state = case.parent / "target-directory.sqlite3"
        section = section.rstrip() + "\n" + "env = { REVIT_TARGET_STATE = " + json.dumps(str(state)) + " }\n\n"
        updated = (text[:match.start()] + section + text[match.end():]).encode("utf-8")
        tomllib.loads(updated.decode("utf-8"))
        (case / "codex-config.toml").write_bytes(original)
        changes.append((config, original, updated, "codex-config.toml"))
    for path, original, updated, backup in changes:
        manifest["changed_files"].append(dict(path=str(path), backup=backup,
            original_sha256=digest(original), installed_sha256=digest(updated)))
    (case / "installation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    changed = []
    try:
        for path, original, updated, backup in changes:
            replace_file(path, updated)
            changed.append((path, original))
    except BaseException:
        for path, original in reversed(changed):
            replace_file(path, original)
        raise
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--legacy-extension", type=Path)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--versions", nargs="+", default=["2024", "2025", "2026"])
    parser.add_argument("--codex-config", type=Path)
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.restore:
        restore(args.restore.resolve())
    elif not all((args.source, args.legacy_extension, args.backup_root)):
        parser.error("--source, --legacy-extension and --backup-root are required")
    else:
        install(args)


if __name__ == "__main__":
    main()
