"""Real HTTP metadata parsing/discovery/waiter composition; no native host."""
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from tests.unit.test_target_identity import metadata
from tools.launch_tools import _wait_for_revit_ready
from tools.target_directory import TargetDirectory
from tools.target_discovery import TargetDiscovery


@pytest.mark.parametrize("status,payload,ready", [
    (200, "valid_metadata", True),
    (200, {"api_name": "revit_mcp", "status": "alive"}, False),
    (200, {"api_name": "foreign", "status": "alive"}, False),
    (200, {"exception": {"message": "handler failed"}}, False),
    (200, [], False), (204, None, False),
    (202, {"api_name": "revit_mcp", "status": "alive"}, False),
    (404, {"api_name": "revit_mcp", "status": "alive"}, False),
    (408, {"exception": {"message": "handler failed"}}, False),
    (500, {"api_name": "revit_mcp", "status": "alive"}, False),
    (503, {"api_name": "revit_mcp", "runtime_available": False,
           "error_code": "runtime_unavailable", "error": "identity unavailable"}, False),
    (502, "<html>proxy error</html>", False), (200, "malformed JSON", False),
])
async def test_modern_launch_requires_valid_200_metadata_not_liveness(monkeypatch, status, payload, ready):
    endpoint = "http://127.0.0.1:49001/revit_mcp"
    snapshot = metadata(process_id=777, revit_version="2025", endpoint=endpoint)
    payload = snapshot if payload == "valid_metadata" else payload
    clock, calls = [0.0], []
    async def sleep(seconds):
        clock[0] += seconds
    monkeypatch.setattr("tools.launch_tools.anyio.sleep", sleep)
    real_client = httpx.AsyncClient
    def reply(request):
        calls.append(request.url.path)
        if isinstance(payload, str):
            return httpx.Response(status, text=payload)
        if payload is None:
            return httpx.Response(status, content=b"")
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs))
    directory = TargetDirectory()
    try:
        discovery = TargetDiscovery(directory, candidates=lambda: [{"endpoint": endpoint}], local_validator=lambda data: None)
        process = SimpleNamespace(pid=777, poll=Mock(return_value=None), returncode=None)
        actual_ready, result = await _wait_for_revit_ready(discovery, process, snapshot["process_started_at"],
            None, 1, "2025", clock=lambda: clock[0])
        assert actual_ready is ready
        assert calls and set(calls) == {"/revit_mcp/metadata/"}
        if ready:
            assert result["instance_id"] == snapshot["instance_id"]
            assert result["runtime_id"] == snapshot["runtime_id"]
            assert directory.resolve(result["target"])["process_id"] == 777
            assert len(calls) == 2  # Initial discovery and final revalidation.
        else:
            assert "target" not in result and directory.targets() == []
    finally:
        directory.close()
