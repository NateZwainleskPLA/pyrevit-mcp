"""Readiness binds the actual child process, not a configured endpoint."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tools.launch_tools import _wait_for_revit_ready
from tools.target_directory import TargetDirectory
from tests.unit.test_target_identity import metadata


@pytest.fixture
def launch_wait(monkeypatch):
    now = [0.0]
    async def sleep(seconds):
        now[0] += seconds
    monkeypatch.setattr("tools.launch_tools.anyio.sleep", sleep)
    directory = TargetDirectory()
    own = directory.observe(metadata(process_id=777, revit_version="2025",
                                     endpoint="http://localhost:49001/revit_mcp"))
    other = directory.observe(metadata(process_id=888, revit_version="2026",
                                       endpoint="http://localhost:49002/revit_mcp"))
    process = SimpleNamespace(pid=777, poll=Mock(return_value=None), returncode=None)
    discovery = SimpleNamespace(directory=directory, discover=AsyncMock(), revalidate=AsyncMock())
    async def wait(timeout=3):
        return await _wait_for_revit_ready(discovery, process, own["process_started_at"],
                                           None, timeout, "2025", clock=lambda: now[0])
    yield discovery, process, own, other, wait
    directory.close()


async def test_immediate_ready_returns_own_handle(launch_wait):
    discovery, process, own, other, wait = launch_wait
    discovery.discover.return_value = {"targets": [other, own]}
    ready, response = await wait()
    assert ready and response["target"] == own["target"]
    assert response["process_id"] == process.pid
    discovery.revalidate.assert_awaited_once_with(own["target"])


async def test_waits_through_unrelated_endpoint_until_own_registration(launch_wait):
    discovery, process, own, other, wait = launch_wait
    discovery.discover.side_effect = [{"targets": [other]}, {"targets": [other]}, {"targets": [own]}]
    ready, response = await wait()
    assert ready and response["target"] == own["target"]
    assert discovery.discover.await_count == 3


@pytest.mark.parametrize("value", ["Error: 503 - Service Unavailable", {"status": "active"}, {"targets": []}])
async def test_generic_http_response_is_not_readiness(launch_wait, value):
    discovery, process, own, other, wait = launch_wait
    discovery.discover.return_value = value
    ready, response = await wait()
    assert not ready
    assert response["error_code"] == "launch_verification_timeout"


@pytest.mark.parametrize("field,value", [("process_started_at", "old PID lifetime"), ("revit_version", "2026"),
                                          ("endpoint", "http://remote.host:49001/revit_mcp"),
                                          ("documents_known", False), ("runtime_available", False)])
async def test_pid_reuse_version_remote_host_or_uninitialized_runtime_never_match(launch_wait, field, value):
    discovery, process, own, other, wait = launch_wait
    candidate = dict(own, **{field: value})
    discovery.discover.return_value = {"targets": [candidate]}
    assert not (await wait())[0]


async def test_process_exit_stops_wait_without_accepting_old_registration(launch_wait):
    discovery, process, own, other, wait = launch_wait
    process.poll.return_value = 9
    process.returncode = 9
    discovery.discover.return_value = {"targets": [own]}
    ready, response = await wait()
    assert not ready and response["error_code"] == "launched_process_exited"
    discovery.discover.assert_not_awaited()


async def test_generation_changes_during_final_handshake_never_match(launch_wait):
    discovery, process, own, other, wait = launch_wait
    discovery.discover.return_value = {"targets": [own]}
    discovery.revalidate.side_effect = ValueError("runtime expired")
    ready, response = await wait()
    assert not ready and "runtime expired" in response["verification_error"]
