"""Exercise installation updates and rollback without a native host or config."""
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
