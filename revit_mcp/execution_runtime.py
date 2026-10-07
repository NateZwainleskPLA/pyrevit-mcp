# -*- coding: utf-8 -*-
"""Experimental private serialized ExternalEvent lane. No automatic installation."""
import threading

from .operation_store import OperationError
from .execution_output import safe_text, validate_output_limit


class ExecutionRuntime(object):
    """Adapters validate cached identity, resolve in API context, and execute.

    validate_cached(payload) MUST use primitive snapshots only.
    validate_api(payload, uiapp) MUST revalidate the full identity and resolve a
    still-valid document wrapper immediately before work. execute receives that
    resolved context plus a cancellation_check() callback, and returns
    state/effects/result plus optional unsafe=True.
    The exclusive gate is an integration assertion: it must exclude ALL legacy
    API-context handlers, not just the old script route.
    """
    def __init__(self, store, validate_cached, validate_api, execute,
                 experimental=False, exclusive=False, refresh=None, admission_guard=None):
        self.store = store
        self.validate_cached, self.validate_api = validate_cached, validate_api
        self.execute, self.refresh = execute, refresh
        self.admission_guard = admission_guard
        self.enabled = bool(experimental and exclusive)
        self.lock = threading.RLock()
        self.event = None
        self.command_running = False
        self.pending = False
        self.stopping = False
        self.quarantined = False
        self.diagnostics = []

    def bind_event(self, event):
        """Bind exactly once, in the same valid API context as event creation."""
        with self.lock:
            if self.event is not None or self.stopping:
                raise RuntimeError("ExternalEvent already bound or runtime stopping")
            self.event = event

    def _diagnostic(self, error):
        self.diagnostics.append(safe_text(error)[:2048])
        del self.diagnostics[:-16]

    def _quarantine(self, reason, operation_id=None, document_id=None):
        self.quarantined = True
        adapter = getattr(self, "adapter", None)
        if adapter is not None:
            try:
                adapter.safety.observe({"unsafe": True, "error_type": "RuntimeQuarantine",
                    "cleanup_errors": [{"stage": "runtime", "error": safe_text(reason)[:2048]}]},
                    document_id, operation_id)
            except BaseException as error:
                self._diagnostic(error)

    def submit(self, payload):
        with self.lock:
            if not self.enabled or self.stopping or self.event is None:
                raise OperationError("runtime_disabled", "Experimental exclusive runtime is not enabled", 503)
            self.validate_cached(payload)
            # Deduplication must work even after quarantine or queue saturation.
            operation_id = payload.get("operation_id")
            if operation_id in self.store.records:
                receipt, created = self.store.admit(payload)
            else:
                if self.quarantined:
                    raise OperationError("host_quarantined", "Host needs targeted recovery", 503)
                from .identity import string_types
                if not isinstance(payload.get("code"), string_types) or not payload["code"].strip():
                    raise OperationError("invalid_code", "Nonempty script code is required", 400)
                if payload.get("transaction_mode", "script") not in ("script", "managed"):
                    raise OperationError("invalid_transaction_mode", "Mode must be script or managed", 400)
                if type(payload.get("allow_ui_change", False)) is not bool:
                    raise OperationError("invalid_ui_permission", "UI permission must be boolean", 400)
                if self.admission_guard:
                    self.admission_guard(payload)
                receipt, created = self.store.admit(payload)
            self._schedule()
            return receipt, created

    def _schedule(self):
        if self.pending or self.command_running or self.stopping or not self.store.has_queued():
            return
        try:
            response = self.event.Raise()
            # Autodesk returns Accepted/Pending/Denied/TimedOut. No implicit success.
            if str(response) not in ("Accepted", "Pending"):
                raise RuntimeError("ExternalEvent Raise: {0}".format(response))
            self.pending = True
        except Exception as error:
            # Admission remains recoverable; a duplicate submission can retry wakeup.
            self._diagnostic(error)

    def on_external_event(self, uiapp):
        """One operation per API callback; callback reentry cannot overlap work."""
        with self.lock:
            self.pending = False
            if self.stopping or self.command_running:
                return
            work = self.store.take_next()
            if work is None:
                return
            self.command_running = True
        operation_id, payload = work
        outcome = {"state": "failed", "effects": "none", "result": {}}
        entered = False
        try:
            context = self.validate_api(payload, uiapp)
            if self.quarantined:
                raise OperationError("host_quarantined", "Host needs targeted recovery", 503)
            if self.store.cancellation_requested(operation_id):
                outcome = {"state": "canceled", "effects": "none", "result": {}}
            else:
                entered = True
                outcome = self.execute(payload, context,
                                       lambda: self.store.cancellation_requested(operation_id))
            if outcome.get("unsafe") or outcome.get("cleanup_errors"):
                self._quarantine("Unsafe execution/cleanup", operation_id, payload.get("document_id"))
                outcome["state"], outcome["effects"] = "failed", "unknown"
                outcome.setdefault("result", {})["cleanup_errors"] = outcome.get("cleanup_errors", [])
            if outcome.get("effects") not in ("none", "committed", "rolled_back", "unknown"):
                raise ValueError("Executor must report explicit effects")
        except BaseException as error:
            if entered or getattr(error, "code", None) == "host_unsafe":
                self._quarantine(error, operation_id, payload.get("document_id"))
            outcome = {"state": "failed", "effects": "unknown" if entered else "none",
                       "result": {"error": safe_text(error), "error_type": type(error).__name__}}
        finally:
            try:
                self.store.complete(operation_id, outcome["state"], outcome["effects"], outcome["result"])
                if self.store.durability_failed:
                    self._quarantine("Operation receipt durability uncertain", operation_id, payload.get("document_id"))
            except BaseException as error:
                self._quarantine(error, operation_id, payload.get("document_id"))
                self._diagnostic(error)
                # Invalid/nonprimitive adapter results must not strand running state.
                try:
                    self.store.complete(operation_id, "failed", "unknown",
                                        {"error": "Receipt finalization failed", "cleanup_errors": [safe_text(error)]})
                except BaseException as fallback_error:
                    self._diagnostic(fallback_error)
            finally:
                try:
                    if self.refresh:
                        self.refresh(uiapp)
                except BaseException as error:
                    self._diagnostic(error)
                finally:
                    # Refresh is API work too; release only after it finishes/fails.
                    with self.lock:
                        self.command_running = False
                        self._schedule()

    def stop(self):
        """Expire tokens now; disposal waits for a pending/active callback."""
        with self.lock:
            self.stopping = True
            self.store.expire()
            adapter = getattr(self, "adapter", None)
            if adapter is not None:
                adapter.registry.expire()

    def dispose_in_api_context(self):
        with self.lock:
            if not self.stopping or self.command_running or self.pending:
                raise RuntimeError("Cannot dispose a live, active, or pending callback")
            if self.event is not None:
                self.event.Dispose()
                self.event = None
            unbound = getattr(self, "_unbound_event", None)
            if unbound is not None:
                unbound.Dispose()
                self._unbound_event = None
            self._handler = None
            owner_state = getattr(self, "owner_state", None)
            if owner_state is not None:
                with owner_state["lock"]:
                    if owner_state.get("runtime") is self:
                        owner_state["runtime"] = None


def _create_external_event(runtime):
    """Call ONLY in a valid Revit API context; retain handler with the event."""
    from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

    class Handler(IExternalEventHandler):
        def Execute(self, uiapp):
            runtime.on_external_event(uiapp)

        def GetName(self):
            return "Revit MCP experimental serialized execution"

    handler = Handler()
    event = ExternalEvent.Create(handler)
    try:
        runtime.bind_event(event)
    except BaseException:
        # Retain a created event even when binding fails: disposal/lease release
        # cannot claim success while an owned native callback remains alive.
        runtime._unbound_event = event
        runtime._handler = handler
        raise
    runtime._handler = handler
    return runtime


class NativeExecutionAdapter(object):
    """Wiring to the identity owner and completed execution service.

    All methods named *_api require API context. No wrapper is retained here.
    The injected service contract is execute_payload(data, doc, uidoc,
    cancellation_check=...) -> (structured result, HTTP status).
    """
    def __init__(self, registry, execute_payload, safety=None, output_limit_chars=1000000):
        from .execution_safety import ExecutionSafety
        self.registry = registry
        self.execute_payload = execute_payload
        self.safety = safety or ExecutionSafety()
        validate_output_limit(output_limit_chars)
        self.output_limit_chars = output_limit_chars
        self._host_safety = (False, False)

    def validate_cached(self, payload):
        from .identity import IdentityError
        try:
            self.registry.validate_target(payload.get("instance_id"), payload.get("runtime_id"))
            snapshot = self.registry.snapshot()
            if not snapshot["documents_known"]:
                raise OperationError("documents_unknown", "API-context snapshot is not initialized", 503)
            if not any(doc["document_id"] == payload.get("document_id") for doc in snapshot["documents"]):
                raise OperationError("stale_document", "Document token is not present in the cached snapshot", 409)
            expected = payload.get("expected_revit_version")
            if expected is not None and expected != snapshot["revit_version"]:
                raise OperationError("version_mismatch", "Expected Revit version does not match", 409)
        except IdentityError as error:
            raise OperationError(error.code, safe_text(error), 409)

    def validate_operation_cached(self, payload):
        """Historical receipts require the runtime, never an open document."""
        from .identity import IdentityError
        try:
            self.registry.validate_target(payload.get("instance_id"), payload.get("runtime_id"))
        except IdentityError as error:
            raise OperationError(error.code, safe_text(error), 409)

    def observe_safety_api(self, uiapp):
        """Observe ALL documents, not only the chosen document or owned scopes."""
        try:
            documents = list(uiapp.Application.Documents)
            safe = all(doc.IsValidObject and not doc.IsModifiable for doc in documents)
        except BaseException:
            self._host_safety = (False, False)
            raise
        # HTTP admission sees the last complete observation, never a transient
        # half-reset. Execution still performs its own fresh API validation.
        self._host_safety = (True, safe)
        return safe

    def admit_cached(self, payload):
        self.validate_cached(payload)
        from .execution_safety import MutationBlockedError
        try:
            self.safety.require_safe()
        except MutationBlockedError as error:
            raise OperationError("host_quarantined", safe_text(error), 503)
        known, safe = self._host_safety
        if not known or not safe:
            raise OperationError("host_unsafe", "No known safe API-context host snapshot", 503)

    def validate_api(self, payload, uiapp):
        from .identity import IdentityError
        self.validate_cached(payload)
        if not self.observe_safety_api(uiapp):
            self.safety.observe({"unsafe": True, "error_type": "UnsafeDocumentError", "cleanup_errors": []},
                                payload.get("document_id"), payload.get("operation_id"))
            raise OperationError("host_unsafe", "An open document is invalid or already modifiable", 503)
        uidoc = uiapp.ActiveUIDocument
        active_doc = uidoc.Document if uidoc is not None else None
        try:
            doc = self.registry.resolve_document(payload["instance_id"], payload["runtime_id"],
                payload["document_id"], list(uiapp.Application.Documents), active_doc)
        except IdentityError as error:
            raise OperationError(error.code, safe_text(error), 409)
        # No implicit activation. UI document is usable only with explicit opt-in.
        from .target_registry import same_document
        selected_uidoc = uidoc if (payload.get("allow_ui_change") is True and
                                  active_doc is not None and same_document(doc, active_doc)) else None
        if payload.get("allow_ui_change") and selected_uidoc is None:
            raise OperationError("inactive_document", "UI work requires the selected active document", 409)
        return doc, selected_uidoc, uiapp

    def execute(self, payload, context, cancellation_check):
        doc, uidoc, uiapp = context
        try:
            result, status = self.execute_payload(payload, doc, uidoc, cancellation_check=cancellation_check,
                                                  output_limit_chars=self.output_limit_chars)
        except BaseException as error:
            result, status = {"status": "error", "effects": "unknown", "unsafe": True,
                              "error": safe_text(error), "error_type": type(error).__name__, "cleanup_errors": []}, 500
        # Other-doc raw transaction leaks also quarantine this exclusive host.
        cleanup_errors = list(result.get("cleanup_errors", []))
        try:
            safe = self.observe_safety_api(uiapp)
        except BaseException as error:
            safe = False
            cleanup_errors.append({"stage": "host_postcondition", "error": safe_text(error)})
        unsafe = bool(result.get("unsafe") or not safe or cleanup_errors)
        state = "succeeded" if status == 200 and result.get("status") == "success" else "failed"
        if result.get("error_type") == "ExecutionCanceled":
            state = "canceled"
        elif result.get("error_type") == "OperationCanceledException":
            # Revit's pick/interaction Esc outcome, separate from our cancel flag.
            state = "canceled"
            result["outcome"] = "user_canceled"
        effects = result.get("effects", "unknown")
        if unsafe:
            state, effects = "failed", "unknown"
            result["host_postcondition_unsafe"] = True
        result["unsafe"] = unsafe
        result["cleanup_errors"] = cleanup_errors
        self.safety.observe(result, payload.get("document_id"), payload.get("operation_id"))
        return {"state": state, "effects": effects, "result": result,
                "unsafe": unsafe, "cleanup_errors": cleanup_errors}

    def refresh_api(self, uiapp):
        uidoc = uiapp.ActiveUIDocument
        self.registry.refresh_documents(list(uiapp.Application.Documents),
                                        uidoc.Document if uidoc is not None else None)


def _require_exclusion_receipt(receipt):
    from .routing_policy import ROUTES
    required = set(path for path in ROUTES if not path.startswith("/operations/"))
    required.discard("/get_view/")
    required.update(("/get_view/<view_name>", "/metadata/refresh/"))
    if (not receipt or receipt.get("legacy_api_excluded") is not True or
            receipt.get("private_runtime_reload_guard") is not True or
            required - set(receipt.get("excluded_routes", []))):
        raise ValueError("Enabled private lane requires complete request-only legacy exclusion and reload guard receipt")


def _build_runtime_in_api_context(registry, uiapp, execute_payload, store=None,
                                 experimental=False, exclusive=False, owner_state=None,
                                 output_limit_chars=1000000, exclusion_receipt=None):
    """Construct the adapter without installing routes or modifying startup.

    Caller MUST own an exclusive listener/registration mode: all legacy API
    work excluded, no other private lane bound to this host. Native lifecycle
    evidence is still required before adoption. This factory never enables it
    implicitly, and creates no event until its flags explicitly request one.
    """
    from .operation_store import OperationStore
    # The composition owner retains this SAME map/safety/lock across engine reload.
    # Refuse to synthesize a private guard or competing lane for an enabled host.
    if experimental and exclusive:
        from .target_routing import get_process_safety
        _require_exclusion_receipt(exclusion_receipt)
        retained = get_process_owner_state()
        if owner_state is None:
            owner_state = retained
        if owner_state is not retained or owner_state["safety"] is not get_process_safety():
            raise ValueError("Enabled native lane requires the shared process-retained owner and safety")
        with owner_state["lock"]:
            if owner_state.get("runtime") is not None:
                raise RuntimeError("Another private lane owns this host; stop and safely dispose it first")
    adapter = NativeExecutionAdapter(registry, execute_payload,
                                      safety=owner_state["safety"] if owner_state else None,
                                      output_limit_chars=output_limit_chars)
    adapter.refresh_api(uiapp)
    adapter.observe_safety_api(uiapp)
    runtime_id = registry.snapshot()["runtime_id"]
    store = store or OperationStore(runtime_id)
    if store.runtime_id != runtime_id:
        raise ValueError("Operation store belongs to another runtime")
    runtime = ExecutionRuntime(store, adapter.validate_cached, adapter.validate_api,
                               adapter.execute, experimental, exclusive, adapter.refresh_api,
                               admission_guard=adapter.admit_cached)
    runtime.adapter = adapter
    if experimental and exclusive:
        with owner_state["lock"]:
            if owner_state.get("runtime") is not None:
                raise RuntimeError("Another private lane owns this host; stop and safely dispose it first")
            runtime.owner_state = owner_state
            owner_state["runtime"] = runtime
            try:
                _create_external_event(runtime)
            except BaseException:
                # Retain a lease if partial event creation cannot be safely disposed.
                if runtime.event is None and getattr(runtime, "_unbound_event", None) is None:
                    owner_state["runtime"] = None
                else:
                    runtime.stop()
                raise
    return runtime


def build_runtime_in_api_context(registry, uiapp, execute_payload, store=None,
                                 experimental=False, exclusive=False, owner_state=None,
                                 output_limit_chars=1000000, exclusion_receipt=None):
    """Use routing's real startup guard for the complete private-lane construction.

    Prime retained ownership before taking the guard, so an initially absent
    slot cannot bypass its serialization. Both the complete exclusion receipt
    marker and completed routing guard are required. Request-only exclusions must be established in a
    fresh initialization; never switch an already-serving listener here.
    """
    if experimental and exclusive:
        # Validate composition evidence before allocating native retained state.
        _require_exclusion_receipt(exclusion_receipt)
        from .target_routing import startup_owner_guard
        get_process_owner_state()
        with startup_owner_guard():
            return _build_runtime_in_api_context(registry, uiapp, execute_payload, store,
                experimental, exclusive, owner_state, output_limit_chars, exclusion_receipt)
    return _build_runtime_in_api_context(registry, uiapp, execute_payload, store,
        experimental, exclusive, owner_state, output_limit_chars, exclusion_receipt)


OWNER_SLOT = "revit_mcp.execution.owner.v1"


def get_process_owner_state():
    """API-context composition seam. Native cross-engine retention is unproven."""
    from System import AppDomain
    from .target_routing import get_process_safety
    domain = AppDomain.CurrentDomain
    owner = domain.GetData(OWNER_SLOT)
    if owner is None:
        owner = {"lock": threading.RLock(), "runtime": None, "safety": get_process_safety()}
        domain.SetData(OWNER_SLOT, owner)
    if not isinstance(owner, dict) or "lock" not in owner or "safety" not in owner:
        raise RuntimeError("Retained runtime owner unavailable; cannot create a competing lane")
    return owner
