"""Composed legacy liveness/transport checks; no native readiness proof."""
import time

import httpx
import pytest

from tools.launch_tools import _wait_for_revit_ready
from tools.revit_transport import request_revit
from tools.utils import compatibility_response


@pytest.mark.parametrize("http_status, payload, ready", [
    (200, {"api_name": "revit_mcp", "status": "alive"}, True),
    (200, {"api_name": "revit_mcp", "status": "alive", "success": False}, False),
    (200, {"api_name": "revit_mcp", "status": "alive",
           "exception": {"message": "handler failed"}}, False),
    (200, {"api_name": "foreign", "status": "alive"}, False),
    (200, {"api_name": "revit_mcp", "status": "active"}, False),
    (200, {"status": "alive"}, False),
    (200, {"exception": {"message": "handler failed"}}, False),
    (200, [], False),
    (204, None, False),
    (202, {"api_name": "revit_mcp", "status": "alive"}, False),
    (400, {"api_name": "foreign", "status": "alive"}, False),
    (404, {"api_name": "revit_mcp", "status": "alive"}, False),
    (408, {"exception": {"message": "handler failed"}}, False),
    (500, {"api_name": "revit_mcp", "status": "alive"}, False),
    (503, {"api_name": "revit_mcp", "status": "alive"}, False),
    (503, {"api_name": "revit_mcp", "status": "unhealthy"}, False),
    (502, "<html>proxy error</html>", False),
    (200, "malformed JSON", False),
])
async def test_health_requires_received_200_and_intended_payload(
    monkeypatch, http_status, payload, ready,
):
    """Exercise the real request parser, compatibility wrapper, and poller."""
    clock = [0]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr("tools.launch_tools.anyio.sleep", sleep)
    calls = []

    def reply(request):
        calls.append(request.url.path)
        if isinstance(payload, str):
            return httpx.Response(http_status, text=payload)
        if payload is None:
            return httpx.Response(http_status, content=b"")
        return httpx.Response(http_status, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        async def revit_get(path, ctx=None, **kwargs):
            result = await request_revit(
                "GET", "http://localhost/revit_mcp" + path, client=client, **kwargs,
            )
            return compatibility_response(result)

        actual_ready, response = await _wait_for_revit_ready(
            revit_get, ctx=None, timeout=1, poll_interval=1,
        )
    assert actual_ready is ready
    assert calls == ["/revit_mcp/health/"]
    if ready:
        assert response == payload
    else:
        assert response is None
