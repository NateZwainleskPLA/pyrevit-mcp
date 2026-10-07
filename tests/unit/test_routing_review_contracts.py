"""Regressions for the pinned Opus routing repros; no live host involved."""
import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from revit_mcp.routing_policy import RoutingPolicyError
from tools.revit_transport import RevitTransportResult
from tools.target_router import TargetRouter
from tests.unit.test_target_router import Directory


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("metadata timeout")])
async def test_handshake_failure_returns_structured_no_admission_and_never_sends(error):
    execution = AsyncMock()
    router = TargetRouter(Directory(), AsyncMock(side_effect=error), execution)
    result = await router.call("POST", "/execute_code/", target="r1", document="d1")
    assert result.failure_kind
    assert result.exception_type == type(error).__name__
    assert result.mutation_outcome_unknown is False
    assert "not sent" in result.error
    execution.assert_not_awaited()


async def test_handshake_http_error_preserves_metadata_response_without_execution():
    request = httpx.Request("GET", "http://127.0.0.1:49001/revit_mcp/metadata/")
    body = {"runtime_available": False, "error": "identity unavailable"}
    response = httpx.Response(503, json=body, request=request, headers=[("x-evidence", "one"), ("x-evidence", "two")])
    execution = AsyncMock()
    router = TargetRouter(Directory(), AsyncMock(side_effect=httpx.HTTPStatusError("unavailable", request=request, response=response)), execution)
    result = await router.call("POST", "/execute_code/", target="r1", document="d1")
    assert result.status_code == 503 and result.body == body
    assert result.json_received and result.raw_body == response.content
    assert [value for key, value in result.headers if key == "x-evidence"] == ["one", "two"]
    assert result.mutation_outcome_unknown is False
    execution.assert_not_awaited()


async def test_main_code_and_file_tool_render_handshake_failure(monkeypatch, tmp_path, mock_mcp):
    import main
    from tools.code_execution_tools import register_code_execution_tools
    request = AsyncMock()
    monkeypatch.setattr(main, "target_router", TargetRouter(Directory(), AsyncMock(side_effect=httpx.ConnectError("refused")), request))
    register_code_execution_tools(mock_mcp, main.revit_get, main.revit_post, main.revit_image)
    path = tmp_path / "edit.py"
    path.write_text("print('not sent')", encoding="utf-8")
    for name, kwargs in [("execute_revit_code", {"code": "print(1)"}),
                         ("execute_revit_script_file", {"file_path": str(path)})]:
        text = await mock_mcp.tools[name](target="r1", document="d1", **kwargs)
        assert "refused" in text and "not sent" in text
    request.assert_not_awaited()


def test_cli_handshake_failure_returns_error_without_traceback(monkeypatch, tmp_path, capsys):
    from scripts import execute_revit_file
    router = TargetRouter(Directory(), AsyncMock(side_effect=httpx.ConnectError("refused")), AsyncMock())
    async def run(args):
        return await execute_revit_file.execute_script_file(router, args.file, target=args.target, document=args.document)
    monkeypatch.setattr(execute_revit_file, "_run", run)
    path, state = tmp_path / "edit.py", tmp_path / "directory.sqlite"
    path.write_text("print(1)", encoding="utf-8")
    state.touch()
    assert execute_revit_file.main(["--file", str(path), "--state", str(state), "--target", "r1", "--document", "d1"]) == 1
    assert "refused" in capsys.readouterr().out
    router.request.assert_not_awaited()


@pytest.mark.parametrize("method,values", [("POST", {}), ("POST", {"operation_id": ""}),
                                        ("POST", {"operation_id": None}), ("GET", {})])
async def test_operation_call_requires_id_before_revalidation_or_transport(method, values):
    handshake, request = AsyncMock(), AsyncMock()
    router = TargetRouter(Directory(), handshake, request)
    with pytest.raises(RoutingPolicyError) as exc:
        await router.call(method, "/operations/cancel/", target="r1", **({"params": values} if method == "GET" else {"data": values}))
    assert exc.value.code == "missing_operation_id"
    handshake.assert_not_awaited()
    request.assert_not_awaited()


async def test_get_operation_confirmation_uses_actual_query_id():
    body = {"actual_target": {"instance_id": "instance1", "runtime_id": "runtime1"}, "operation_id": "other"}
    request = AsyncMock(return_value=RevitTransportResult("GET", "fixture", status_code=200, json_received=True, body=body))
    router = TargetRouter(Directory(), AsyncMock(), request)
    result = await router.call("GET", "/operations/inspect/", target="r1", params={"operation_id": "original"})
    assert result.failure_kind == "invalid_identity_response"
    assert result.body is body and not result.mutation_outcome_unknown
    request.assert_awaited_once()


async def test_received_transport_failure_is_not_reclassified_as_missing_identity():
    original = RevitTransportResult("POST", "fixture", status_code=200, failure_kind="invalid_json",
                                    raw_body=b"incomplete", error="invalid JSON", mutation_outcome_unknown=True)
    result = await TargetRouter(Directory(), AsyncMock(), AsyncMock(return_value=original)).call(
        "POST", "/execute_code/", target="r1", document="d1")
    assert result is original


async def test_unknown_explicit_policy_keeps_conservative_mutation_delivery_flag():
    original = RevitTransportResult("POST", "fixture", failure_kind="timeout", mutation_outcome_unknown=True)
    result = await TargetRouter(Directory(), AsyncMock(), AsyncMock(return_value=original)).call(
        "POST", "/custom_future_command/", target="r1", policy=(False, False, False))
    assert result is original


async def test_query_transport_loss_preserves_diagnostics_without_mutation_flag():
    original = RevitTransportResult("POST", "fixture", failure_kind="timeout", mutation_outcome_unknown=True, error="receipt lost")
    result = await TargetRouter(Directory(), AsyncMock(), AsyncMock(return_value=original)).call(
        "POST", "/list_families/", target="r1", document="d1")
    assert result.failure_kind == original.failure_kind and result.error == original.error
    assert result.mutation_outcome_unknown is False


@pytest.mark.parametrize("endpoint,document,values,unknown", [
    ("/list_families/", "d1", {}, False),
    ("/operations/inspect/", None, {"operation_id": "original"}, False),
    ("/execute_code/", "d1", {}, True),
    ("/operations/cancel/", None, {"operation_id": "original"}, True),
])
async def test_identity_mismatch_ambiguity_follows_route_semantics(endpoint, document, values, unknown):
    body = {"actual_target": {"instance_id": "other"}, "operation_id": "original", "effects": "committed"}
    request = AsyncMock(return_value=RevitTransportResult("POST", "fixture", status_code=200, json_received=True, body=body))
    result = await TargetRouter(Directory(), AsyncMock(), request).call("POST", endpoint, target="r1", document=document, data=values)
    assert result.failure_kind == "invalid_identity_response"
    assert result.mutation_outcome_unknown is unknown
    assert result.body is body and result.body["effects"] == "committed"
    request.assert_awaited_once()


def test_retained_guard_exception_from_prior_module_is_structured_no_admission(monkeypatch):
    from revit_mcp.target_routing import TargetedAPI
    from tests.unit.test_receiver_target_routing import API
    from tests.unit.test_target_identity import Document, registry
    spec = importlib.util.find_spec("revit_mcp.execution_safety")
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    safety = prior.ExecutionSafety()
    safety.observe({"unsafe": True, "error_type": "Cleanup"})
    snapshot = safety.snapshot()
    monkeypatch.setitem(sys.modules, "pyrevit", SimpleNamespace(routes=SimpleNamespace(make_response=lambda data, status=200, headers=None: SimpleNamespace(data=data, status=status))))
    doc, reg = Document(), registry()
    metadata = reg.refresh_documents([doc], doc)
    app = SimpleNamespace(Application=SimpleNamespace(Documents=[doc]), ActiveUIDocument=SimpleNamespace(Document=doc))
    execute = Mock()
    api = API()
    @TargetedAPI(api, registry_getter=lambda: reg, safety=safety).route("/execute_code/", methods=["POST"])
    def handler(doc, request):
        execute()
    ids = {key: metadata[key] for key in ("instance_id", "runtime_id")}
    ids["document_id"] = metadata["documents"][0]["document_id"]
    response = handler(app, SimpleNamespace(method="POST", data=ids))
    assert response.status == 409
    assert response.data["error_code"] == "mutation_blocked" and response.data["effects"] == "none"
    assert safety.snapshot() == snapshot
    execute.assert_not_called()
