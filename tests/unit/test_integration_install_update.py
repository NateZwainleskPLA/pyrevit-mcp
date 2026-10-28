"""Exercise installation, updates and rollback without a native host or real config."""
import argparse
import ast
import json
import re
from pathlib import Path

import pytest

from scripts import install_revit_integration as installer


@pytest.fixture
def installed(tmp_path, monkeypatch):
    case = tmp_path / "installs" / "previous"
    case.mkdir(parents=True)
    source = tmp_path / "source"
    source.mkdir()
    startup = tmp_path / "extension" / "startup.py"
    startup.parent.mkdir()
    for name in ("legacy-startup.py", "local-guards.py"):
        (case / name).write_text("# original local setup\n")
    settings = {"source": str(source), "sha": "old-commit", "case": str(case),
                "versions": ["2024", "2025", "2026"],
                "legacy": str(case / "legacy-startup.py"), "guards": str(case / "local-guards.py")}
    original = ("# Revit MCP integration dispatcher\n"
                "_integration_settings = json.loads(%r)\n" % json.dumps(settings)).encode()
    startup.write_bytes(original)
    manifest = {"source": str(source), "integration_sha": "old-commit",
                "versions": settings["versions"], "backup_directory": str(case),
                "changed_files": [{"path": str(startup), "backup": "legacy-startup.py",
                                   "installed_sha256": installer.digest(original)}]}
    (case / "installation.json").write_text(json.dumps(manifest))
    def git(command, **kwargs):
        assert Path(kwargs["cwd"]) == source
        return b"" if command[1] == "status" else "new-commit\n"
    monkeypatch.setattr(installer.subprocess, "check_output", git)
    return case, startup, original, settings


def test_update_preserves_local_dependencies_and_rollback(installed):
    case, startup, original, before = installed
    updated_case = installer.update_installation(case)
    manifest = json.loads((updated_case / "installation.json").read_text())
    match = re.search(r"json\.loads\((.*)\)", startup.read_text())
    after = json.loads(ast.literal_eval(match.group(1)))
    assert after == dict(before, sha="new-commit", case=str(updated_case))
    assert manifest["previous_installation"] == str(case)
    assert manifest["changed_files"][0]["installed_sha256"] == installer.digest(startup.read_bytes())
    assert (updated_case / "previous-dispatcher.py").read_bytes() == original
    installer.restore(updated_case)
    assert startup.read_bytes() == original


def test_modified_dispatcher_is_not_overwritten(installed):
    case, startup, original, _ = installed
    edited = original + b"# user change\n"
    startup.write_bytes(edited)
    with pytest.raises(RuntimeError, match="changed since installation"):
        installer.update_installation(case)
    assert startup.read_bytes() == edited
    assert list(case.parent.iterdir()) == [case]


def test_update_rejects_dirty_source_before_changing_installation(installed, monkeypatch):
    case, startup, original, _ = installed
    monkeypatch.setattr(installer.subprocess, "check_output", lambda *args, **kwargs: b" M startup.py\n")
    with pytest.raises(RuntimeError, match="Commit the integration checkout"):
        installer.update_installation(case)
    assert startup.read_bytes() == original
    assert list(case.parent.iterdir()) == [case]


def test_rollback_refuses_edits_after_update(installed):
    case, startup, _, _ = installed
    updated_case = installer.update_installation(case)
    startup.write_bytes(startup.read_bytes() + b"# later user edit\n")
    with pytest.raises(RuntimeError, match="Changed since installation"):
        installer.restore(updated_case)


def write_claude(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / ".venv" / "Scripts").mkdir(parents=True)
    (source / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    extension = tmp_path / "extension"
    extension.mkdir()
    (extension / "startup.py").write_text("# local guards\n# Initialize the main API\napi = None\n")
    entry = {"type": "stdio", "command": "old/python.exe", "args": ["old/main.py"],
             "env": {"REVIT_TARGET_STATE": "old/target-directory.sqlite3"}}
    claude = tmp_path / ".claude.json"
    write_claude(claude, {"numStartups": 1, "mcpServers": {
        "revit-mcp-python": entry, "other": {"type": "stdio", "command": "other.exe"}}})
    monkeypatch.setattr(installer.subprocess, "check_output",
                        lambda command, **kwargs: b"" if command[1] == "status" else "new-commit\n")
    args = argparse.Namespace(source=source, legacy_extension=extension, backup_root=tmp_path / "installs",
                              versions=["2025"], codex_config=None, claude_config=claude)
    return args, claude, entry


def test_install_points_claude_entry_and_restores_only_that_entry(fresh):
    args, claude, entry = fresh
    startup = args.legacy_extension / "startup.py"
    legacy = startup.read_bytes()
    installer.install(args)
    data = json.loads(claude.read_text(encoding="utf-8"))
    source = args.source.resolve()
    assert data["mcpServers"]["revit-mcp-python"] == {
        "type": "stdio", "command": str(source / ".venv" / "Scripts" / "python.exe"),
        "args": [str(source / "main.py")],
        "env": {"REVIT_TARGET_STATE": str(args.backup_root.resolve() / "target-directory.sqlite3")}}
    assert data["mcpServers"]["other"] == {"type": "stdio", "command": "other.exe"}
    # Claude Code keeps rewriting the rest of the file; rollback must survive it.
    data["numStartups"] = 2
    write_claude(claude, data)
    (case,) = args.backup_root.iterdir()
    installer.restore(case)
    restored = json.loads(claude.read_text(encoding="utf-8"))
    assert restored["mcpServers"]["revit-mcp-python"] == entry
    assert restored["numStartups"] == 2
    assert startup.read_bytes() == legacy


def test_install_refuses_unreconciled_claude_environment(fresh):
    args, claude, entry = fresh
    write_claude(claude, {"mcpServers": {"revit-mcp-python": dict(entry, env={"REVIT_PORT": "48885"})}})
    before = claude.read_bytes()
    startup = (args.legacy_extension / "startup.py").read_bytes()
    with pytest.raises(RuntimeError, match="explicit reconciliation"):
        installer.install(args)
    assert claude.read_bytes() == before
    assert (args.legacy_extension / "startup.py").read_bytes() == startup
    assert not args.backup_root.exists()


def test_rollback_refuses_claude_entry_edited_after_install(fresh):
    args, claude, _ = fresh
    installer.install(args)
    startup = args.legacy_extension / "startup.py"
    dispatcher = startup.read_bytes()
    data = json.loads(claude.read_text(encoding="utf-8"))
    data["mcpServers"]["revit-mcp-python"]["args"] = ["elsewhere/main.py"]
    write_claude(claude, data)
    (case,) = args.backup_root.iterdir()
    with pytest.raises(RuntimeError, match="Claude Code entry changed since installation"):
        installer.restore(case)
    assert startup.read_bytes() == dispatcher
