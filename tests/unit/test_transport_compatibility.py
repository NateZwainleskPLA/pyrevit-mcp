"""HTTP-to-tool checks using controlled responses, without a Revit host."""

import base64
import json

import httpx
import pytest
from mcp.server.fastmcp import Image

import main
from tools.code_execution_tools import register_code_execution_tools
from tools.revit_transport import RevitTransportResult, request_revit
from tools.utils import compatibility_response, format_response


@pytest.fixture
def install_http(monkeypatch):
    real_client = httpx.AsyncClient

    def install(handler):
        requests = []

        def record(request):
            requests.append(request)
            return handler(request)

        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(record), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)
        return requests

    return install


async def test_main_keeps_full_internal_result_and_legacy_dictionary(install_http):
    body = {"status": "error", "error": "boom", "partial_output": "step one",
            "traceback": "script.py:3 AssertionError", "effects": "committed",
            "instance_id": "actual", "runtime_id": "generation", "document_id": "open-document"}
    requests = install_http(lambda request: httpx.Response(500, json=body,
                                                           headers={"X-Receiver": "actual"}))
    result = await main._revit_call("POST", "/execute_code/", data={"code": "raise AssertionError"})
    response = await main.revit_post("/execute_code/", {"code": "raise AssertionError"})
    assert isinstance(result, RevitTransportResult)
    assert result.body == body and result.status_code == 500
    assert isinstance(response, dict) and response == body
    assert response.transport_result.body == body
    assert response.transport_result.headers == result.headers
    rendered = format_response(response)
    assert "HTTP 500 Internal Server Error" in rendered
    for evidence in ("boom", "step one", "AssertionError", "committed", "actual", "generation", "open-document"):
        assert evidence in rendered
    assert len(requests) == 2


@pytest.mark.parametrize("status", [202, 409, 503])
async def test_non_200_receipts_reach_tools_without_invented_crash(status, install_http, mock_mcp):
    body = {"state": "queued", "operation_id": "original", "effects": "none", "target": "actual"}
    requests = install_http(lambda request: httpx.Response(status, json=body))
    register_code_execution_tools(mock_mcp, main.revit_get, main.revit_post)
    rendered = await mock_mcp.tools["execute_revit_code"]("print('one')")
    assert "HTTP {}".format(status) in rendered
    assert json.loads(rendered.split("\n", 1)[1]) == body
    assert "Unknown error occurred" not in rendered
    assert len(requests) == 1 and requests[0].method == "POST"


async def test_legacy_success_output_stays_readable_and_metadata_available(install_http):
    body = {"status": "success", "output": "hello\n"}
    install_http(lambda request: httpx.Response(200, json=body))
    response = await main.revit_post("/execute_code/", {"code": "print('hello')"})
    assert format_response(response) == "hello\n"
    assert response.transport_result.body == body


@pytest.mark.parametrize("value_field", ["output", "message", "result", "data"])
async def test_success_preserves_actual_target_aliases_and_effects(value_field, install_http):
    metadata = {"actual_target": {"instance_id": "instance", "runtime_id": "runtime",
                                   "document_id": "open-document"},
                "target": "r17", "document": "d4", "effects": "committed",
                "instance_id": "instance", "runtime_id": "runtime", "document_id": "open-document",
                "operation_id": "original"}
    body = {"status": "success", value_field: "done", **metadata}
    install_http(lambda request: httpx.Response(200, json=body))
    response = await main.revit_post("/execute_code/", {})
    rendered = format_response(response)
    assert rendered.startswith("done\n\n=== RESPONSE METADATA ===\n")
    assert json.loads(rendered.split("=== RESPONSE METADATA ===\n", 1)[1]) == metadata
    assert response.transport_result.body == body


@pytest.mark.parametrize("exc_type,expected,unknown", [
    (httpx.ConnectError, "Connection to Revit failed", False),
    (httpx.ReadTimeout, "Request timed out", True),
    (httpx.RemoteProtocolError, "Transport failure", True),
])
async def test_legacy_text_failure_exposes_structured_cause(exc_type, expected, unknown, install_http):
    def handler(request):
        raise exc_type("controlled", request=request)

    requests = install_http(handler)
    response = await main.revit_post("/execute_code/", {"operation_id": "original"})
    assert isinstance(response, str) and expected in response
    assert response.transport_result.exception_type == exc_type.__name__
    assert response.transport_result.mutation_outcome_unknown == unknown
    assert ("If this request changes the model, verify model state before resubmitting" in
            format_response(response)) == unknown
    assert len(requests) == 1


async def test_malformed_response_is_not_a_revit_exception(install_http):
    install_http(lambda request: httpx.Response(500, text="gateway failure"))
    response = await main.revit_post("/execute_code/", {})
    assert "malformed or non-JSON" in response
    assert "HTTP 500" in response and "gateway failure" in response
    assert response.transport_result.failure_kind == "invalid_json"
    assert not response.transport_result.revit_error
    assert response.transport_result.raw_body == b"gateway failure"


@pytest.mark.parametrize("body", [None, ["receipt", 2], False, "Unicode: \u753b\u50cf"])
async def test_non_object_json_compatibility_retains_original(body, install_http):
    install_http(lambda request: httpx.Response(200, content=json.dumps(body)))
    response = await main.revit_get("/status/")
    assert json.loads(response) == body
    assert response.transport_result.body == body
    assert response.transport_result.json_received


async def test_get_passes_query_and_timeout_through_actual_client(install_http):
    requests = install_http(lambda request: httpx.Response(200, json={"status": "success"}))
    await main.revit_get("/status/", params={"operation_id": "original"}, timeout=7.0)
    assert requests[0].url.params["operation_id"] == "original"
    assert requests[0].extensions["timeout"] == {"connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0}


async def test_image_uses_same_transport_and_decodes_valid_payload(install_http):
    data = b"fixture-png-bytes"
    requests = install_http(lambda request: httpx.Response(200, json={
        "image_data": base64.b64encode(data).decode("ascii")}))
    response = await main.revit_image("/export_image/")
    assert isinstance(response, Image) and response.data == data
    assert requests[0].extensions["timeout"]["read"] == 60.0


async def test_image_revit_error_retains_diagnostics(install_http):
    install_http(lambda request: httpx.Response(500, json={
        "status": "error", "error": "export failed", "traceback": "export.py:4", "instance_id": "actual"}))
    response = await main.revit_image("/export_image/")
    assert "HTTP 500" in response and "export failed" in response
    assert "export.py:4" in response and "actual" in response


async def test_image_rejects_invalid_base64(install_http):
    install_http(lambda request: httpx.Response(200, json={"image_data": "***"}))
    assert "Invalid image data" in await main.revit_image("/export_image/")


async def test_transport_formatting_does_not_mutate_body():
    body = {"status": "queued", "operation_id": "original", "effects": "none"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(202, json=body))) as client:
        result = await request_revit("POST", "http://fixture.invalid/", client=client)
    response = compatibility_response(result)
    assert "=== QUEUED ===" in format_response(response)
    assert "=== ERROR DETAILS ===" not in format_response(result)
    assert result.body == response == body
    assert "status_code" not in response and "transport_result" not in response


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("status", [408, 500])
async def test_native_pyrevit_exception_is_an_error_not_a_timeout(method, status, install_http):
    body = {"exception": {"source": "Autodesk Revit 2025",
                          "message": "InvalidOperationException\nScript Executor Traceback: script.py:8"},
            "target": "r17", "effects": "unknown"}
    requests = install_http(lambda request: httpx.Response(status, json=body))
    result = await main._revit_call(method, "/place_family/", data={})
    assert result.revit_error and result.kind == "revit_error"
    assert result.failure_kind is None and result.body == body
    for view in (result, compatibility_response(result), dict(body)):
        text = format_response(view)
        assert "=== ERROR DETAILS ===" in text
        assert "Source: Autodesk Revit 2025" in text
        assert "Error: InvalidOperationException" in text
        assert "Script Executor Traceback: script.py:8" in text
        assert "r17" in text and "unknown" in text
        assert "Request Timeout" not in text
        if not isinstance(view, dict) or hasattr(view, "transport_result"):
            assert text.startswith("Error:")
            assert "HTTP {}".format(status) in text
    assert len(requests) == 1


@pytest.mark.parametrize("status", [302, 404, 409, 503])
async def test_every_non_2xx_json_result_is_error_prefixed(status, install_http):
    install_http(lambda request: httpx.Response(status, json={"detail": "endpoint response"}))
    response = await main.revit_get("/status/")
    assert format_response(response).startswith("Error: HTTP {}".format(status))
    assert response.transport_result.body == {"detail": "endpoint response"}


async def test_read_only_post_timeout_keeps_duration_without_claiming_mutation(install_http):
    def handler(request):
        raise httpx.ReadTimeout("controlled", request=request)

    requests = install_http(handler)
    response = await main.revit_post("/list_families/", {}, timeout=42.0)
    text = format_response(response)
    assert "timed out after 42 seconds" in text
    assert "If this request changes the model, verify model state before resubmitting" in text
    assert "mutation outcome" not in text and "Inspect the original operation" not in text
    assert response.transport_result.timeout_seconds == 42.0 and len(requests) == 1


async def test_main_preserves_readable_pre_delivery_build_failure(install_http):
    requests = install_http(lambda request: httpx.Response(200, json={}))
    response = await main.revit_post("/execute_code/", {"code": object()})
    assert isinstance(response, str) and response.startswith("Error:")
    assert response.transport_result.failure_kind == "request_error"
    assert not response.transport_result.mutation_outcome_unknown and not requests


async def test_empty_acknowledgement_text_does_not_invent_execution_success(install_http):
    install_http(lambda request: httpx.Response(204, content=b"\n"))
    response = await main.revit_post("/execute_code/", {})
    assert "HTTP 204" in response and "Empty response received" in response
    assert "Error:" not in response and "committed" not in response and "succeeded" not in response
    assert response.transport_result.kind == "empty_response"
    assert response.transport_result.body is None and not response.transport_result.json_received


@pytest.mark.parametrize("kwargs,expected", [({}, 30.0), ({"timeout": None}, None)])
async def test_owned_client_keeps_default_timeout_and_explicit_disable(install_http, kwargs, expected):
    requests = install_http(lambda request: httpx.Response(200, json={}))
    await request_revit("GET", "http://fixture.invalid/status/", **kwargs)
    assert requests[0].extensions["timeout"]["read"] == expected
