"""Per-call routing over the identity directory and single-attempt transport."""
import anyio
import httpx
from dataclasses import replace

from revit_mcp.routing_policy import MUTATION_ROUTES, ROUTES, RoutingPolicyError, route_policy
from .revit_transport import RevitTransportResult, request_revit


def _revalidation_failure(error):
    """Preserve handshake evidence; the directed execution request was not sent."""
    try:
        request = error.request
    except RuntimeError:  # Injected failures may not carry a Request.
        request = None
    response = getattr(error, "response", None)
    metadata = dict(method=request.method if request is not None else "GET",
                    url=str(request.url) if request is not None else "",
                    failure_kind="target_revalidation_failed",
                    error="Target revalidation failed; execution request was not sent: {}".format(str(error) or type(error).__name__),
                    exception_type=type(error).__name__, mutation_outcome_unknown=False)
    if response is not None:
        metadata.update(status_code=response.status_code,
                        headers=tuple(response.headers.multi_items()),
                        raw_body=response.content, response_text=response.text)
        try:
            metadata.update(body=response.json(), json_received=True)
        except (ValueError, UnicodeError):
            pass
    return RevitTransportResult(**metadata)


class TargetRouter:
    def __init__(self, directory, handshake, request=request_revit):
        self.directory = directory
        self.handshake = handshake
        self.request = request
        self._locks = {}

    async def resolve(self, target, document=None):
        # The directory's revalidate clears verification while a handshake is
        # outstanding. Serialize that step for one handle; different handles
        # stay independent, and HTTP execution happens outside this lock.
        lock = self._locks.setdefault(target, anyio.Lock())
        async with lock:
            await self.directory.revalidate(target, self.handshake)
            return self.directory.resolve(target, document)

    async def call(self, method, endpoint, *, target, document=None, data=None,
                   params=None, timeout=30.0, allow_ui_change=False, policy=None):
        requires_document = (policy or route_policy(endpoint))[0]
        if not target:
            raise RoutingPolicyError("missing_target", "An explicit target handle is required")
        if requires_document and not document:
            raise RoutingPolicyError("missing_document", "An explicit document handle is required")
        if endpoint == "/execute_application_code/" and document is not None:
            raise RoutingPolicyError("unexpected_document", "Application execution does not accept a document handle")
        if type(allow_ui_change) is not bool:
            raise RoutingPolicyError("invalid_ui_permission", "allow_ui_change must be a boolean")
        operation_values = params if method.upper() == "GET" else data
        if endpoint.startswith("/operations/") and operation_values is not None and not isinstance(operation_values, dict):
            raise RoutingPolicyError("invalid_request", "Operation request fields must be a JSON object")
        expected_operation = (operation_values or {}).get("operation_id") if endpoint.startswith("/operations/") else None
        if endpoint.startswith("/operations/") and (not isinstance(expected_operation, str) or not expected_operation.strip()):
            raise RoutingPolicyError("missing_operation_id", "An explicit nonempty operation ID is required")
        try:
            resolved = await self.resolve(target, document)
        except httpx.HTTPError as error:
            return _revalidation_failure(error)
        identities = {key: resolved[key] for key in ("instance_id", "runtime_id")}
        if document is not None:
            identities["document_id"] = resolved["document_id"]
        # Do not let body/query callers override receiver validation fields.
        for values in (data, params):
            if values and any(key in values for key in (
                    "target", "document", "instance_id", "runtime_id", "document_id", "allow_ui_change")):
                raise RoutingPolicyError("reserved_identity", "Identity fields are supplied by the target router")
        url = resolved["endpoint"].rstrip("/") + endpoint
        if method.upper() == "GET":
            query = dict(params or {})
            query.update(identities, allow_ui_change="true" if allow_ui_change else "false")
            result = await self.request(method, url, params=query, timeout=timeout)
        else:
            payload = dict(data or {})
            payload.update(identities, allow_ui_change=allow_ui_change)
            result = await self.request(method, url, data=payload, params=params, timeout=timeout)
        # HTTP method alone does not distinguish read-only POST queries from
        # mutating operations. Preserve receiver effects; this flag describes
        # only delivery ambiguity for a potentially mutating request.
        known_route = endpoint in ROUTES or endpoint.startswith("/get_view/")
        may_mutate = (not known_route or endpoint in MUTATION_ROUTES or
                      endpoint in ("/operations/submit/", "/operations/cancel/"))
        if result is not None and not may_mutate and result.mutation_outcome_unknown:
            result = replace(result, mutation_outcome_unknown=False)
        if result is not None and result.http_success and not result.revit_error and not result.failure_kind:
            body = result.body if isinstance(result.body, dict) else {}
            actual = body.get("actual_target", body)
            wrong_operation = expected_operation is not None and body.get("operation_id") != expected_operation
            if (not isinstance(actual, dict) or any(actual.get(key) != value for key, value in identities.items())
                    or wrong_operation):
                return replace(result, failure_kind="invalid_identity_response",
                               error="Successful response did not confirm the addressed target/document/operation",
                               mutation_outcome_unknown=method.upper() == "POST" and may_mutate)
        return result
