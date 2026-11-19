# -*- coding: UTF-8 -*-
"""User override of the latched safety guard, asked in a Revit TaskDialog.

The route is not a mutation route, so a latched guard does not block it. It
never clears anything by itself: only the human's explicit "Allow" answer in
the dialog calls ExecutionSafety.clear_by_user, and only after a fresh check of
every open document and every retained owned scope. The dialog is shown in API
context, outside any execute call, so dialog_capture is not subscribed and no
connector code answers it. IronPython 2.7; imports under CPython for tests.
"""
import logging
import threading
import time

from .execution_output import safe_text
from .execution_safety import latch_summary

logger = logging.getLogger(__name__)

DIALOG_ID = "RevitMCP_SafetyOverride"
ALLOW, KEEP = "allow", "keep_blocked"
# A queued or repeated request right after a "keep blocked" answer gets that
# answer back instead of a second dialog.
REASK_AFTER_SECONDS = 60
TERMINAL_STATUSES = ("Committed", "RolledBack", "Uninitialized")
CHECK_LIMITS = (u"This check cannot see an open transaction group, files the agent wrote, "
                u"or changes it already committed.")

_lock = threading.Lock()
_state = {"open": False, "last": None}


class OverrideUnavailable(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


def _title(document):
    try:
        return safe_text(document.Title) or u"<untitled>"
    except Exception:
        return u"<unreadable document>"


def recheck(documents, retained=()):
    """Fresh state of every open document and every retained owned scope."""
    rows, problems = [], []
    for document in documents:
        title = _title(document)
        try:
            if not document.IsValidObject:
                rows.append(u"{0}: NOT VALID".format(title))
                problems.append(u"document {0} is no longer valid".format(title))
                continue
            if document.IsModifiable:
                rows.append(u"{0}: STILL MODIFIABLE, a transaction is open".format(title))
                problems.append(u"document {0} still has an open transaction".format(title))
                continue
        except Exception as error:
            rows.append(u"{0}: STATE UNREADABLE".format(title))
            problems.append(u"document {0} could not be read: {1}".format(title, safe_text(error)))
            continue
        rows.append(u"{0}: OK, no open transaction".format(title))
    for context in retained:
        for scope in list(getattr(context, "active", ())):
            name = safe_text(getattr(scope, "name", u"?"))
            try:
                status = safe_text(scope.native.GetStatus())
            except Exception as error:
                status = u"unreadable ({0})".format(safe_text(error))
            if status not in TERMINAL_STATUSES:
                rows.append(u"Connector transaction '{0}': {1}".format(name, status))
                problems.append(u"connector transaction '{0}' is still {1}".format(name, status))
    return {"passed": not problems, "documents": rows, "problems": problems}


def private_lane_active():
    """A private execution lane owns its own quarantine; the override never clears it."""
    try:
        from System import AppDomain
    except ImportError:
        return False  # not inside Revit (offline tests)
    try:
        from .execution_runtime import OWNER_SLOT
        owner = AppDomain.CurrentDomain.GetData(OWNER_SLOT)
        return isinstance(owner, dict) and owner.get("runtime") is not None
    except Exception:
        return True  # unreadable: fail closed


def _active_captures():
    from .dialog_capture import active_captures
    return active_captures()


def _retained():
    from .execution_context import retained_contexts
    return retained_contexts()


def dialog_text(snapshot, check):
    """(main instruction, content) for the dialog; plain words for the user."""
    lines = [u"Revit MCP blocked model changes because {0}.".format(latch_summary(snapshot)), u"",
             u"Fresh check just now:"]
    lines.extend(u"  " + row for row in check["documents"] or [u"(no open documents)"])
    lines.append(u"")
    if check["passed"]:
        instruction = u"An AI agent asks you to allow model changes again"
        lines.append(CHECK_LIMITS)
        lines.append(u"Allow only if the model looks right to you. The agent cannot answer this for you.")
    else:
        instruction = u"CHECK FAILED: model changes stay blocked"
        lines.append(u"Model changes cannot be allowed while " + u"; ".join(check["problems"]) + u".")
        lines.append(u"Save your work in Revit and restart Revit to recover.")
    return instruction, u"\n".join(lines)


def show_task_dialog(instruction, content, offer_allow):
    """Modal TaskDialog in API context. Returns ALLOW only for the explicit Allow link."""
    from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommandLinkId, TaskDialogCommonButtons,
                                   TaskDialogResult)
    dialog = TaskDialog(u"Revit MCP: model changes blocked")
    try:
        dialog.Id = DIALOG_ID  # names it in journals and DialogBoxShowing
    except Exception:
        pass
    dialog.MainInstruction = instruction
    dialog.MainContent = content
    dialog.AllowCancellation = True  # Escape and the close box give Cancel: keep blocked
    if offer_allow:
        dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, u"Keep model changes blocked",
                              u"The agent keeps read-only access.")
        dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink2, u"Allow model changes again",
                              u"The agent can edit, save and run code again.")
        dialog.DefaultButton = TaskDialogResult.CommandLink1
    else:
        dialog.CommonButtons = TaskDialogCommonButtons.Close
        dialog.DefaultButton = TaskDialogResult.Close
    result = dialog.Show()
    return ALLOW if offer_allow and result == TaskDialogResult.CommandLink2 else KEEP


def _reply(outcome, message, status="success", **extra):
    body = {"status": status, "outcome": outcome, "message": message, "effects": "none"}
    body.update(extra)
    return body


def request_override(uiapp, safety, show=None, retained=None, lane_active=None, captures=None, clock=None):
    """Ask the user, in API context, whether model changes may resume. Returns (body, status)."""
    show = show or show_task_dialog
    retained = retained or _retained
    lane_active = lane_active or private_lane_active
    captures = captures or _active_captures
    clock = clock or time.time
    snapshot = safety.snapshot()
    if not snapshot.get("blocked"):
        return _reply("not_blocked", u"Model changes are not blocked. Retry the call."), 200
    try:
        if not callable(getattr(safety, "clear_by_user", None)):
            raise OverrideUnavailable("override_unsupported",
                u"The safety guard in this Revit session comes from an older connector version that "
                u"cannot be cleared by the user. The user must check and save the model in Revit and "
                u"restart Revit.")
        if lane_active():
            raise OverrideUnavailable("private_lane_quarantine",
                u"A private execution lane owns this Revit session; its quarantine is not cleared by "
                u"the override. The user must check and save the model in Revit and restart Revit.")
        if captures():
            raise OverrideUnavailable("execution_running",
                u"An execute call is still running in Revit. Retry when it ends.")
    except OverrideUnavailable as error:
        return _reply(error.code, safe_text(error), status="error", error=safe_text(error),
                      error_code=error.code), 409
    signature = len(snapshot.get("reasons") or [])
    with _lock:
        if _state["open"]:
            return _reply("dialog_already_open",
                u"The override dialog is already open in Revit. Ask the user to answer it, "
                u"then retry the blocked call."), 200
        last = _state["last"]
        if (last and last["answer"] != ALLOW and last["signature"] == signature
                and clock() - last["at"] < REASK_AFTER_SECONDS):
            return _reply(last["outcome"], last["message"] + u" (answered {0:.0f} s ago; not asked again)".format(
                clock() - last["at"])), 200
        _state["open"] = True
    try:
        documents = tuple(uiapp.Application.Documents)
        check = recheck(documents, retained())
        instruction, content = dialog_text(snapshot, check)
        answer = show(instruction, content, check["passed"])
        if not check["passed"]:
            outcome, message = "refused_check_failed", (
                u"Model changes stay blocked: the fresh check failed (" + u"; ".join(check["problems"])
                + u"). The override is refused while a transaction is open. The user must save their "
                u"work in Revit and restart Revit.")
        elif answer == ALLOW:
            # Nothing else runs while the modal dialog is open; confirm anyway.
            again = recheck(tuple(uiapp.Application.Documents), retained())
            if not again["passed"]:
                outcome, message = "refused_check_failed", (
                    u"Model changes stay blocked: the check failed after the user answered ("
                    + u"; ".join(again["problems"]) + u").")
            else:
                cleared = safety.clear_by_user(note=u"; ".join(check["documents"]))
                outcome, message = "allowed", (
                    u"The user allowed model changes again ({0} latch reason{1} cleared). Retry the "
                    u"blocked call. A new unsafe result blocks changes again.").format(
                        cleared, u"" if cleared == 1 else u"s")
        else:
            outcome, message = "kept_blocked", (
                u"The user kept model changes blocked. Continue with read-only tools, or ask the user "
                u"what to do; do not ask again unless they agree.")
    except Exception as error:
        logger.warning("Safety override failed: %s", safe_text(error))
        return _reply("override_failed", u"The override dialog failed: " + safe_text(error)
                      + u". Model changes stay blocked.", status="error", error=safe_text(error),
                      error_code="override_failed"), 500
    finally:
        with _lock:
            _state["open"] = False
    with _lock:
        _state["last"] = {"answer": answer, "outcome": outcome, "message": message,
                          "signature": signature, "at": clock()}
    return _reply(outcome, message, check=check["documents"]), 200


def register_safety_override_routes(api, safety_getter=None):
    """Register through TargetedAPI: identity is validated, the guard is not applied."""
    @api.route("/safety/override/", methods=["POST"])
    def safety_override(uiapp, request):
        from pyrevit import routes
        if safety_getter is None:
            from .target_routing import get_process_safety
            safety = get_process_safety()
        else:
            safety = safety_getter()
        body, status = request_override(uiapp, safety)
        return routes.make_response(data=body, status=status)

    logger.info("Safety override route registered.")
