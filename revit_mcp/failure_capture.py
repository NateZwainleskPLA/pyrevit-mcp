# -*- coding: UTF-8 -*-
"""Per-call Revit failure handling, so failure dialogs never block execution.

Application.FailuresProcessing is app-wide, so it also covers raw script
transactions. It is subscribed only for one execute call. Errors roll back
silently; warnings stay in the model and Revit shows its non-modal
mini-warning. No resolution is applied. Every message is recorded.
Compatible with IronPython 2.7 and CPython for offline tests.
"""
import logging

from .execution_output import safe_text

logger = logging.getLogger(__name__)


def _element_id(element_id):
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def _delegate(callback):
    # One explicit delegate, so -= removes exactly what += added.
    try:
        from System import EventHandler
        from Autodesk.Revit.DB.Events import FailuresProcessingEventArgs
    except ImportError:
        return callback
    return EventHandler[FailuresProcessingEventArgs](callback)


class FailureCapture(object):
    def __init__(self, db, application):
        self.db = db
        self.application = application
        self.failures = []
        self.active = False
        self._handler = None

    def __enter__(self):
        if self.application is None:
            return self
        handler = _delegate(self._process)
        try:
            self.application.FailuresProcessing += handler
        except BaseException as error:
            self.failures.append({"action": "capture_unavailable", "error": safe_text(error)})
            return self
        self._handler = handler
        self.active = True
        return self

    def __exit__(self, error_type, error, tb):
        # Inert first: a failed unsubscribe must never act on later user work.
        self.active = False
        if self._handler is not None:
            try:
                self.application.FailuresProcessing -= self._handler
            except BaseException as unsubscribe_error:
                logger.warning("FailuresProcessing unsubscribe failed: %s", safe_text(unsubscribe_error))
            self._handler = None
        return False

    def _process(self, sender, args):
        """Event handler; never raises into Revit."""
        if not self.active:
            return
        try:
            accessor = args.GetFailuresAccessor()
            transaction = safe_text(accessor.GetTransactionName())
            records = []
            for message in accessor.GetFailureMessages():
                severity = message.GetSeverity()
                records.append({
                    "severity": safe_text(severity),
                    "description": safe_text(message.GetDescriptionText()),
                    "element_ids": [_element_id(item) for item in message.GetFailingElementIds()],
                    "transaction": transaction,
                    "action": "kept" if severity == self.db.FailureSeverity.Warning else "rolled_back"})
            if not records:
                return
            self.failures.extend(records)
            options = accessor.GetFailureHandlingOptions()
            if any(record["action"] == "rolled_back" for record in records):
                for record in records:
                    record["action"] = "rolled_back"
                options.SetClearAfterRollback(True)
                accessor.SetFailureHandlingOptions(options)
                args.SetProcessingResult(self.db.FailureProcessingResult.ProceedWithRollBack)
            else:
                options.SetForcedModalHandling(False)
                accessor.SetFailureHandlingOptions(options)
        except BaseException as error:
            self.failures.append({"action": "capture_error", "error": safe_text(error)})
