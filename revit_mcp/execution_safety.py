# -*- coding: UTF-8 -*-
"""Guard primitive for the owner of all host mutation paths.

No registration or global quarantine is performed by this module. Share one
process-retained instance across all mutation entry points and runtime reloads.
Only the user override (safety_override.py) clears it; see clear_by_user.
"""
import threading
import time


class MutationBlockedError(Exception):
    pass


OVERRIDE_TOOL = "request_safety_override"
RECOVERY_STEP = (u"Recovery: call request_safety_override with this target, and tell the user that a "
                 u"dialog is waiting for them in Revit. It re-checks every open document and lets the "
                 u"user allow model changes again. Never answer that dialog yourself. If the user keeps "
                 u"changes blocked or the check fails, the fallback is that the user checks and saves the "
                 u"model in Revit and restarts Revit; reloading pyRevit or the connector does not clear this.")
READ_ONLY_NOTE = (u"Until then, read-only tools still run (get_revit_model_info, list_revit_views, "
                  u"get_revit_view, get_current_view_info, get_current_view_elements, list_levels, "
                  u"list_families, list_family_categories, list_category_parameters). "
                  u"Code execution always counts as a model change, even for a script that only reads.")
MAX_REASON_CHARS = 200


def _text(value):
    try:
        return u"{0}".format(value)
    except Exception:
        return repr(value)


def _reason_text(reason):
    """One latch reason from primitive snapshot fields; tolerant of older guards."""
    reason = reason if isinstance(reason, dict) else {}
    errors = [item for item in (reason.get("cleanup_errors") or []) if isinstance(item, dict)]
    text = _text(reason.get("error_type") or "unsafe execution")
    if errors:
        first = errors[0]
        detail = _text(first.get("error", ""))
        if len(detail) > MAX_REASON_CHARS:
            detail = detail[:MAX_REASON_CHARS - 3] + u"..."
        where = first.get("stage") or u"cleanup"
        if first.get("scope"):
            where = u"{0} of '{1}'".format(where, _text(first["scope"]))
        text += u" at {0}: {1}".format(where, detail)
    ids = []
    if reason.get("operation_id"):
        ids.append(u"operation {0}".format(_text(reason["operation_id"])))
    if reason.get("document_id"):
        ids.append(u"document {0}".format(_text(reason["document_id"])))
    if ids:
        text += u" ({0})".format(u", ".join(ids))
    return text


def latch_summary(snapshot):
    """Why the guard latched, in one sentence fragment, from a primitive snapshot."""
    reasons = list((snapshot or {}).get("reasons") or [])
    if not reasons:
        return u"an earlier call left Revit in an unverified state"
    why = u"an earlier call left Revit in an unverified state: " + _reason_text(reasons[0])
    if len(reasons) > 1:
        why += u" ({0} more latch reasons)".format(len(reasons) - 1)
    return why.rstrip(u".")


def blocked_message(snapshot):
    """Why the guard latched and the recovery step, from a primitive snapshot."""
    return u"Model changes are blocked because {0}. {1} {2}".format(latch_summary(snapshot), RECOVERY_STEP,
                                                                    READ_ONLY_NOTE)


MAX_CLEARED_HISTORY = 50


def _copy_reason(item):
    copied = {"document_id": item["document_id"], "operation_id": item["operation_id"],
              "error_type": item["error_type"],
              "cleanup_errors": [dict(error) for error in item["cleanup_errors"]]}
    for key in ("cleared_at", "cleared_by", "clear_note"):
        if key in item:
            copied[key] = item[key]
    return copied


class ExecutionSafety(object):
    """Latch observed unsafe execution; successful results never clear it.

    There is no automatic reset or retry. The one recovery workflow is the user
    override: the human at the Revit window answers a dialog shown in API
    context, after a fresh re-check of every open document, and only that path
    calls clear_by_user. A process restart also starts clean. Cleared reasons
    stay in snapshot()["cleared"] for diagnostics, and any later unsafe
    observation latches again. Caller validates identities before recording
    optional primitive document/operation IDs for diagnostics.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._reasons = []
        self._cleared = []

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
                raise MutationBlockedError(blocked_message(self.snapshot()))

    def clear_by_user(self, note=None, now=None):
        """The user allowed model changes again in the override dialog.

        Call ONLY from safety_override after the user's explicit answer. Moves
        the current reasons to the cleared history with when and by whom.
        Returns how many reasons were cleared.
        """
        stamp = time.time() if now is None else now
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))
        with self._lock:
            cleared = len(self._reasons)
            for item in self._reasons:
                entry = _copy_reason(item)
                entry.update(cleared_at=when, cleared_by="user_override_dialog")
                if note:
                    entry["clear_note"] = note
                self._cleared.append(entry)
            del self._cleared[:-MAX_CLEARED_HISTORY]
            self._reasons = []
            return cleared

    def snapshot(self):
        with self._lock:
            return {"blocked": bool(self._reasons),
                    "reasons": [_copy_reason(item) for item in self._reasons],
                    "cleared": [_copy_reason(item) for item in getattr(self, "_cleared", [])]}
