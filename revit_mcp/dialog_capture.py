# -*- coding: UTF-8 -*-
"""Per-call Revit dialog handling, so known modal dialogs never block execution.

UIApplication.DialogBoxShowing is subscribed only for one execute call. Only
exact dialog IDs proven live are answered; any other dialog is recorded and left
for the user. Records go into the call's failures with the script line that
was running. Compatible with IronPython 2.7 and CPython for offline tests.
"""
import logging
import traceback

from .execution_output import safe_text, script_frame

logger = logging.getLogger(__name__)

# Shown by CopyElements (and other pastes) when the destination has types, often
# materials, with the same names but different settings. Proven in Revit 2025.5
# (25.5.0.57): IDCANCEL is accepted and the copy raises OperationCanceledException.
DUPLICATE_TYPES = "Dialog_Revit_PasteSimilarSymbolsPaste"
IDCANCEL = 2
ANSWERS = {
    DUPLICATE_TYPES: (IDCANCEL, "cancelled", (
        "Revit's Duplicate Types dialog: the destination already has types with the same "
        "names but different settings. It was answered Cancel, so the copy raised "
        "OperationCanceledException.")),
}
DUPLICATE_TYPES_HINT = (
    "A copy was cancelled at {where} because the destination already has types (often "
    "materials) with the same names but different settings. Choose explicitly with "
    "options = DB.CopyPasteOptions(); options.SetDuplicateTypeNamesHandler(handler), "
    "where handler subclasses DB.IDuplicateTypeNamesHandler and OnDuplicateTypeNamesFound(args) "
    "returns DB.DuplicateTypeAction.UseDestinationTypes to keep the destination's types, "
    "or Abort to cancel. args.GetTypeIds() lists the conflicting types in args.Document.")
MAX_MESSAGE_CHARS = 500


def _delegate(callback):
    # One explicit delegate, so -= removes exactly what += added.
    try:
        from System import EventHandler
        from Autodesk.Revit.UI.Events import DialogBoxShowingEventArgs
    except ImportError:
        return callback
    return EventHandler[DialogBoxShowingEventArgs](callback)


def script_location(stack=None):
    """The innermost script frame: the line that called into Revit."""
    frames = traceback.extract_stack() if stack is None else stack
    for filename, line, function, text in reversed(frames):
        if script_frame(filename):
            return {"file": safe_text(filename), "line": line, "function": safe_text(function),
                    "code": safe_text(text or "")}
    return None


def ui_application(uiapp, application):
    """The call's UIApplication, or one built over its Application (operations runtime)."""
    if uiapp is not None or application is None:
        return uiapp
    try:
        from Autodesk.Revit.UI import UIApplication
        return UIApplication(application)
    except Exception as error:
        logger.warning("No UIApplication for dialog capture: %s", safe_text(error))
        return None


class DialogCapture(object):
    def __init__(self, uiapp, failures, stack=None):
        self.uiapp = uiapp
        self.failures = failures
        self.active = False
        self._handler = None
        self._stack = stack

    def __enter__(self):
        if self.uiapp is None:
            return self
        handler = _delegate(self._on_dialog)
        try:
            self.uiapp.DialogBoxShowing += handler
        except BaseException as error:
            self.failures.append({"action": "dialog_capture_unavailable", "error": safe_text(error)})
            return self
        self._handler = handler
        self.active = True
        return self

    def __exit__(self, error_type, error, tb):
        # Inert first: a failed unsubscribe must never answer later user dialogs.
        self.active = False
        if self._handler is not None:
            try:
                self.uiapp.DialogBoxShowing -= self._handler
            except BaseException as unsubscribe_error:
                logger.warning("DialogBoxShowing unsubscribe failed: %s", safe_text(unsubscribe_error))
            self._handler = None
        return False

    def _on_dialog(self, sender, args):
        """Event handler; never raises into Revit and never retries another answer."""
        if not self.active:
            return
        record = {"dialog_id": None, "action": "left_for_user"}
        try:
            record["dialog_id"] = safe_text(args.DialogId)
            try:
                record["location"] = script_location(self._stack() if self._stack else None)
            except BaseException as error:
                record["location_error"] = safe_text(error)
            answer = ANSWERS.get(record["dialog_id"])
            if answer is None:
                message = getattr(args, "Message", None)
                if message:
                    record["message"] = safe_text(message)[:MAX_MESSAGE_CHARS]
            else:
                code, action, description = answer
                record["description"] = description
                record["action"] = action if args.OverrideResult(code) else "answer_rejected"
        except BaseException as error:
            record["action"] = "dialog_capture_error"
            record["error"] = safe_text(error)
        self.failures.append(record)


def dialog_hints(failures):
    """Hints for dialogs this call answered, pointing at the script line."""
    hints = []
    for item in failures:
        if item.get("dialog_id") == DUPLICATE_TYPES and item.get("action") == "cancelled":
            location = item.get("location") or {}
            where = ("{0} line {1}".format(location["file"], location["line"])
                     if location.get("line") else "an unknown line")
            hints.append(DUPLICATE_TYPES_HINT.format(where=where))
    return hints
