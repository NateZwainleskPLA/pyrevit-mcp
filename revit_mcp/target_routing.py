# -*- coding: utf-8 -*-
"""Validate synchronous Routes calls in API context, before handler execution."""
import json
from contextlib import contextmanager

from .identity import IdentityError, string_types
from .routing_policy import MUTATION_ROUTES, RoutingPolicyError, check_ui_policy, route_policy
from .target_registry import get_registry, same_document
from .execution_safety import ExecutionSafety, MutationBlockedError

SAFETY_SLOT = "revit_mcp.routing.safety.v1"
PRIVATE_OWNER_SLOT = "revit_mcp.execution.owner.v1"


@contextmanager
def startup_owner_guard():
    """Reject startup while a retained private lane owns this process.

    Do not initialize identity, clear leases or replace unreadable retained state.
    An existing idle owner's lock stays held through registration, preventing its
    factory from acquiring a private lease halfway through synchronous startup.
    Native initialization remains an API-context composition operation.
    """
    try:
        from System import AppDomain
        domain = AppDomain.CurrentDomain
        owner = domain.GetData(PRIVATE_OWNER_SLOT)
    except Exception as error:
        raise RuntimeError("Retained private execution owner is unreadable: " + str(error))
    if owner is None:
        yield
        return
    if not isinstance(owner, dict) or any(key not in owner for key in ("lock", "runtime", "safety")):
        raise RuntimeError("Retained private execution owner is corrupt; startup is blocked")
    lock = owner["lock"]
    if not callable(getattr(lock, "acquire", None)) or not callable(getattr(lock, "release", None)):
        raise RuntimeError("Retained private execution owner lock is unavailable; startup is blocked")
    try:
        acquired = lock.acquire(False)
    except Exception as error:
        raise RuntimeError("Retained private execution owner lock is unreadable: " + str(error))
    if not acquired:
        raise RuntimeError("Retained private execution owner is busy; startup is blocked")
    try:
        if owner["safety"] is None or owner["safety"] is not domain.GetData(SAFETY_SLOT):
            raise RuntimeError("Retained private execution owner has a different safety guard; startup is blocked")
        if not all(callable(getattr(owner["safety"], name, None)) for name in ("require_safe", "observe", "snapshot")):
            raise RuntimeError("Retained private execution safety guard is corrupt; startup is blocked")
        if owner["runtime"] is not None:
            raise RuntimeError("A retained private execution lane owns this process; stop and safely release its lease before startup")
        yield
    finally:
        lock.release()


def get_process_safety():
    """Retain one guard across connector reloads; failure never resets it."""
    from System import AppDomain
    domain = AppDomain.CurrentDomain
    guard = domain.GetData(SAFETY_SLOT)
    if guard is None:
        guard = ExecutionSafety()
        domain.SetData(SAFETY_SLOT, guard)
    if not all(callable(getattr(guard, key, None)) for key in ("require_safe", "observe", "snapshot")):
        raise RuntimeError("Retained execution safety guard is unavailable")
    return guard


def request_payload(request):
    if request.method.upper() == "GET":
        data = dict(request.query_params or {})
        permission = data.get("allow_ui_change", "false")
        if permission not in ("true", "false"):
            raise RoutingPolicyError("invalid_ui_permission", "allow_ui_change must be true or false")
        data["allow_ui_change"] = permission == "true"
    else:
        data = request.data
        if isinstance(data, string_types):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                raise RoutingPolicyError("invalid_request", "Request body must be a JSON object")
        if not isinstance(data, dict):
            raise RoutingPolicyError("invalid_request", "Request body must be a JSON object")
        data = dict(data)
    return data


def validate_api_context(registry, endpoint, payload, uiapp):
    """Resolve the specified document, ignoring any active doc supplied by Routes."""
    actual = registry.validate_target(payload.get("instance_id"), payload.get("runtime_id"))
    requires_document, _, _ = route_policy(endpoint)
    active_uidoc = uiapp.ActiveUIDocument
    active_doc = active_uidoc.Document if active_uidoc is not None else None
    doc = active_doc if endpoint == "/status/" else None
    if requires_document:
        doc = registry.resolve_document(
            actual["instance_id"], actual["runtime_id"], payload.get("document_id"),
            uiapp.Application.Documents, active_doc)
        actual["document_id"] = payload["document_id"]
    is_active = doc is not None and active_doc is not None and same_document(doc, active_doc)
    permission = payload.get("allow_ui_change", False)
    check_ui_policy(endpoint, is_active, permission)
    if endpoint == "/execute_code/" and permission and not is_active:
        raise RoutingPolicyError("inactive_document", "UI execution requires the specified document to be active")
    uidoc = active_uidoc if is_active else None
    if endpoint == "/execute_code/" and not permission:
        uidoc = None
    return doc, uidoc, actual


class TargetedAPI(object):
    """Registration proxy with real uiapp signatures recognized by pyRevit.

    Wrap only legacy synchronous API routes. Discovery and future request-only
    operation routes register directly on the underlying API. admission_guard
    can reject legacy work when an exclusive execution lane is configured.
    """
    def __init__(self, api, registry_getter=get_registry, admission_guard=None, safety=None):
        self.api = api
        self.registry_getter = registry_getter
        self.admission_guard = admission_guard
        self.safety = safety

    def route(self, endpoint, **options):
        route_policy(endpoint)  # A newly added route cannot bypass targeting.

        def decorate(handler):
            code = getattr(handler, "__code__", None) or handler.func_code
            arg_names = code.co_varnames[:code.co_argcount]

            def invoke(uiapp, request, view_name=None):
                from pyrevit import routes
                actual, body, payload = {}, {}, {}
                doc, admitted = None, False
                status, headers = 200, {}
                try:
                    registry = self.registry_getter()
                    snap = registry.snapshot()
                    actual = {k: snap[k] for k in ("instance_id", "runtime_id")}
                    payload = request_payload(request)
                    doc, uidoc, actual = validate_api_context(registry, endpoint, payload, uiapp)
                    if endpoint in MUTATION_ROUTES and self.safety is not None:
                        try:
                            if self.safety.snapshot()["blocked"]:
                                raise MutationBlockedError("Mutations are blocked by the retained safety guard")
                            self.safety.require_safe()
                        except Exception as error:
                            # A process-retained guard can belong to a previous
                            # engine's module: its exception class is different.
                            # Any guard rejection is before handler admission.
                            raise RoutingPolicyError("mutation_blocked", str(error))
                        if doc is not None:
                            try:
                                modifiable = doc.IsModifiable
                            except Exception as error:
                                self.safety.observe({"unsafe": True, "error_type": "document_state_unavailable"},
                                                    actual.get("document_id"), payload.get("operation_id"))
                                raise RoutingPolicyError("document_state_unavailable", str(error))
                            if modifiable:
                                raise RoutingPolicyError("modifiable_document", "Document is already modifiable; mutation was not admitted")
                    if self.admission_guard is not None:
                        self.admission_guard(endpoint, payload, doc)
                    values = dict(uiapp=uiapp, request=request, doc=doc, uidoc=uidoc, view_name=view_name)
                    admitted = True
                    response = handler(**{name: values[name] for name in arg_names})
                    body = getattr(response, "data", response)
                    body = dict(body) if isinstance(body, dict) else {"status": "success", "result": body}
                    status, headers = getattr(response, "status", 200), getattr(response, "headers", {})
                except (IdentityError, RoutingPolicyError, MutationBlockedError) as error:
                    status = 409
                    body = {"status": "error", "error": str(error),
                            "error_code": getattr(error, "code", "mutation_blocked"), "effects": "none"}
                except Exception as error:
                    status = 500
                    body = {"status": "error", "error": str(error), "error_code": "routing_failed"}
                finally:
                    if admitted and self.safety is not None and endpoint in MUTATION_ROUTES:
                        try:
                            closed = endpoint == "/close_document/" and body.get("status") == "success"
                            if doc is not None and not closed and (not doc.IsValidObject or doc.IsModifiable):
                                raise RuntimeError("Document is invalid or still modifiable after execution")
                        except Exception as error:
                            body.update(status="error", unsafe=True, effects="unknown")
                            status = 500
                            body.setdefault("cleanup_errors", []).append({"stage": "routing_postcondition", "error": str(error)})
                        self.safety.observe(body, actual.get("document_id"), payload.get("operation_id"))
                body["actual_target"] = actual
                return routes.make_response(data=body, status=status, headers=headers)

            if "<view_name>" in endpoint:
                def routed(uiapp, request, view_name):
                    return invoke(uiapp, request, view_name)
            else:
                def routed(uiapp, request):
                    return invoke(uiapp, request)
            routed.__name__ = handler.__name__
            routed.__doc__ = handler.__doc__
            return self.api.route(endpoint, **options)(routed)
        return decorate


class DisabledAPI(object):
    """Register HTTP-worker rejections instead of legacy API-context callbacks."""
    def __init__(self, api, registry_getter=get_registry, metadata_only=False):
        self.api, self.registry_getter = api, registry_getter
        self.metadata_only = metadata_only
        self.excluded_routes = set()

    def assert_excluded(self, endpoints):
        missing = set(endpoints) - self.excluded_routes
        if missing:
            raise RuntimeError("Legacy routes were not excluded: " + ", ".join(sorted(missing)))
        return {"legacy_api_excluded": True, "excluded_routes": sorted(self.excluded_routes)}

    def route(self, endpoint, **options):
        if self.metadata_only and endpoint == "/metadata/":
            return self.api.route(endpoint, **options)

        def decorate(handler):
            def reject(request):
                from pyrevit import routes
                snap = self.registry_getter().snapshot()
                return routes.make_response(data={"status": "error", "effects": "none",
                    "error_code": "legacy_api_disabled",
                    "error": "Legacy API routes are excluded from this host's execution mode",
                    "actual_target": {k: snap[k] for k in ("instance_id", "runtime_id")}}, status=503)
            reject.__name__ = handler.__name__
            result = self.api.route(endpoint, **options)(reject)
            self.excluded_routes.add(endpoint)
            return result
        return decorate
