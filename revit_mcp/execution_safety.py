# -*- coding: UTF-8 -*-
"""Guard primitive for the owner of all host mutation paths.

No registration or global quarantine is performed by this module. Share one
process-retained instance across all mutation entry points and runtime reloads.
"""
import threading


class MutationBlockedError(Exception):
    pass


class ExecutionSafety(object):
    """Latch observed unsafe execution; successful results never clear it.

    Recovery requires an explicit owner workflow or process restart. There is
    intentionally no automatic reset/retry. Caller validates identities before
    recording optional primitive document/operation IDs for diagnostics.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._reasons = []

    def observe(self, result, document_id=None, operation_id=None):
        if result.get("unsafe"):
            reason = {"document_id": document_id, "operation_id": operation_id,
                      "error_type": result.get("error_type"),
                      "cleanup_errors": [dict(item) for item in result.get("cleanup_errors", [])]}
            with self._lock:
                self._reasons.append(reason)
        return self.snapshot()

    def require_safe(self):
        """Call after identity validation, before every host mutation path."""
        with self._lock:
            if self._reasons:
                raise MutationBlockedError("Model changes blocked after observed unsafe execution; targeted recovery is required")

    def snapshot(self):
        with self._lock:
            return {"blocked": bool(self._reasons), "reasons": [
                {"document_id": item["document_id"], "operation_id": item["operation_id"],
                 "error_type": item["error_type"],
                 "cleanup_errors": [dict(error) for error in item["cleanup_errors"]]}
                for item in self._reasons]}
