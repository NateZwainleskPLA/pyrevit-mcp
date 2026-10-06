"""Single-attempt HTTP transport, independent of target and operation routing.

The decoded body is never augmented with client fields. HTTP and failure metadata
live beside it, so receiver identity, effects, diagnostics, and future fields
survive unchanged. A received HTTP error is not a connection failure.
"""

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class RevitTransportResult:
    method: str
    url: str
    status_code: int | None = None
    headers: tuple[tuple[str, str], ...] = ()
    body: Any = None
    json_received: bool = False
    raw_body: bytes = b""
    response_text: str = ""
    failure_kind: str | None = None
    error: str | None = None
    exception_type: str | None = None
    # Delivery ambiguity only. False does not prove absence of model/file
    # effects; a valid receipt's own state/effects remain authoritative.
    mutation_outcome_unknown: bool = False

    @property
    def http_success(self) -> bool:
        """HTTP success alone does not establish execution success/readiness."""
        return self.status_code is not None and 200 <= self.status_code < 300

    @property
    def revit_error(self) -> bool:
        """Explicit receiver failure, separate from HTTP/transport failures.

        Recoverable statuses can carry an 'error' note, so the presence of that
        field alone is not evidence of a Revit exception.
        """
        if not self.json_received or not isinstance(self.body, dict):
            return False
        status = self.body.get("status")
        return (isinstance(status, str) and
                (status.lower() in {"error", "failed"} or
                 status.lower().endswith("_failed"))) or self.body.get("success") is False or (
                     not status and bool(self.body.get("error") or self.body.get("traceback")))

    @property
    def kind(self) -> str:
        if self.failure_kind:
            return self.failure_kind
        if self.revit_error:
            return "revit_error"
        if not self.http_success:
            return "http_error"
        return "json_response"


class RevitResponse(dict):
    """Legacy dictionary view with full transport data available internally.

    No client-owned keys are inserted into the receiver's payload. Existing
    dictionary consumers keep working; new routing code should use the result
    directly rather than infer success from this view's type.
    """

    def __init__(self, result: RevitTransportResult):
        super().__init__(result.body)
        self.transport_result = result


class RevitResponseText(str):
    """Legacy text view retaining non-object JSON and transport failure data."""

    def __new__(cls, text: str, result: RevitTransportResult):
        value = super().__new__(cls, text)
        value.transport_result = result
        return value


async def request_revit(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    params: dict | None = None,
    timeout: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> RevitTransportResult:
    """Send exactly one request to the supplied URL; never retry a mutation.

    The caller owns routing/identity validation and operation reconciliation.
    An injected client stays open and must itself be configured without retries.
    Connect/pool failures precede delivery; read/write/disconnect failures can
    follow admission. Unknown outcomes must be inspected, never replayed here.
    """
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise ValueError("Revit transport supports only GET and POST")
    if client is None:
        async with httpx.AsyncClient(timeout=timeout) as owned_client:
            return await request_revit(method, url, data=data, params=params,
                                       timeout=timeout, client=owned_client)

    try:
        response = await client.request(method, url, params=params,
                                        **({"json": data} if method == "POST" else {}),
                                        timeout=timeout)
    except httpx.TimeoutException as exc:
        return _request_failure(method, url, "timeout", exc,
                                unknown=not isinstance(exc, (httpx.ConnectTimeout, httpx.PoolTimeout)))
    except httpx.ConnectError as exc:
        return _request_failure(method, url, "connection_error", exc, unknown=False)
    except httpx.RequestError as exc:
        return _request_failure(method, url, "transport_error", exc, unknown=True)

    metadata = dict(method=method, url=str(response.url), status_code=response.status_code,
                    headers=tuple(response.headers.multi_items()), raw_body=response.content,
                    response_text=response.text)
    try:
        body = response.json()
    except (ValueError, UnicodeError) as exc:
        return RevitTransportResult(
            **metadata, failure_kind="invalid_json", error=str(exc) or type(exc).__name__,
            exception_type=type(exc).__name__, mutation_outcome_unknown=method == "POST",
        )
    return RevitTransportResult(**metadata, body=body, json_received=True)


def _request_failure(method, url, kind, exc, *, unknown):
    return RevitTransportResult(
        method=method, url=url, failure_kind=kind,
        error=str(exc) or type(exc).__name__, exception_type=type(exc).__name__,
        mutation_outcome_unknown=method == "POST" and unknown,
    )
