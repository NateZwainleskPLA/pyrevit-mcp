"""Per-call FailuresProcessing capture; native behavior was proven live in Revit 2025.5."""
from types import SimpleNamespace

import pytest

from revit_mcp.execution_context import ExecutionContext
from revit_mcp.execution_output import execute_script
from revit_mcp.failure_capture import FailureCapture
from tests.unit.test_execution_context import Document, FakeDB, run
from tests.unit.test_execution_output import execution_route  # noqa: F401  (fixture)
from tools.utils import format_response

OVERLAP = "Highlighted walls overlap."
CANT_SET = "Cant set parameter"


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def fire(self, args):
        for handler in list(self.handlers):
            handler(None, args)


class Message:
    def __init__(self, severity, text, ids=()):
        self.severity, self.text, self.ids = severity, text, ids

    def GetSeverity(self):
        return self.severity

    def GetDescriptionText(self):
        return self.text

    def GetFailingElementIds(self):
        return [SimpleNamespace(Value=value) for value in self.ids]


class Options:
    def __init__(self):
        self.calls = []

    def SetClearAfterRollback(self, value):
        self.calls.append(("clear_after_rollback", value))

    def SetForcedModalHandling(self, value):
        self.calls.append(("forced_modal", value))


class Accessor:
    """No DeleteWarning/ResolveFailure: calling either becomes a capture_error."""
    def __init__(self, transaction, messages):
        self.transaction, self.messages, self.options = transaction, messages, None

    def GetTransactionName(self):
        return self.transaction

    def GetFailureMessages(self):
        return list(self.messages)

    def GetFailureHandlingOptions(self):
        return Options()

    def SetFailureHandlingOptions(self, options):
        self.options = options


class Args:
    def __init__(self, accessor):
        self.accessor, self.result = accessor, "Continue"

    def GetFailuresAccessor(self):
        return self.accessor

    def SetProcessingResult(self, result):
        self.result = result


class FailureDB(FakeDB):
    """Commit runs failure processing first, like Revit; rollback follows its result."""
    FailureSeverity = SimpleNamespace(Warning="Warning", Error="Error", DocumentCorruption="DocumentCorruption")
    FailureProcessingResult = SimpleNamespace(Continue="Continue", ProceedWithRollBack="ProceedWithRollBack")

    def __init__(self, application, *messages):
        FakeDB.__init__(self)
        self.application, self.messages = application, list(messages)

    def _create(self, doc, name, kind):
        scope = FakeDB._create(self, doc, name, kind)
        commit = scope.Commit

        def processed_commit():
            if self.messages:
                args = Args(Accessor(name, self.messages.pop(0)))
                self.application.FailuresProcessing.fire(args)
                if args.result == "ProceedWithRollBack":
                    scope.plan["commit_status"] = "RolledBack"
            return commit()
        scope.Commit = processed_commit
        return scope


def process(*messages):
    application = SimpleNamespace(FailuresProcessing=Event())
    capture = FailureCapture(FailureDB(application), application)
    args = Args(Accessor("Edit", messages))
    with capture:
        application.FailuresProcessing.fire(args)
    return capture, args


def test_warning_is_kept_and_shown_non_modally():
    capture, args = process(Message("Warning", OVERLAP, [2 ** 40, 7]))
    assert capture.failures == [{"severity": "Warning", "description": OVERLAP, "element_ids": [2 ** 40, 7],
                                 "transaction": "Edit", "action": "kept"}]
    assert args.result == "Continue"
    assert args.accessor.options.calls == [("forced_modal", False)]


@pytest.mark.parametrize("severity", ["Error", "DocumentCorruption"])
def test_error_rolls_back_silently_with_its_warnings(severity):
    capture, args = process(Message(severity, CANT_SET, [5]), Message("Warning", OVERLAP, [5, 6]))
    assert [(item["severity"], item["action"]) for item in capture.failures] == [
        (severity, "rolled_back"), ("Warning", "rolled_back")]
    assert args.result == "ProceedWithRollBack"
    assert args.accessor.options.calls == [("clear_after_rollback", True)]


def test_legacy_integer_element_ids():
    application = SimpleNamespace(FailuresProcessing=Event())
    message = Message("Warning", OVERLAP)
    message.GetFailingElementIds = lambda: [SimpleNamespace(IntegerValue=12)]
    capture = FailureCapture(FailureDB(application), application)
    with capture:
        application.FailuresProcessing.fire(Args(Accessor("Edit", [message])))
    assert capture.failures[0]["element_ids"] == [12]


def test_handler_never_raises_into_revit():
    class Broken:
        def GetFailuresAccessor(self):
            raise RuntimeError("accessor unavailable")
    application = SimpleNamespace(FailuresProcessing=Event())
    capture = FailureCapture(FailureDB(application), application)
    with capture:
        application.FailuresProcessing.fire(Broken())
    assert capture.failures == [{"action": "capture_error", "error": "accessor unavailable"}]


def test_subscription_lasts_only_for_the_call_and_stays_inert_if_unsubscribe_fails():
    application = SimpleNamespace(FailuresProcessing=Event())
    capture = FailureCapture(FailureDB(application), application)
    with capture:
        assert len(application.FailuresProcessing.handlers) == 1
    assert application.FailuresProcessing.handlers == []

    class StuckEvent(Event):
        def __isub__(self, handler):
            raise RuntimeError("cannot unsubscribe")
    application.FailuresProcessing = StuckEvent()
    capture = FailureCapture(FailureDB(application), application)
    with capture:
        pass
    args = Args(Accessor("Manual user edit", [Message("Error", CANT_SET)]))
    application.FailuresProcessing.fire(args)
    assert args.result == "Continue" and capture.failures == []


def test_unavailable_event_is_reported_and_execution_continues():
    capture = FailureCapture(FailureDB(None), SimpleNamespace())
    with capture:
        pass
    assert capture.failures[0]["action"] == "capture_unavailable"


def test_owned_commit_rolled_back_by_failure_names_the_failure_text():
    application = SimpleNamespace(FailuresProcessing=Event())
    db, doc = FailureDB(application, [Message("Error", CANT_SET)]), Document()
    with FailureCapture(db, application) as capture:
        context = ExecutionContext(db, doc, "script", failures=capture.failures)
        result = execute_script("with execution.transaction(doc, 'Set'):\n    doc.value = 3",
                                {"doc": doc, "execution": context}, "trial.py", runner=context.run)
        context.close()
    result.update(context.summary())
    assert result["error"] == ("TransactionScopeError: Owned scope did not finish cleanly: Set: "
                               "Revit failure rolled back the commit: " + CANT_SET)
    assert result["cleanup_errors"] == [{"scope": "Set", "stage": "commit",
                                         "error": "Revit failure rolled back the commit: " + CANT_SET}]
    assert result["owned_effects"] == "rolled_back" and not result["unsafe"] and doc.value == 0


def test_rollback_without_reported_failure_keeps_generic_message():
    result, context, db, doc = run("doc.value = 9", "managed", FakeDB({"commit_status": "RolledBack"}))
    assert result["cleanup_errors"][0]["error"] == "Expected Committed, received RolledBack"
    assert "Expected Committed, received RolledBack" in result["error"]


@pytest.mark.parametrize("mode", ["managed", "script"])
def test_execute_payload_reports_failures_and_unsubscribes(execution_route, mode):
    application = SimpleNamespace(FailuresProcessing=Event())
    doc = Document()
    doc.Application = application  # operations runtime path: no uiapp supplied
    execution_route.DB = FailureDB(application, [Message("Error", CANT_SET, [9])])
    code = "doc.value = 5" if mode == "managed" else "with execution.transaction(doc, 'Set'):\n    doc.value = 5"
    result, status = execution_route.execute_payload({"code": code, "transaction_mode": mode}, doc, None)
    assert status == 500 and CANT_SET in result["error"]
    assert result["failures"] == [{"severity": "Error", "description": CANT_SET, "element_ids": [9],
                                   "transaction": "Managed execution" if mode == "managed" else "Set",
                                   "action": "rolled_back"}]
    assert result["owned_effects"] == "rolled_back" and not result["unsafe"] and doc.value == 0
    assert application.FailuresProcessing.handlers == []


def test_execute_payload_raw_transaction_warning_commits_and_is_reported(execution_route):
    application = SimpleNamespace(FailuresProcessing=Event())
    uiapp = SimpleNamespace(Application=application)
    execution_route.DB = FailureDB(application, [Message("Warning", OVERLAP, [1, 2])])
    code = "t = DB.Transaction(doc, 'Raw')\nt.Start()\ndoc.value = 4\nt.Commit()\nt.Dispose()"
    result, status = execution_route.execute_payload({"code": code}, Document(), None, uiapp=uiapp)
    assert status == 200, result
    assert [item["action"] for item in result["failures"]] == ["kept"]
    assert application.FailuresProcessing.handlers == []


def test_success_formatting_shows_failures_only_when_present():
    response = {"status": "success", "output": "done", "effects": "unknown",
                "failures": [{"severity": "Warning", "description": OVERLAP, "action": "kept"}]}
    assert OVERLAP in format_response(response)
    assert "failures" not in format_response(dict(response, failures=[]))
