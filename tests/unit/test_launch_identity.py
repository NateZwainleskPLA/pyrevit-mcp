import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from tools.launch_tools import register_launch_tools
from tools.target_directory import TargetDirectory
from tests.unit.test_target_identity import metadata


async def test_launch_retains_popen_identity_and_returns_its_own_handle(monkeypatch, mock_mcp):
    directory = TargetDirectory()
    owned = directory.observe(metadata(process_id=777, revit_version="2025", endpoint="http://localhost:49001/revit_mcp"))
    unrelated = directory.observe(metadata(process_id=888, revit_version="2025", endpoint="http://localhost:49002/revit_mcp"))
    discovery = SimpleNamespace(directory=directory, discover=AsyncMock(return_value={"targets": [unrelated, owned]}),
                                revalidate=AsyncMock())
    process = SimpleNamespace(pid=777, poll=Mock(return_value=None), returncode=None)
    popen = Mock(return_value=process)
    monkeypatch.setattr("tools.launch_tools.subprocess.Popen", popen)
    monkeypatch.setattr("tools.launch_tools._find_revit_installations", lambda: [{"year": "2025", "path": "C:/Revit.exe"}])
    monkeypatch.setattr("tools.windows_target_evidence.process_started_at", lambda pid: owned["process_started_at"])
    register_launch_tools(mock_mcp, discovery=discovery)
    result = json.loads(await mock_mcp.tools["launch_revit"](ctx=None, version="2025"))
    assert result["revit_ready"] and result["target"] == owned["target"]
    assert result["process_id"] == process.pid
    assert result["actual_target"] == {key: owned[key] for key in ("instance_id", "runtime_id")}
    popen.assert_called_once_with(["C:/Revit.exe"])
    assert process.poll.called
    directory.close()


async def test_lan_only_child_remains_unverified_with_documented_loopback_limit(monkeypatch, mock_mcp):
    from tools.launch_tools import _wait_for_revit_ready
    directory = TargetDirectory()
    owned = directory.observe(metadata(process_id=777, revit_version="2025", endpoint="http://192.0.2.10:49001/revit_mcp"))
    discovery = SimpleNamespace(directory=directory, discover=AsyncMock(return_value={"targets": [owned]}),
                                revalidate=AsyncMock())
    process = SimpleNamespace(pid=777, poll=Mock(return_value=None), returncode=None)
    monkeypatch.setattr("tools.launch_tools.subprocess.Popen", Mock(return_value=process))
    monkeypatch.setattr("tools.launch_tools._find_revit_installations", lambda: [{"year": "2025", "path": "C:/Revit.exe"}])
    monkeypatch.setattr("tools.windows_target_evidence.process_started_at", lambda pid: owned["process_started_at"])
    now = [0.0]
    async def sleep(seconds):
        now[0] += seconds
    async def bounded_wait(*args):
        return await _wait_for_revit_ready(*args, clock=lambda: now[0])
    monkeypatch.setattr("tools.launch_tools.anyio.sleep", sleep)
    monkeypatch.setattr("tools.launch_tools._wait_for_revit_ready", bounded_wait)
    register_launch_tools(mock_mcp, discovery=discovery)
    result = json.loads(await mock_mcp.tools["launch_revit"](ctx=None, version="2025", timeout=2))
    assert result["status"] == "launched_unverified" and not result["revit_ready"]
    assert "target" not in result and "actual_target" not in result
    assert "loopback" in result["message"] and "LAN/non-loopback" in result["message"]
    assert result["verification"]["error_code"] == "launch_verification_timeout"
    assert now[0] == 2
    discovery.revalidate.assert_not_awaited()
    directory.close()
