"""Per-call routing over the identity directory and single-attempt transport."""
import anyio
from dataclasses import replace

from revit_mcp.routing_policy import RoutingPolicyError, route_policy
from .revit_transport import request_revit


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
        if type(allow_ui_change) is not bool:
            raise RoutingPolicyError("invalid_ui_permission", "allow_ui_change must be a boolean")
        resolved = await self.resolve(target, document)
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
        if result is not None and result.http_success and not result.revit_error:
            body = result.body if isinstance(result.body, dict) else {}
            actual = body.get("actual_target", body)
            if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in identities.items()):
                return replace(result, failure_kind="invalid_identity_response",
                               error="Successful response did not confirm the addressed target/document",
                               mutation_outcome_unknown=method.upper() == "POST")
        return result
