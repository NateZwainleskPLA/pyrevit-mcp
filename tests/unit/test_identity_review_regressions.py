"""PR #5 review regressions. Controlled host doubles, no native Revit calls."""
import inspect
import importlib.util
import json
import os
import sys
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from pathlib import Path

import pytest

from revit_mcp.identity import IdentityError, validate_snapshot
import revit_mcp.target_runtime as runtime
from tools.target_directory import TargetDirectory
from tools.target_discovery import TargetDiscovery, configured_candidates
from tests.unit.test_target_identity import Document, descriptor, metadata, registry, uid
from tests.unit.test_target_discovery import CapturedAPI, Event, Generic, install_routes_mock


@pytest.fixture
def native_host(monkeypatch, tmp_path):
    import revit_mcp.target_registry as registry_module
    monkeypatch.setattr(registry_module, "_registry", None)
    slots, format_calls = {}, []
    domain = SimpleNamespace(GetData=lambda k: slots.get(k), SetData=lambda k, v: slots.__setitem__(k, v))
    app = SimpleNamespace(Documents=[Document()], VersionBuild="25.0", DocumentOpened=Event(), DocumentClosed=Event())
    uiapp = SimpleNamespace(Application=app, ActiveUIDocument=None, Idling=Event(), ViewActivated=Event())
    pyrevit = install_routes_mock(monkeypatch)
    pyrevit.HOST_APP = SimpleNamespace(uiapp=uiapp, app=app, version="2025", has_api_context=True)
    pyrevit.framework = SimpleNamespace(EventHandler=Generic)
    pyrevit.DB = SimpleNamespace(Events=SimpleNamespace(DocumentOpenedEventArgs=object, DocumentClosedEventArgs=object))
    pyrevit.UI = SimpleNamespace(Events=SimpleNamespace(IdlingEventArgs=object, ViewActivatedEventArgs=object))
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(AppDomain=SimpleNamespace(CurrentDomain=domain), String=str, Object=object))
    monkeypatch.setitem(sys.modules, "System.Collections.Generic", SimpleNamespace(Dictionary=Generic))
    invariant = object()
    monkeypatch.setitem(sys.modules, "System.Globalization", SimpleNamespace(CultureInfo=SimpleNamespace(InvariantCulture=invariant)))
    def format_start(fmt, culture=None):
        format_calls.append((fmt, culture))
        return "2026-10-05T12:00:00.000000Z"
    start = SimpleNamespace(ToUniversalTime=lambda: SimpleNamespace(ToString=format_start))
    process = SimpleNamespace(Id=100, StartTime=start)
    monkeypatch.setitem(sys.modules, "System.Diagnostics", SimpleNamespace(Process=SimpleNamespace(GetCurrentProcess=lambda: process)))
    registration = SimpleNamespace(process_id=100, server_host="", server_port=48884)
    monkeypatch.setitem(sys.modules, "pyrevit.routes.server", SimpleNamespace(serverinfo=SimpleNamespace(register=lambda: registration)))
    monkeypatch.delenv("REVIT_MCP_ADVERTISED_HOST", raising=False)
    monkeypatch.setenv("REVIT_MCP_REGISTRATION_DIR", str(tmp_path))
    monkeypatch.setattr(runtime, "publish_registration", lambda snap, path: None)
    return SimpleNamespace(slots=slots, registration=registration, app=app, uiapp=uiapp,
                           format_calls=format_calls, invariant=invariant, domain=domain)


@pytest.mark.parametrize("bind", ["", "0.0.0.0", "::"])
def test_default_and_wildcard_binds_advertise_discoverable_loopback(native_host, bind):
    native_host.registration.server_host = bind
    reg = runtime.initialize_identity(CapturedAPI())
    assert reg.snapshot()["endpoint"] == "http://127.0.0.1:48884/revit_mcp"


def test_explicit_advertised_host_override_is_preserved(native_host, monkeypatch):
    monkeypatch.setenv("REVIT_MCP_ADVERTISED_HOST", "::1")
    reg = runtime.initialize_identity(CapturedAPI())
    assert reg.snapshot()["endpoint"] == "http://[::1]:48884/revit_mcp"


def test_native_process_start_uses_invariant_culture(native_host):
    runtime.initialize_identity(CapturedAPI())
    assert native_host.format_calls == [("yyyy-MM-ddTHH:mm:ss.ffffffZ", native_host.invariant)]


def test_old_expire_failure_does_not_skip_exact_delegate_detachment(native_host):
    first = runtime.initialize_identity(CapturedAPI())
    state = native_host.slots[runtime.CALLBACK_SLOT]
    callbacks = [state[key] for key in ("idling", "view", "opened", "closed")]
    def broken_expire():
        raise RuntimeError("old engine unavailable")
    state["expire"] = broken_expire
    second = runtime.initialize_identity(CapturedAPI())
    for event, callback in zip((native_host.uiapp.Idling, native_host.uiapp.ViewActivated,
                                native_host.app.DocumentOpened, native_host.app.DocumentClosed), callbacks):
        assert len(event.handlers) == 1
        assert callback not in event.handlers
    assert native_host.slots[runtime.CALLBACK_SLOT] is not state
    assert not first.snapshot()["runtime_available"]
    assert second.snapshot()["runtime_available"]


def test_detachment_failure_retains_disabled_ownership_and_prevents_replacement(native_host):
    reg = runtime.initialize_identity(CapturedAPI())
    state = native_host.slots[runtime.CALLBACK_SLOT]
    class CannotDetach(Event):
        def __isub__(self, callback):
            raise RuntimeError("cannot detach")
    blocked = CannotDetach()
    blocked.handlers = native_host.uiapp.Idling.handlers[:]
    native_host.uiapp.Idling = blocked
    with pytest.raises(RuntimeError, match="detach"):
        runtime.initialize_identity(CapturedAPI())
    assert native_host.slots[runtime.CALLBACK_SLOT] is state
    assert state["enabled"] is False
    assert blocked.handlers == [state["idling"]]
    assert not native_host.uiapp.ViewActivated.handlers
    assert not native_host.app.DocumentOpened.handlers
    assert not native_host.app.DocumentClosed.handlers
    assert not reg.snapshot()["runtime_available"]
    # The still-attached callback is disabled and must not read an API object.
    state["uiapp"].Application = None
    blocked.handlers[0](None, None)
    assert "snapshot_error" not in reg.snapshot()


def test_partial_attachment_with_failed_detach_retains_disabled_exact_delegate(native_host):
    class PartialFailure(Event):
        def __iadd__(self, callback):
            self.handlers.append(callback)
            raise RuntimeError("attach failed after subscription")
        def __isub__(self, callback):
            raise RuntimeError("detach failed")
    partial = PartialFailure()
    native_host.app.DocumentOpened = partial
    with pytest.raises(RuntimeError, match="attach failed"):
        runtime.initialize_identity(CapturedAPI())
    state = native_host.slots[runtime.CALLBACK_SLOT]
    assert state["enabled"] is False
    assert partial.handlers == [state["opened"]]
    assert not native_host.uiapp.Idling.handlers
    assert not native_host.uiapp.ViewActivated.handlers
    with pytest.raises(RuntimeError, match="detach incomplete"):
        runtime.initialize_identity(CapturedAPI())
    assert partial.handlers == [state["opened"]]


def test_links_never_receive_or_resolve_tokens_and_family_is_classified():
    reg = registry()
    host, link, family = Document("Host"), Document("Link"), Document("Family")
    link.IsLinked = True
    family.IsFamilyDocument = True
    snapshot = reg.refresh_documents([host, link, family], host)
    assert [doc["title"] for doc in snapshot["documents"]] == ["Host", "Family"]
    assert [doc["is_family_document"] for doc in snapshot["documents"]] == [False, True]
    normalized = validate_snapshot(snapshot)
    assert normalized["documents"] == snapshot["documents"]
    family_token = snapshot["documents"][1]["document_id"]
    assert reg.resolve_document(snapshot["instance_id"], snapshot["runtime_id"], family_token,
                                [host, link, family]) is family
    # A previously routable wrapper that becomes a link must fail fresh resolution.
    token = snapshot["documents"][0]["document_id"]
    host.IsLinked = True
    with pytest.raises(IdentityError, match="not open"):
        reg.resolve_document(snapshot["instance_id"], snapshot["runtime_id"], token, [host, link, family])


async def test_family_classification_is_copied_to_directory_without_live_access():
    directory = TargetDirectory()
    snapshot = metadata(documents=[descriptor(is_family_document=True)])
    result = directory.observe(snapshot)
    assert result["documents"][0]["is_family_document"] is True
    assert validate_snapshot(metadata(documents=[descriptor()]))["documents"][0]["is_family_document"] is False
    with pytest.raises(IdentityError, match="is_family_document"):
        validate_snapshot(metadata(documents=[descriptor(is_family_document="true")]))


@pytest.mark.parametrize("reverse", [False, True])
async def test_same_endpoint_stale_record_cannot_veto_matching_live_record(monkeypatch, tmp_path, reverse):
    endpoint = "http://127.0.0.1:48884/revit_mcp"
    live = metadata(process_id=900, endpoint=endpoint)
    stale = metadata(process_id=100, endpoint=endpoint)
    names = ["100.json", "900.json"]
    if reverse:
        names.reverse()
    (tmp_path / names[0]).write_text(json.dumps(stale))
    (tmp_path / names[1]).write_text(json.dumps(live))
    monkeypatch.setenv("REVIT_MCP_REGISTRATION_DIR", str(tmp_path))
    monkeypatch.setenv("REVIT_HOST", "127.0.0.1")
    monkeypatch.setenv("REVIT_PORT_SCAN_COUNT", "1")
    async def handshake(endpoint):
        return live
    result = await TargetDiscovery(TargetDirectory(), configured_candidates, handshake, None).discover()
    assert len(result["targets"]) == 1
    assert result["targets"][0]["process_id"] == 900


def test_candidate_cap_prefers_newest_record_not_pid_filename(monkeypatch, tmp_path):
    for index in range(256):
        path = tmp_path / ("%s.json" % (1000 + index))
        path.write_text(json.dumps(metadata(process_id=1000 + index)))
        os.utime(path, (100, 100))
    newest = tmp_path / "9999.json"
    newest.write_text(json.dumps(metadata(process_id=9999)))
    os.utime(newest, (200, 200))
    monkeypatch.setenv("REVIT_MCP_REGISTRATION_DIR", str(tmp_path))
    records = [candidate["registration"] for candidate in configured_candidates() if "registration" in candidate]
    assert len(records) == 256
    assert records[0]["process_id"] == 9999


def test_rejected_late_runtime_observation_preserves_live_verification():
    directory = TargetDirectory()
    instance = uid()
    old = metadata(instance_id=instance, snapshot_at=100)
    current = metadata(instance_id=instance, snapshot_at=101)
    directory.observe(old)
    live = directory.observe(current)["target"]
    with pytest.raises(IdentityError, match="retired runtime"):
        directory.observe(old)
    assert directory.resolve(live)["runtime_id"] == current["runtime_id"]


def test_process_identity_conflict_preserves_existing_verification():
    directory = TargetDirectory()
    original = metadata()
    target = directory.observe(original)["target"]
    with pytest.raises(IdentityError, match="different process lifetime"):
        directory.observe(dict(original, process_started_at="later start"))
    assert directory.resolve(target)["process_started_at"] == original["process_started_at"]


def test_revived_document_rejection_does_not_retire_other_endpoint_owner():
    directory = TargetDirectory()
    token = descriptor()
    original = metadata(documents=[token])
    target = directory.observe(original)["target"]
    closed = dict(original, documents=[], snapshot_at=101)
    directory.observe(closed)
    # Move the exact runtime; another process can now own its previous endpoint.
    moved = dict(closed, endpoint="http://localhost:48885/revit_mcp")
    directory.observe(moved)
    replacement = metadata(process_id=200)
    other = directory.observe(replacement)["target"]
    with pytest.raises(IdentityError, match="closed document token"):
        directory.observe(dict(original, snapshot_at=102))
    assert directory.resolve(other)["instance_id"] == replacement["instance_id"]
    assert directory.resolve(target)["endpoint"] == moved["endpoint"]


def test_failed_sql_write_does_not_unverify_or_retire_live_target():
    directory = TargetDirectory()
    snapshot = metadata(documents=[descriptor()])
    live = directory.observe(snapshot)["target"]
    directory._db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON targets BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="disk failure"):
        directory.observe(metadata())
    assert directory.resolve(live)["instance_id"] == snapshot["instance_id"]
    assert len(directory.targets()) == 1


@pytest.mark.parametrize("partial", [False, True])
def test_legacy_initialization_failure_returns_primitive_metadata_and_preserves_routes(native_host, monkeypatch, partial):
    api = CapturedAPI()
    installed, saved_handlers = [], []
    if partial:
        normal_register = runtime.register_metadata_routes
        def fail_after_metadata(api, reg):
            installed.append(reg)
            normal_register(api, reg)
            saved_handlers.append(api.handlers["/metadata/"])
            raise RuntimeError("failure after metadata installation")
        monkeypatch.setattr(runtime, "register_metadata_routes", fail_after_metadata)
    else:
        native_host.registration.process_id = 999  # early ownership failure
    assert runtime.initialize_legacy_identity(api) is None
    # Independent legacy status registration still works.
    from revit_mcp.status import register_status_routes
    register_status_routes(api)
    assert api.handlers["/status/"](Document())["status"] == 200
    for path in ("/metadata/", "/metadata/refresh/"):
        handler = api.handlers[path]
        assert not inspect.signature(handler).parameters
        response = handler()
        assert response["status"] == 503
        assert response["data"]["runtime_available"] is False
        assert response["data"]["error_code"] == "runtime_unavailable"
        assert not set(response["data"]).intersection(("instance_id", "runtime_id", "documents", "document_id"))
        with pytest.raises(IdentityError):
            validate_snapshot(response["data"])
    from revit_mcp.target_registry import get_registry
    with pytest.raises(IdentityError, match="not initialized"):
        get_registry()
    if partial:
        assert not installed[0].snapshot()["runtime_available"]
        assert saved_handlers[0]()["data"]["runtime_available"] is False
        assert not any(event.handlers for event in (native_host.uiapp.Idling, native_host.uiapp.ViewActivated,
                                                    native_host.app.DocumentOpened, native_host.app.DocumentClosed))


def test_strict_initialization_still_raises_without_legacy_metadata(native_host):
    native_host.registration.process_id = 999
    api = CapturedAPI()
    with pytest.raises(RuntimeError, match="does not belong"):
        runtime.initialize_identity(api)
    assert not api.handlers


@pytest.mark.parametrize("failure", [None, "early", "partial"])
def test_targeted_startup_requires_strict_identity_without_legacy_fallback(native_host, monkeypatch, failure):
    api = CapturedAPI()
    sys.modules["pyrevit"].routes.API = lambda name: api
    def forbidden_legacy_initializer(api):
        pytest.fail("Targeted startup called the legacy degraded initializer")
    monkeypatch.setattr(runtime, "initialize_legacy_identity", forbidden_legacy_initializer)
    if failure == "early":
        native_host.registration.process_id = 999
    elif failure == "partial":
        register = runtime.register_metadata_routes
        def broken_register(api, registry):
            register(api, registry)
            raise RuntimeError("partial metadata registration")
        monkeypatch.setattr(runtime, "register_metadata_routes", broken_register)
    source_dir = Path(__file__).resolve().parents[2]
    # Load the real status registrar; other independent route modules are inert
    # registration doubles, never native model handlers.
    spec = importlib.util.spec_from_file_location("revit_mcp.status", source_dir / "revit_mcp/status.py")
    status = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(status)
    monkeypatch.setitem(sys.modules, "revit_mcp.status", status)
    calls = []
    for name, registrar in {
        "model_info": "register_model_info_routes", "views": "register_views_routes",
        "placement": "register_placement_routes", "colors": "register_color_routes",
        "code_execution": "register_code_execution_routes", "document": "register_document_routes",
    }.items():
        monkeypatch.setitem(sys.modules, "revit_mcp." + name, SimpleNamespace(**{
            registrar: lambda api, name=name: calls.append(name)}))
    spec = importlib.util.spec_from_file_location("_identity_review_startup", source_dir / "startup.py")
    startup = importlib.util.module_from_spec(spec)
    if failure:
        expected = "does not belong" if failure == "early" else "partial metadata registration"
        with pytest.raises(RuntimeError, match=expected):
            spec.loader.exec_module(startup)
        assert calls == []
        assert "/health/" not in api.handlers
        assert "/status/" not in api.handlers
        # Partial strict initialization can have registered cached metadata;
        # it must never turn into a degraded legacy success/fallback.
        if "/metadata/" in api.handlers:
            assert api.handlers["/metadata/"]()["status"] != 503
        return
    spec.loader.exec_module(startup)
    assert len(calls) == 6
    assert "/health/" not in api.handlers
    assert list(inspect.signature(api.handlers["/status/"]).parameters) == ["uiapp", "request"]
    metadata_response = api.handlers["/metadata/"]()
    assert metadata_response["status"] == 200
    assert validate_snapshot(metadata_response["data"])["endpoint"] == "http://127.0.0.1:48884/revit_mcp"


async def test_retirement_during_metadata_tool_read_is_a_typed_error(mock_mcp):
    from tools.target_tools import register_target_tools
    directory = TargetDirectory()
    snapshot = metadata()
    handle = directory.observe(snapshot)["target"]
    async def revalidate(target):
        directory.observe(metadata())  # port has a new owner between handshake/list
    register_target_tools(mock_mcp, directory, SimpleNamespace(revalidate=revalidate))
    with pytest.raises(IdentityError) as error:
        await mock_mcp.tools["get_revit_target_metadata"](handle, ctx=None)
    assert error.value.code == "expired_target"


def test_pruning_deletes_only_proven_stale_owned_files(tmp_path):
    live, reused, dead, inaccessible = (metadata(process_id=pid) for pid in (100, 200, 300, 400))
    for record in (live, reused, dead, inaccessible):
        (tmp_path / ("%s.json" % record["process_id"])).write_text(json.dumps(record))
    unknown = tmp_path / "notes.json"
    unknown.write_text("unrelated")
    malformed = tmp_path / "500.json"
    malformed.write_text("bad JSON")
    current_runtime, stale_runtime = uid(), uid()
    stale_temp = tmp_path / ("100.json.%s.tmp" % stale_runtime)
    stale_temp.write_text("stale own temp")
    current_temp = tmp_path / ("100.json.%s.tmp" % current_runtime)
    current_temp.write_text("current temp")
    foreign_temp = tmp_path / ("200.json.%s.tmp" % stale_runtime)
    foreign_temp.write_text("other process temp")
    def inspect_start(pid):
        if pid == 400:
            raise OSError("access denied")
        return {100: live["process_started_at"], 200: "new process start", 300: None}[pid]
    runtime.prune_registration_records(str(tmp_path), 100, current_runtime, inspect_start)
    assert (tmp_path / "100.json").exists()
    assert not (tmp_path / "200.json").exists()
    assert not (tmp_path / "300.json").exists()
    assert (tmp_path / "400.json").exists()
    assert unknown.exists() and malformed.exists()
    assert not stale_temp.exists()
    assert current_temp.exists() and foreign_temp.exists()


def test_publish_serializes_pruning_and_atomic_record_replacement(monkeypatch, tmp_path):
    lock = threading.Lock()
    active, maximum, releases = [0], [0], []
    class Lease:
        def __init__(self, path, mode, access, sharing):
            assert str(path).endswith(".registration.lock")
            assert (mode, access, sharing) == ("open", "rw", "exclusive")
            lock.acquire()
            active[0] += 1
            maximum[0] = max(maximum[0], active[0])
        def Dispose(self):
            active[0] -= 1
            releases.append(True)
            lock.release()
    monkeypatch.setitem(sys.modules, "System.IO", SimpleNamespace(
        File=SimpleNamespace(Exists=os.path.exists, Replace=lambda src, dst, _: os.replace(src, dst), Move=os.rename),
        FileStream=Lease, FileMode=SimpleNamespace(OpenOrCreate="open"),
        FileAccess=SimpleNamespace(ReadWrite="rw"), FileShare=SimpleNamespace(**{"None": "exclusive"})))
    snapshots = [metadata(process_id=pid) for pid in range(100, 104)]
    starts = {snapshot["process_id"]: snapshot["process_started_at"] for snapshot in snapshots}
    monkeypatch.setattr(runtime, "native_process_started_at", lambda pid: starts.get(pid))
    (tmp_path / "999.json").write_text(json.dumps(metadata(process_id=999)))
    with ThreadPoolExecutor(max_workers=4) as workers:
        paths = list(workers.map(lambda snap: runtime.publish_registration(snap, str(tmp_path)), snapshots))
    assert maximum[0] == 1 and active[0] == 0 and len(releases) == 4
    assert not (tmp_path / "999.json").exists()
    for snapshot, path in zip(snapshots, paths):
        result = json.loads(open(path).read())
        assert result["instance_id"] == snapshot["instance_id"]
    assert not list(tmp_path.glob("*.tmp"))
    replacement = dict(snapshots[0], runtime_id=uid())
    runtime.publish_registration(replacement, str(tmp_path))
    assert json.loads((tmp_path / "100.json").read_text())["runtime_id"] == replacement["runtime_id"]
