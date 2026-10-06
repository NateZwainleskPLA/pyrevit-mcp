# -*- coding: utf-8 -*-
"""Experimental private serialized ExternalEvent lane. No automatic installation."""
import threading

from .operation_store import OperationError


class ExecutionRuntime(object):
    """Adapters validate cached identity, resolve in API context, and execute.

    validate_cached(payload) MUST use primitive snapshots only.
    validate_api(payload, uiapp) MUST revalidate the full identity and resolve a
    still-valid document wrapper immediately before work. execute receives that
    resolved context and returns state/effects/result plus optional unsafe=True.
    The exclusive gate is an integration assertion: it must exclude ALL legacy
    API-context handlers, not just the old script route.
    """
    def __init__(self, store, validate_cached, validate_api, execute,
                 experimental=False, exclusive=False, refresh=None):
        self.store = store
        self.validate_cached, self.validate_api = validate_cached, validate_api
        self.execute, self.refresh = execute, refresh
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
        self.diagnostics.append(str(error)[:2048])
        del self.diagnostics[:-16]

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
            entered = True
            outcome = self.execute(payload, context)
            if outcome.get("unsafe") or outcome.get("cleanup_errors"):
                self.quarantined = True
                outcome["state"], outcome["effects"] = "failed", "unknown"
                outcome.setdefault("result", {})["cleanup_errors"] = outcome.get("cleanup_errors", [])
            if outcome.get("effects") not in ("none", "committed", "rolled_back", "unknown"):
                raise ValueError("Executor must report explicit effects")
        except BaseException as error:
            if entered:
                self.quarantined = True
            outcome = {"state": "failed", "effects": "unknown" if entered else "none",
                       "result": {"error": str(error), "error_type": type(error).__name__}}
        finally:
            try:
                self.store.complete(operation_id, outcome["state"], outcome["effects"], outcome["result"])
            except BaseException as error:
                self.quarantined = True
                self._diagnostic(error)
                # Invalid/nonprimitive adapter results must not strand running state.
                try:
                    self.store.complete(operation_id, "failed", "unknown",
                                        {"error": "Receipt finalization failed", "cleanup_errors": [str(error)]})
                except BaseException as fallback_error:
                    self._diagnostic(fallback_error)
            finally:
                # Ownership clears even when receipt serialization or refresh fails.
                with self.lock:
                    self.command_running = False
                try:
                    if self.refresh:
                        self.refresh(uiapp)
                except BaseException as error:
                    self._diagnostic(error)
                with self.lock:
                    self._schedule()

    def stop(self):
        """Expire tokens now; disposal waits for a pending/active callback."""
        with self.lock:
            self.stopping = True
            self.store.expire()

    def dispose_in_api_context(self):
        with self.lock:
            if not self.stopping or self.command_running or self.pending:
                raise RuntimeError("Cannot dispose a live, active, or pending callback")
            if self.event is not None:
                self.event.Dispose()
                self.event = None


def create_external_event(runtime):
    """Call ONLY in a valid Revit API context; retain handler with the event."""
    from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

    class Handler(IExternalEventHandler):
        def Execute(self, uiapp):
            runtime.on_external_event(uiapp)

        def GetName(self):
            return "Revit MCP experimental serialized execution"

    handler = Handler()
    event = ExternalEvent.Create(handler)
    runtime.bind_event(event)
    runtime._handler = handler
    return runtime
