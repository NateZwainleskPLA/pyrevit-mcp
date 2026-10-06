import inspect
import json
import os
import socket
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from revit_mcp.identity import IdentityError
from revit_mcp.target_runtime import register_metadata_routes, initialize_identity
from tools.target_directory import TargetDirectory
from tools.target_discovery import TargetDiscovery, configured_candidates, metadata_handshake
from tools.target_tools import register_target_tools
from tests.unit.test_target_identity import Document, metadata, descriptor, registry


class CapturedAPI:
    def __init__(self):
        self.handlers = {}

    def route(self, path, methods):
        def capture(handler):
            self.handlers[path] = handler
            return handler
        return capture


def install_routes_mock(monkeypatch):
    module = SimpleNamespace(routes=SimpleNamespace(
        make_response=lambda data, status=200: dict(data=data, status=status)))
    monkeypatch.setitem(sys.modules, "pyrevit", module)
    return module


def test_metadata_route_is_noncontext_and_refresh_requires_full_target(monkeypatch):
    install_routes_mock(monkeypatch)
    reg = registry()
    api = CapturedAPI()
    register_metadata_routes(api, reg)
    cached = api.handlers["/metadata/"]
    refresh = api.handlers["/metadata/refresh/"]
    assert not inspect.signature(cached).parameters
    assert "uiapp" in inspect.signature(refresh).parameters
    initial = cached()["data"]
    assert initial["documents_known"] is False
    assert initial["snapshot_at"] is None
    class ForbiddenApp:
        def __getattribute__(self, name):
            pytest.fail("invalid-target refresh dereferenced UIApplication")
    result = refresh(ForbiddenApp(), initial["instance_id"], "wrong")
    assert result["status"] == 409
    assert result["data"]["error_code"] == "invalid_identity"
    a, b = Document(), Document()
    uiapp = SimpleNamespace(Application=SimpleNamespace(Documents=[a, b]),
                            ActiveUIDocument=SimpleNamespace(Document=b))
    result = refresh(uiapp, initial["instance_id"], initial["runtime_id"])
    assert result["status"] == 200
    assert [d["is_active"] for d in result["data"]["documents"]] == [False, True]
    reg.expire()
    assert refresh(ForbiddenApp(), initial["instance_id"], initial["runtime_id"])["status"] == 409


def test_refresh_failure_preserves_snapshot_and_returns_503(monkeypatch):
    install_routes_mock(monkeypatch)
    reg = registry(clock=lambda: 100)
    snap = reg.refresh_documents([Document()])
    api = CapturedAPI()
    register_metadata_routes(api, reg)
    result = api.handlers["/metadata/refresh/"](None, snap["instance_id"], snap["runtime_id"])
    assert result["status"] == 503
    assert result["data"]["documents"] == snap["documents"]
    assert result["data"]["snapshot_at"] == 100
    assert result["data"]["snapshot_error"]


async def test_discovery_is_explicit_and_rejects_stale_registration_and_non_metadata():
    directory = TargetDirectory()
    snapshots = {
        "http://localhost:48884/revit_mcp": metadata(),
        "http://localhost:48885/revit_mcp": metadata(process_id=101, endpoint="http://localhost:48885/revit_mcp"),
        "http://localhost:48886/revit_mcp": {"status": "active"},
    }
    candidates = [dict(endpoint=endpoint) for endpoint in snapshots]
    candidates[1]["registration"] = {"process_id": 999}
    candidates.append(dict(endpoint=candidates[1]["endpoint"]))  # must not bypass stale evidence
    checked = []
    async def handshake(endpoint):
        return snapshots[endpoint]
    discovery = TargetDiscovery(directory, candidates, handshake, lambda data: checked.append(data["process_id"]))
    result = await discovery.discover()
    assert len(result["targets"]) == 1
    assert {item["error_code"] for item in result["errors"]} == {"stale_registration", "invalid_identity"}
    assert len(directory.targets()) == 1
    assert checked == [100, 101]
    assert not hasattr(discovery, "selected_target")


async def test_discovery_rejects_pid_port_ownership_failure():
    directory = TargetDirectory()
    snap = metadata()
    async def handshake(endpoint):
        return snap
    def local_validator(data):
        raise IdentityError("stale_registration", "PID no longer owns listener")
    result = await TargetDiscovery(directory, [dict(endpoint=snap["endpoint"])], handshake, local_validator).discover()
    assert result["targets"] == []
    assert result["errors"][0]["error_code"] == "stale_registration"
    assert directory.targets() == []


async def test_multiple_targets_discovery_and_injected_tools_do_not_select(mock_mcp):
    directory = TargetDirectory()
    snapshots = {s["endpoint"]: s for s in [metadata(documents=[descriptor()]),
                 metadata(process_id=101, endpoint="http://localhost:48885/revit_mcp", revit_version="2026") ]}
    async def handshake(endpoint):
        return snapshots[endpoint]
    discovery = TargetDiscovery(directory, [dict(endpoint=e) for e in snapshots], handshake, None)
    register_target_tools(mock_mcp, directory, discovery)
    assert set(mock_mcp.tools) == {"list_revit_targets", "get_revit_target_metadata"}
    result = await mock_mcp.tools["list_revit_targets"](ctx=None)
    assert len(result["targets"]) == 2
    for item in reversed(result["targets"]):
        actual = await mock_mcp.tools["get_revit_target_metadata"](item["target"], ctx=None)
        assert actual["instance_id"] == item["instance_id"]
        assert actual["runtime_id"] == item["runtime_id"]


@pytest.mark.parametrize("status,body", [(503, {"status": "active"}), (200, {"status": "active"}), (200, "not JSON"), (302, {})])
async def test_http_handshake_does_not_accept_any_response(monkeypatch, status, body):
    class Client:
        def __init__(self, **kwargs):
            assert not kwargs["follow_redirects"]
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            request = httpx.Request("GET", url)
            return httpx.Response(status, request=request, json=body) if not isinstance(body, str) else httpx.Response(status, request=request, text=body)
    monkeypatch.setattr("tools.target_discovery.httpx.AsyncClient", Client)
    with pytest.raises((httpx.HTTPError, IdentityError, ValueError)):
        await metadata_handshake("http://localhost:48884/revit_mcp")


def test_json_candidate_loading_prefers_native_evidence_and_bounded_scan(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIT_MCP_REGISTRATION_DIR", str(tmp_path))
    monkeypatch.setenv("REVIT_PORT_SCAN_START", "48884")
    monkeypatch.setenv("REVIT_PORT_SCAN_COUNT", "2")
    monkeypatch.setenv("REVIT_HOST", "127.0.0.1")
    snap = metadata()
    (tmp_path / "100.json").write_text(json.dumps(snap), encoding="utf-8")
    (tmp_path / "bad.json").write_text("invalid", encoding="utf-8")
    (tmp_path / "ignored.pickle").write_bytes(b"never unpickle")
    result = configured_candidates()
    assert result[0]["registration"]["process_id"] == 100
    assert result[0]["source"] == "native_registration_json"
    assert len(result) == 3
    monkeypatch.setenv("REVIT_PORT_SCAN_COUNT", "257")
    with pytest.raises(ValueError, match="1..256"):
        configured_candidates()


def test_directory_partial_state_does_not_reset_allocator(tmp_path):
    path = tmp_path / "directory.sqlite"
    directory = TargetDirectory(path)
    directory.observe(metadata())
    directory._db.execute("DELETE FROM directory_state WHERE key='namespace'")
    directory.close()
    with pytest.raises(IdentityError, match="partial directory"):
        TargetDirectory(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows ownership adapter")
def test_windows_ownership_of_own_disposable_listener():
    from tools.windows_target_evidence import _process_start, validate_windows_ownership
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        snap = metadata(process_id=os.getpid(), process_started_at=_process_start(os.getpid()).isoformat(),
                        endpoint="http://127.0.0.1:%s/revit_mcp" % listener.getsockname()[1])
        validate_windows_ownership(snap)
        with pytest.raises(IdentityError, match="different process start"):
            validate_windows_ownership(dict(snap, process_started_at="2000-01-01T00:00:00Z"))
        snap["endpoint"] = "http://127.0.0.1:1/revit_mcp"
        with pytest.raises(IdentityError, match="does not own"):
            validate_windows_ownership(snap)


class Event:
    def __init__(self):
        self.handlers = []
    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self
    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self


class Generic:
    def __class_getitem__(cls, item):
        return lambda callback=None: callback if callback is not None else {}


def test_startup_uses_native_registration_and_removes_owned_callbacks_on_reload(monkeypatch, tmp_path):
    import revit_mcp.target_runtime as runtime
    import revit_mcp.target_registry as registry_module
    monkeypatch.setattr(registry_module, "_registry", None)
    slots = {}
    domain = SimpleNamespace(GetData=lambda key: slots.get(key), SetData=lambda key, value: slots.__setitem__(key, value))
    app = SimpleNamespace(Documents=[Document()], VersionBuild="25.0", DocumentOpened=Event(), DocumentClosed=Event())
    uiapp = SimpleNamespace(Application=app, ActiveUIDocument=None, Idling=Event(), ViewActivated=Event())
    pyrevit = install_routes_mock(monkeypatch)
    pyrevit.HOST_APP = SimpleNamespace(uiapp=uiapp, app=app, version="2025", has_api_context=True)
    pyrevit.framework = SimpleNamespace(EventHandler=Generic)
    pyrevit.DB = SimpleNamespace(Events=SimpleNamespace(DocumentOpenedEventArgs=object, DocumentClosedEventArgs=object))
    pyrevit.UI = SimpleNamespace(Events=SimpleNamespace(IdlingEventArgs=object, ViewActivatedEventArgs=object))
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(AppDomain=SimpleNamespace(CurrentDomain=domain), String=str, Object=object))
    monkeypatch.setitem(sys.modules, "System.Collections.Generic", SimpleNamespace(Dictionary=Generic))
    start = SimpleNamespace(ToUniversalTime=lambda: SimpleNamespace(ToString=lambda fmt: "2026-10-05T12:00:00.000000Z"))
    process = SimpleNamespace(Id=100, StartTime=start)
    monkeypatch.setitem(sys.modules, "System.Diagnostics", SimpleNamespace(Process=SimpleNamespace(GetCurrentProcess=lambda: process)))
    monkeypatch.setitem(sys.modules, "pyrevit.routes.server", SimpleNamespace(serverinfo=SimpleNamespace(register=lambda:
        SimpleNamespace(process_id=100, server_host="localhost", server_port=48884))))
    published = []
    monkeypatch.setattr(runtime, "publish_registration", lambda snap, path: published.append(snap))
    monkeypatch.setenv("REVIT_MCP_REGISTRATION_DIR", str(tmp_path))
    first = initialize_identity(CapturedAPI())
    first_snap = first.snapshot()
    assert first_snap["documents_known"]
    second = initialize_identity(CapturedAPI())
    assert second.snapshot()["instance_id"] == first_snap["instance_id"]
    assert second.snapshot()["runtime_id"] != first_snap["runtime_id"]
    assert second.snapshot()["documents"][0]["document_id"] != first_snap["documents"][0]["document_id"]
    assert not first.snapshot()["runtime_available"]
    assert all(len(event.handlers) == 1 for event in (app.DocumentOpened, app.DocumentClosed, uiapp.Idling, uiapp.ViewActivated))
    assert len(published) == 2
    assert registry_module.get_registry() is second
    app.Documents = []
    app.DocumentClosed.handlers[0](app, None)
    assert second.snapshot()["documents"] == []
