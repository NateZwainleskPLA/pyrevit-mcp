"""Explicit application client tools and original target confirmation."""
import inspect
from unittest.mock import AsyncMock

import pytest

from revit_mcp.routing_policy import RoutingPolicyError
from tools.code_execution_tools import register_code_execution_tools
from tools.revit_transport import RevitTransportResult
from tools.target_router import TargetRouter
from tests.unit.test_target_router import Directory


async def test_application_router_requires_only_target_and_confirms_original_identity():
    body = {"status": "success", "actual_target": {"instance_id": "instance1", "runtime_id": "runtime1"}}
    request = AsyncMock(return_value=RevitTransportResult(
        method="POST", url="fixture", status_code=200, json_received=True, body=body))
    handshake = AsyncMock()
    router = TargetRouter(Directory(), handshake, request)
    result = await router.call("POST", "/execute_application_code/", target="r1", data={"code": "pass"})
    assert result.http_success and result.failure_kind is None
    assert request.await_args.kwargs["data"] == dict(code="pass", instance_id="instance1",
                                                     runtime_id="runtime1", allow_ui_change=False)
    assert "document_id" not in request.await_args.kwargs["data"]
    handshake.assert_awaited_once()
    request.assert_awaited_once()


@pytest.mark.parametrize("document", ["d1", "d2", ""])
async def test_application_router_rejects_document_selector_before_transport(document):
    request, handshake = AsyncMock(), AsyncMock()
    router = TargetRouter(Directory(), handshake, request)
    with pytest.raises(RoutingPolicyError) as error:
        await router.call("POST", "/execute_application_code/", target="r1", document=document)
    assert error.value.code == "unexpected_document"
    request.assert_not_awaited()
    handshake.assert_not_awaited()


@pytest.mark.parametrize("target", [None, "unknown"])
async def test_application_router_rejects_missing_or_unknown_target(target):
    request = AsyncMock()
    router = TargetRouter(Directory(), AsyncMock(), request)
    with pytest.raises((ValueError, KeyError)):
        await router.call("POST", "/execute_application_code/", target=target)
    request.assert_not_awaited()


@pytest.mark.parametrize("actual", [{}, {"instance_id": "foreign", "runtime_id": "runtime1"},
                                    {"instance_id": "instance1", "runtime_id": "stale"}])
async def test_application_success_from_wrong_receiver_is_unknown_and_never_replayed(actual):
    request = AsyncMock(return_value=RevitTransportResult(
        method="POST", url="fixture", status_code=200, json_received=True,
        body={"status": "success", "actual_target": actual}))
    router = TargetRouter(Directory(), AsyncMock(), request)
    result = await router.call("POST", "/execute_application_code/", target="r1", data={"code": "pass"})
    assert result.failure_kind == "invalid_identity_response" and result.mutation_outcome_unknown
    request.assert_awaited_once()


async def test_application_code_tool_uses_explicit_route_without_document(mock_mcp):
    post = AsyncMock(return_value={"status": "success", "output": "opened",
                                  "actual_target": {"instance_id": "confirmed"}})
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    result = await mock_mcp.tools["execute_revit_application_code"](
        target="r1", code="new_doc = app.OpenDocumentFile('fixture.rvt')", allow_ui_change=True,
        script_name="bootstrap.py", description="Bootstrap")
    assert "confirmed" in result and "opened" in result
    assert post.await_args.args[:2] == ("/execute_application_code/", {
        "code": "new_doc = app.OpenDocumentFile('fixture.rvt')", "description": "Bootstrap",
        "transaction_mode": "script", "script_name": "bootstrap.py"})
    assert post.await_args.kwargs == {"target": "r1", "allow_ui_change": True, "timeout": 60.0}
    signature = inspect.signature(mock_mcp.tools["execute_revit_code"])
    assert signature.parameters["document"].default is inspect.Parameter.empty
    assert "document" not in inspect.signature(mock_mcp.tools["execute_revit_application_code"]).parameters


async def test_application_file_tool_reads_local_utf8_bom_and_sends_basename_only(tmp_path, mock_mcp):
    path = tmp_path / "検証.py"
    path.write_bytes(b"\xef\xbb\xbf" + "print(u'雪')\r\n".encode("utf-8"))
    post = AsyncMock(return_value={"status": "error", "partial_output": "雪",
                                  "actual_target": {"runtime_id": "confirmed"}})
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    result = await mock_mcp.tools["execute_revit_application_script_file"](
        target="remote", file_path=str(path))
    assert "confirmed" in result and "雪" in result
    assert post.await_args.args[0] == "/execute_application_code/"
    payload = post.await_args.args[1]
    assert payload["code"] == "print(u'雪')\n" and payload["script_name"] == "検証.py"
    assert len(payload["script_sha256"]) == 64 and str(tmp_path) not in str(payload)
    assert post.await_args.kwargs == {"target": "remote", "allow_ui_change": False, "timeout": 60.0}
    post.assert_awaited_once()


@pytest.mark.parametrize("tool", ["execute_revit_application_code", "execute_revit_application_script_file"])
async def test_application_tools_reject_managed_mode_without_transport(mock_mcp, tool):
    post = AsyncMock()
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    kwargs = {"code": "pass"} if tool.endswith("_code") else {"file_path": "missing.py"}
    result = await mock_mcp.tools[tool](target="r1", transaction_mode="managed", **kwargs)
    assert "script" in result and "Error" in result
    post.assert_not_awaited()


async def test_application_cli_file_adapter_uses_same_transport_and_file_payload(tmp_path):
    from scripts.execute_revit_file import execute_application_script_file
    path = tmp_path / "bootstrap.py"
    path.write_text("print('continued')", encoding="utf-8")
    router = type("Router", (), {"call": AsyncMock(return_value="receipt")})()
    result = await execute_application_script_file(router, path, target="r1", allow_ui_change=True)
    assert result == "receipt"
    assert router.call.await_args.args == ("POST", "/execute_application_code/")
    assert router.call.await_args.kwargs["target"] == "r1"
    assert "document" not in router.call.await_args.kwargs
    assert router.call.await_args.kwargs["data"]["script_name"] == "bootstrap.py"


@pytest.mark.parametrize("contents", [None, b"\xff\xfe"])
async def test_application_file_errors_never_send_request(tmp_path, contents, mock_mcp):
    path = tmp_path / "bad.py"
    if contents is not None:
        path.write_bytes(contents)
    post = AsyncMock()
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    result = await mock_mcp.tools["execute_revit_application_script_file"](target="r1", file_path=str(path))
    assert "Error" in result
    post.assert_not_awaited()


@pytest.mark.parametrize("scope_args", [[], ["--application", "--document", "d1"],
                                        ["--application", "--transaction-mode", "managed"]])
def test_cli_requires_explicit_single_scope_and_rejects_application_managed_mode(scope_args, capsys):
    from scripts.execute_revit_file import main
    with pytest.raises(SystemExit) as error:
        main(["--file", "fixture.py", "--target", "r1"] + scope_args)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


async def test_native_mcp_registration_exposes_target_only_application_tools():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("application-contract-test")
    register_code_execution_tools(mcp, AsyncMock(), AsyncMock())
    schemas = {tool.name: tool.inputSchema for tool in await mcp.list_tools()}
    for name in ("execute_revit_application_code", "execute_revit_application_script_file"):
        assert "target" in schemas[name]["required"]
        assert "document" not in schemas[name]["properties"]
    for name in ("execute_revit_code", "execute_revit_script_file"):
        assert "document" in schemas[name]["required"]
