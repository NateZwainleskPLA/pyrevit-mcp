# -*- coding: utf-8 -*-
"""Tests for _wait_for_revit_ready with mocked async calls."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch
from tools.launch_tools import _wait_for_revit_ready
from tools.revit_transport import RevitTransportResult, request_revit
from tools.utils import compatibility_response


def received_response(body, status=200):
    return compatibility_response(RevitTransportResult(
        method="GET", url="http://fixture.invalid/health/", status_code=status,
        body=body, json_received=True))


@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_immediate_ready(mock_sleep):
    """Revit responds on first poll."""
    mock_get = AsyncMock(return_value=received_response({"status": "alive", "api_name": "revit_mcp"}))
    ready, response = await _wait_for_revit_ready(mock_get, ctx=None, timeout=30)

    assert ready is True
    assert response["status"] == "alive"
    mock_get.assert_awaited_once_with("/health/", ctx=None, timeout=5.0)
    mock_sleep.assert_not_called()


@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_ready_after_retries(mock_sleep):
    """Revit fails twice then responds."""
    mock_get = AsyncMock(
        side_effect=[
            ConnectionError("refused"),
            ConnectionError("refused"),
            received_response({"status": "alive", "api_name": "revit_mcp"}),
        ]
    )
    ready, response = await _wait_for_revit_ready(
        mock_get, ctx=None, timeout=60, poll_interval=1
    )

    assert ready is True
    assert response == {"status": "alive", "api_name": "revit_mcp"}
    assert mock_sleep.call_count == 2


@patch("time.time", return_value=0)
@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_connector_marked_503_is_not_liveness(mock_sleep, mock_time):
    """The legacy /status/ no-document allowance does not apply to /health/."""
    mock_sleep.side_effect = lambda _: setattr(mock_time, "return_value", 2)
    body = {"status": "unhealthy", "api_name": "revit_mcp"}
    mock_get = AsyncMock(return_value=received_response(body, 503))
    ready, response = await _wait_for_revit_ready(mock_get, ctx=None, timeout=1)

    assert ready is False
    assert response is None


@pytest.mark.parametrize("failure", [
    ConnectionError("refused"),
    "Error: Request timed out waiting for Revit API context",
])
@patch("time.time")
@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_timeout(mock_sleep, mock_time, failure):
    """Revit never responds — returns False after timeout."""
    # Simulate time progressing past the timeout
    # _wait_for_revit_ready does `import time` locally, so we patch the
    # global time module.  Calls: start=time(), while: time()-start<timeout
    mock_time.side_effect = [0, 0, 5, 5, 11, 11]
    mock_get = AsyncMock(side_effect=[failure, failure])

    ready, response = await _wait_for_revit_ready(
        mock_get, ctx=None, timeout=10, poll_interval=5
    )

    assert ready is False
    assert response is None


@pytest.mark.parametrize("status,body,expected", [
    (200, {"status": "alive", "api_name": "revit_mcp"}, True),
    (200, {"status": "active", "api_name": "revit_mcp"}, False),
    (503, {"status": "unhealthy", "api_name": "revit_mcp"}, False),
    (404, {"status": "alive", "api_name": "revit_mcp"}, False),
    (409, {"status": "alive", "api_name": "revit_mcp"}, False),
    (500, {"status": "alive", "api_name": "revit_mcp"}, False),
    (503, {"status": "unhealthy", "api_name": "foreign_service"}, False),
    (503, {"status": "unhealthy"}, False),
    (500, {"exception": {"source": "pyRevit", "message": "dispatch failed"}}, False),
    (408, {"exception": {"source": "pyRevit", "message": "handler failed"}}, False),
    (200, {"exception": {"source": "pyRevit", "message": "handler failed"}}, False),
    (200, ["not a status object"], False),
])
@patch("time.time", return_value=0)
@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_waiter_checks_received_http_status_and_json(mock_sleep, mock_time, status, body, expected):
    mock_sleep.side_effect = lambda _: setattr(mock_time, "return_value", 2)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def revit_get(endpoint, ctx=None, timeout=5.0):
            result = await request_revit("GET", "http://fixture.invalid" + endpoint,
                                         timeout=timeout, client=client)
            return compatibility_response(result)

        ready, response = await _wait_for_revit_ready(revit_get, None, timeout=1)
    assert ready == expected
    assert (response is not None) == expected
    assert len(requests) == 1
    assert requests[0].url.path == "/health/"  # No endpoint fallback.


@pytest.mark.parametrize("response", [
    "Error: 503 - Service Unavailable",
    {"status": "alive", "api_name": "revit_mcp"},
])
@patch("time.time", return_value=0)
@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_waiter_requires_http_metadata(mock_sleep, mock_time, response):
    mock_sleep.side_effect = lambda _: setattr(mock_time, "return_value", 2)
    ready, body = await _wait_for_revit_ready(AsyncMock(return_value=response), None, timeout=1)
    assert not ready and body is None


@patch("time.time", return_value=0)
@patch("tools.launch_tools.anyio.sleep", new_callable=AsyncMock)
async def test_non_json_5xx_does_not_establish_readiness(mock_sleep, mock_time):
    mock_sleep.side_effect = lambda _: setattr(mock_time, "return_value", 2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(502, text="<html>bad gateway</html>"))) as client:
        result = await request_revit("GET", "http://fixture.invalid/health/", client=client)
    ready, body = await _wait_for_revit_ready(
        AsyncMock(return_value=compatibility_response(result)), None, timeout=1)
    assert not ready and body is None
