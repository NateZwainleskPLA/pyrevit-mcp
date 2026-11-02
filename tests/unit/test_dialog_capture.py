"""Per-call DialogBoxShowing capture; native behavior was proven live in Revit 2025.5."""
from types import SimpleNamespace

import pytest

from revit_mcp import dialog_capture
from revit_mcp.dialog_capture import DUPLICATE_TYPES, DialogCapture, dialog_hints
from tests.unit.test_execution_context import Document
from tests.unit.test_execution_output import execution_route  # noqa: F401  (fixture)
from tests.unit.test_failure_capture import Event, FailureDB


@pytest.fixture(autouse=True)
def native_frames(monkeypatch):
    """In Revit only .NET sits between the script and the handler; hide this file's fakes."""
    original = dialog_capture.script_frame
    fakes = ("test_dialog_capture.py", "test_failure_capture.py")
    monkeypatch.setattr(dialog_capture, "script_frame",
                        lambda filename: original(filename) and not filename.endswith(fakes))


class DialogArgs:
    def __init__(self, dialog_id, message=None, accept=True):
        self.DialogId, self.accept, self.answers = dialog_id, accept, []
        if message is not None:
            self.Message = message

    def OverrideResult(self, code):
        self.answers.append(code)
        return self.accept


class OperationCanceledException(Exception):
    pass


def copying_document(uiapp):
    """CopyElements stand-in: shows Duplicate Types, then cancels as Revit does on IDCANCEL."""
    doc = Document()

    def copy_elements():
        args = DialogArgs(DUPLICATE_TYPES)
        uiapp.DialogBoxShowing.fire(args)
        if args.answers == [2]:
            raise OperationCanceledException("User cancelled the operation.")
        raise AssertionError("Duplicate Types dialog left open")
    doc.copy_elements = copy_elements
    return doc


def run_script(execution_route, code):
    application = SimpleNamespace(FailuresProcessing=Event())
    uiapp = SimpleNamespace(Application=application, DialogBoxShowing=Event())
    execution_route.DB = FailureDB(application)
    payload = {"code": code, "script_name": "build.py"}
    result, status = execution_route.execute_payload(payload, copying_document(uiapp), None, uiapp=uiapp)
    assert uiapp.DialogBoxShowing.handlers == []
    return result, status


def test_duplicate_types_is_cancelled_with_its_script_line_and_a_hint(execution_route):
    result, status = run_script(execution_route, "print('start')\ndoc.copy_elements()\nprint('unreached')")
    assert status == 500
    assert result["error"] == "OperationCanceledException: User cancelled the operation."
    assert result["script_location"]["line"] == 2
    [record] = result["failures"]
    assert record["dialog_id"] == DUPLICATE_TYPES
    assert record["action"] == "cancelled"
    assert "Duplicate Types" in record["description"]
    assert (record["location"]["file"], record["location"]["line"]) == ("build.py", 2)
    assert "cancelled at build.py line 2" in result["hints"][0]
    assert "SetDuplicateTypeNamesHandler" in result["hints"][0]


def test_a_caught_cancel_is_still_reported(execution_route):
    code = "try:\n    doc.copy_elements()\nexcept Exception as error:\n    print('caught')"
    result, status = run_script(execution_route, code)
    assert status == 200, result
    assert result["output"] == "caught\n"
    assert [(item["action"], item["location"]["line"]) for item in result["failures"]] == [("cancelled", 2)]


def capture_dialog(args, stack=None):
    uiapp = SimpleNamespace(DialogBoxShowing=Event())
    capture = DialogCapture(uiapp, [], stack=stack)
    with capture:
        uiapp.DialogBoxShowing.fire(args)
    return capture


def test_unknown_dialogs_are_recorded_and_left_for_the_user():
    args = DialogArgs("Dialog_Revit_Unknown", message="x" * 900)
    capture = capture_dialog(args, stack=lambda: [("job.py", 7, "<module>", "doc.Thing()")])
    assert args.answers == []
    assert capture.failures == [{"dialog_id": "Dialog_Revit_Unknown", "action": "left_for_user",
                                 "message": "x" * 500, "location": {
                                     "file": "job.py", "line": 7, "function": "<module>", "code": "doc.Thing()"}}]
    assert dialog_hints(capture.failures) == []


def test_a_rejected_answer_is_reported_without_a_hint():
    capture = capture_dialog(DialogArgs(DUPLICATE_TYPES, accept=False))
    assert capture.failures[0]["action"] == "answer_rejected"
    assert dialog_hints(capture.failures) == []


def test_handler_never_raises_into_revit():
    class Broken:
        @property
        def DialogId(self):
            raise RuntimeError("args unavailable")
    capture = capture_dialog(Broken())
    assert capture.failures == [{"dialog_id": None, "action": "dialog_capture_error",
                                 "error": "args unavailable"}]


def test_subscription_lasts_only_for_the_call():
    uiapp = SimpleNamespace(DialogBoxShowing=Event())
    capture = DialogCapture(uiapp, [])
    with capture:
        assert len(uiapp.DialogBoxShowing.handlers) == 1
    assert uiapp.DialogBoxShowing.handlers == []
    args = DialogArgs(DUPLICATE_TYPES)
    capture._on_dialog(None, args)  # a stale delegate Revit still calls stays inert
    assert args.answers == [] and capture.failures == []


def test_unavailable_event_is_reported_and_no_uiapp_is_a_no_op():
    capture = DialogCapture(SimpleNamespace(), [])
    with capture:
        pass
    assert capture.failures[0]["action"] == "dialog_capture_unavailable"
    with DialogCapture(None, []) as quiet:
        pass
    assert quiet.failures == []


def test_location_skips_connector_and_stdlib_frames():
    connector = dialog_capture.__file__
    stdlib = dialog_capture.traceback.__file__
    stack = [("run.py", 3, "<module>", "go()"), (connector, 10, "_on_dialog", ""),
             (stdlib, 5, "extract_stack", "")]
    assert dialog_capture.script_location(stack)["file"] == "run.py"
    assert dialog_capture.script_location([(connector, 1, "f", "")]) is None
