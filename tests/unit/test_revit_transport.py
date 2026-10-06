"""Exercise HTTP outcomes and ambiguous delivery with an actual httpx client."""

import json

import httpx
import pytest

from tools.revit_transport import request_revit


URL = "http://fixture.invalid/revit_mcp/execute_code/"


@pytest.mark.parametrize("status", [200, 202, 409, 503, 500])
async def test_preserves_json_and_http_metadata(status):
    body = {
        "status": "error" if status == 500 else "queued",
        "operation_id": "original-id", "partial_output": "before exception\n",
        "traceback": "script.py:8 AssertionError", "effects": "committed",
        "instance_id": "instance", "runtime_id": "runtime", "document_id": "document",
        "target": {"actual": "instance"}, "future_field": {"nested": [1, 2]},
    }
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Retry-After": "4"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await request_revit("POST", URL, data={"operation_id": "original-id"}, client=client)
        assert not client.is_closed

    assert result.body == body
    assert result.json_received
    assert result.status_code == status
    assert ("retry-after", "4") in result.headers
    assert result.method == "POST" and result.url == URL
    assert result.http_success == (status < 300)
    assert result.revit_error == (status == 500)
    assert result.failure_kind is None
    assert len(requests) == 1  # Even Retry-After on 503 does not replay the POST.
    assert client.is_closed  # Caller context, not transport, closes it.


@pytest.mark.parametrize("body", [None, [1, {"a": 2}], "text", 42, False])
async def test_valid_non_object_json_is_preserved(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(202, content=json.dumps(body)))) as client:
        result = await request_revit("GET", URL, client=client)
        assert not client.is_closed
    assert result.json_received and result.body == body
    assert result.kind == "json_response"


@pytest.mark.parametrize("status,raw", [(200, b"{broken"), (500, b"<html>failed</html>"),
                                        (204, b""), (200, b'{"bad":"\xff"}')])
async def test_invalid_json_retains_response_without_claiming_revit_error(status, raw):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, content=raw))) as client:
        result = await request_revit("POST", URL, client=client)
    assert result.failure_kind == "invalid_json"
    assert not result.json_received and not result.revit_error
    assert result.status_code == status and result.raw_body == raw
    assert result.response_text is not None
    assert result.mutation_outcome_unknown


@pytest.mark.parametrize("exc_type,kind,unknown", [
    (httpx.ConnectError, "connection_error", False),
    (httpx.ConnectTimeout, "timeout", False),
    (httpx.PoolTimeout, "timeout", False),
    (httpx.ReadTimeout, "timeout", True),
    (httpx.WriteTimeout, "timeout", True),
    (httpx.ReadError, "transport_error", True),
    (httpx.WriteError, "transport_error", True),
    (httpx.RemoteProtocolError, "transport_error", True),
])
async def test_failure_classification_and_no_retry(exc_type, kind, unknown):
    attempts = []

    def handler(request):
        attempts.append(request)
        raise exc_type("controlled failure", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await request_revit("POST", URL, client=client)
    assert result.failure_kind == result.kind == kind
    assert result.exception_type == exc_type.__name__
    assert result.mutation_outcome_unknown == unknown
    assert result.body is None and result.status_code is None
    assert not result.json_received and not result.revit_error
    assert len(attempts) == 1


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_lost_receipt_after_admission_inspects_original_id(failure):
    admitted = {}
    submissions = []

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            submissions.append(payload)
            admitted[payload["operation_id"]] = {"operation_id": payload["operation_id"],
                                                  "state": "succeeded", "effects": "committed"}
            raise failure("receipt lost after admission", request=request)
        return httpx.Response(200, json=admitted[request.url.params["operation_id"]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        submission = await request_revit("POST", URL, data={"operation_id": "original"}, client=client)
        inspection = await request_revit("GET", URL, params={"operation_id": "original"}, client=client)
    assert submission.mutation_outcome_unknown
    assert inspection.body == {"operation_id": "original", "state": "succeeded", "effects": "committed"}
    assert submissions == [{"operation_id": "original"}]


async def test_read_timeout_does_not_imply_mutation_for_get():
    def handler(request):
        raise httpx.ReadTimeout("busy", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await request_revit("GET", URL, client=client)
    assert result.failure_kind == "timeout"
    assert not result.mutation_outcome_unknown


async def test_revit_error_over_http_success_is_not_a_transport_error():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"status": "error", "traceback": "AssertionError", "effects": "rolled_back"}))) as client:
        result = await request_revit("GET", URL, client=client)
    assert result.http_success and result.revit_error
    assert result.kind == "revit_error" and result.failure_kind is None


async def test_recoverable_error_note_is_not_a_revit_exception():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            409, json={"status": "name_collision", "error": "Choose another name"}))) as client:
        result = await request_revit("POST", URL, client=client)
    assert result.kind == "http_error" and not result.revit_error


async def test_unsupported_method_fails_before_delivery():
    with pytest.raises(ValueError, match="GET and POST"):
        await request_revit("DELETE", URL)
