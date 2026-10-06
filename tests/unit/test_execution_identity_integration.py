"""Real identity/operation modules, inert documents, no native acceptance claim."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from revit_mcp.execution_runtime import NativeExecutionAdapter, ExecutionRuntime
from revit_mcp.operation_store import OperationError, OperationStore
from tests.unit.test_operation_runtime import Event
from tests.unit.test_target_identity import registry, Document
from tools.target_directory import TargetDirectory
from tools.target_router import TargetRouter
from tools.execution_tools import register_execution_tools
from tools.revit_transport import RevitTransportResult


def setup(service=None):
    reg = registry()
    a, b = Document("same"), Document("same")
    a.IsModifiable = b.IsModifiable = False
    uiapp = SimpleNamespace(Application=SimpleNamespace(Documents=[a, b]),
                            ActiveUIDocument=SimpleNamespace(Document=a))
    adapter = NativeExecutionAdapter(reg, service or
        (lambda p, d, u, cancellation_check=None, **kwargs: ({"status": "success", "effects": "none"}, 200)))
    adapter.refresh_api(uiapp)
    adapter.observe_safety_api(uiapp)
    snap = reg.snapshot()
    value = dict(operation_id="one", code="pass", transaction_mode="script", allow_ui_change=False,
                 instance_id=snap["instance_id"], runtime_id=snap["runtime_id"],
                 document_id=snap["documents"][0]["document_id"])
    engine = ExecutionRuntime(OperationStore(snap["runtime_id"]), adapter.validate_cached,
                              adapter.validate_api, adapter.execute, experimental=True,
                              exclusive=True, refresh=adapter.refresh_api,
                              admission_guard=adapter.admit_cached)
    engine.bind_event(Event())
    engine.adapter = adapter
    return engine, adapter, reg, uiapp, value, a, b


def test_closed_document_after_admission_never_executes_or_compares_invalid_wrapper():
    engine, adapter, reg, uiapp, value, a, b = setup(lambda *a, **k: pytest.fail("must not execute"))
    engine.submit(value)
    a.IsValidObject = False
    a.Equals = lambda _: pytest.fail("cannot compare closed wrapper")
    uiapp.Application.Documents = [b]
    uiapp.ActiveUIDocument = SimpleNamespace(Document=b)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "none")
    assert not engine.command_running


def test_active_switch_preserves_selected_document_and_does_not_activate_it():
    selected = []
    def service(p, doc, uidoc, cancellation_check=None, **kwargs):
        selected.append((doc, uidoc))
        return {"status": "success", "effects": "none"}, 200
    engine, adapter, reg, uiapp, value, a, b = setup(service)
    engine.submit(value)
    uiapp.ActiveUIDocument = SimpleNamespace(Document=b)
    engine.on_external_event(uiapp)
    assert selected == [(a, None)]
    assert uiapp.ActiveUIDocument.Document is b
    receipt = engine.store.inspect("one")
    assert receipt["actual_target"]["document_id"] == value["document_id"]


def test_wrong_full_runtime_never_admits():
    engine, adapter, reg, uiapp, value, a, b = setup()
    value["runtime_id"] = str(uuid.uuid4())
    with pytest.raises(OperationError) as failure:
        engine.submit(value)
    assert failure.value.code == "stale_target"
    assert not engine.store.has_queued()


def test_cached_validator_never_dereferences_live_wrappers():
    engine, adapter, reg, uiapp, value, a, b = setup()
    class Poison:
        def __getattribute__(self, _):
            pytest.fail("background access")
    reg._documents = [(Poison(), value["document_id"])]
    adapter.validate_cached(value)
    engine.submit(value)


def test_raw_leak_in_another_document_quarantines_host_and_retains_inspection():
    engine, adapter, reg, uiapp, value, a, b = setup()
    def service(p, d, u, cancellation_check=None, **kwargs):
        b.IsModifiable = True
        return {"status": "success", "effects": "committed"}, 200
    adapter.execute_payload = service
    engine.submit(value)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "unknown")
    assert engine.quarantined and not engine.command_running
    # Cached identity inspection remains available even when safety fails.
    adapter.validate_cached(value)
    assert engine.submit(value)[1] is False
    with pytest.raises(OperationError):
        engine.submit(dict(value, operation_id="two"))


def test_document_became_modifiable_before_callback_blocks_executor():
    engine, adapter, reg, uiapp, value, a, b = setup(lambda *a, **k: pytest.fail("must not execute"))
    engine.submit(value)
    b.IsModifiable = True
    engine.on_external_event(uiapp)
    assert engine.quarantined
    assert engine.store.inspect("one")["effects"] == "none"


async def test_real_target_router_and_recoverable_tool_reserved_fields(mock_mcp):
    engine, adapter, reg, uiapp, value, a, b = setup()
    directory = TargetDirectory()
    decorated = directory.observe(reg.snapshot())
    request = AsyncMock(return_value=RevitTransportResult("POST", "http://host", status_code=202,
                    body={"operation_id": "one", "state": "queued", "effects": "none",
                          "actual_target": {key: value[key] for key in ("instance_id", "runtime_id", "document_id")}},
                    json_received=True))
    handshake = AsyncMock(return_value=reg.snapshot())
    router = TargetRouter(directory, handshake, request=request)
    register_execution_tools(mock_mcp, router)
    result = await mock_mcp.tools["submit_revit_execution"](decorated["target"],
                                   decorated["documents"][0]["document"], "one", "pass")
    assert result["http_status"] == 202
    assert result["failure_kind"] is None
    transmitted = request.call_args.kwargs["data"]
    assert transmitted["instance_id"] == value["instance_id"]
    assert transmitted["document_id"] == value["document_id"]
    assert "target" not in transmitted and "document" not in transmitted
    receipt, admitted = engine.submit(transmitted)
    assert admitted and receipt["actual_target"]["instance_id"] == value["instance_id"]


def test_primitive_http_inspection_after_document_closes_still_returns_retained_result():
    from revit_mcp.execution_routes import register_execution_routes
    engine, adapter, reg, uiapp, value, a, b = setup()
    engine.submit(value)
    engine.on_external_event(uiapp)
    a.IsValidObject = False
    uiapp.Application.Documents = [b]
    uiapp.ActiveUIDocument = SimpleNamespace(Document=b)
    adapter.refresh_api(uiapp)
    class API:
        def route(self, path, **options):
            return lambda fn: fn
    respond = register_execution_routes(API(), engine, lambda **kw: kw)
    identities = {key: value[key] for key in ("instance_id", "runtime_id", "operation_id")}
    result = respond("inspect", SimpleNamespace(data=identities))
    assert result["status"] == 200
    assert result["data"]["state"] == "succeeded"
    assert result["data"]["document_id"] == value["document_id"]
    assert result["data"]["actual_target"]["document_id"] == value["document_id"]


def test_primitive_http_cancellation_after_document_closes_removes_queued_work():
    from revit_mcp.execution_routes import register_execution_routes
    engine, adapter, reg, uiapp, value, a, b = setup()
    engine.submit(value)
    a.IsValidObject = False
    adapter.registry.refresh_documents([b], b)
    class API:
        def route(self, path, **options):
            return lambda fn: fn
    respond = register_execution_routes(API(), engine, lambda **kw: kw)
    identities = {key: value[key] for key in ("instance_id", "runtime_id", "operation_id")}
    result = respond("cancel", SimpleNamespace(data=identities))
    assert result["status"] == 200 and result["data"]["state"] == "canceled"
    assert not engine.store.has_queued()


def test_native_escape_is_user_canceled_and_never_inferred_from_elapsed_time():
    def service(p, d, u, **kwargs):
        return dict(status="error", error_type="OperationCanceledException", effects="unknown"), 500
    engine, adapter, reg, uiapp, value, a, b = setup(service)
    engine.submit(value)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "canceled"
    assert receipt["result"]["outcome"] == "user_canceled"
    assert receipt["effects"] == "unknown"


async def test_actual_client_receiver_roundtrip_recovers_after_document_retirement(mock_mcp):
    from revit_mcp.execution_routes import register_execution_routes
    engine, adapter, reg, uiapp, value, a, b = setup()
    class API:
        def route(self, path, **options):
            return lambda fn: fn
    respond = register_execution_routes(API(), engine, lambda **kw: kw)
    async def send(method, url, data=None, **kwargs):
        action = url.rstrip("/").rsplit("/", 1)[-1]
        response = respond(action, SimpleNamespace(data=data))
        return RevitTransportResult(method, url, status_code=response["status"],
                                     body=response["data"], json_received=True)
    directory = TargetDirectory()
    decorated = directory.observe(reg.snapshot())
    router = TargetRouter(directory, AsyncMock(side_effect=lambda endpoint: reg.snapshot()), request=send)
    register_execution_tools(mock_mcp, router)
    target, document = decorated["target"], decorated["documents"][0]["document"]
    receipt = await mock_mcp.tools["submit_revit_execution"](target, document, "one", "pass")
    assert receipt["failure_kind"] is None and receipt["http_status"] == 202
    engine.on_external_event(uiapp)
    await mock_mcp.tools["submit_revit_execution"](target, document, "two", "pass")
    a.IsValidObject = False
    uiapp.Application.Documents = [b]
    uiapp.ActiveUIDocument = SimpleNamespace(Document=b)
    adapter.refresh_api(uiapp)
    inspected = await mock_mcp.tools["get_revit_operation"](target, "one")
    assert inspected["failure_kind"] is None
    assert inspected["response"]["document_id"] == value["document_id"]
    canceled = await mock_mcp.tools["cancel_revit_operation"](target, "two")
    assert canceled["failure_kind"] is None and canceled["response"]["state"] == "canceled"
    assert not engine.store.has_queued()
    foreign = dict(instance_id=value["instance_id"], runtime_id=str(uuid.uuid4()), operation_id="one")
    assert respond("inspect", SimpleNamespace(data=foreign))["status"] == 409
    missing = dict(instance_id=value["instance_id"], runtime_id=value["runtime_id"], operation_id="foreign")
    assert respond("inspect", SimpleNamespace(data=missing))["status"] == 404
    reg.expire()
    assert respond("inspect", SimpleNamespace(data=missing))["status"] == 409
