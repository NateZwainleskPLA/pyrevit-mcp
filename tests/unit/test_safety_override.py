"""User override of the latched safety guard; the TaskDialog itself needs live Revit."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from revit_mcp import dialog_capture, safety_override
from revit_mcp.dialog_capture import DialogCapture
from revit_mcp.execution_safety import ExecutionSafety, MutationBlockedError
from revit_mcp.safety_override import ALLOW, DIALOG_ID, KEEP, request_override
from revit_mcp.target_routing import TargetedAPI
from tests.unit.test_receiver_target_routing import API, host  # noqa: F401  (fixture)
from tools.revit_transport import RevitTransportResult
from tools.utils import compatibility_response

LATCH = {"unsafe": True, "error_type": "TransactionScopeError",
         "cleanup_errors": [{"scope": "Flex", "stage": "rollback", "error": "rollback failure"}]}


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(safety_override, "_state", {"open": False, "last": None})


class Doc(object):
    def __init__(self, title="Model.rvt", modifiable=False, valid=True):
        self.Title, self.IsModifiable, self.IsValidObject = title, modifiable, valid


def uiapp(*documents):
    return SimpleNamespace(Application=SimpleNamespace(Documents=list(documents or [Doc()])))


class Dialog(object):
    """Stands in for the TaskDialog; records what the user would see."""
    def __init__(self, answer=KEEP, during=None):
        self.answer, self.during, self.shown = answer, during, []

    def __call__(self, instruction, content, offer_allow):
        self.shown.append((instruction, content, offer_allow))
        if self.during:
            self.during()
        return self.answer


def ask(safety, dialog, app=None, **options):
    options.setdefault("retained", lambda: ())
    options.setdefault("lane_active", lambda: False)
    options.setdefault("captures", lambda: 0)
    return request_override(app or uiapp(), safety, show=dialog, **options)


def latched():
    safety = ExecutionSafety()
    safety.observe(LATCH, "doc-token", "op-1")
    return safety


def test_clear_keeps_history_and_a_new_unsafe_result_latches_again():
    safety = latched()
    assert safety.clear_by_user(note="Model.rvt: OK", now=0) == 1
    safety.require_safe()
    snapshot = safety.snapshot()
    assert not snapshot["blocked"] and snapshot["reasons"] == []
    [cleared] = snapshot["cleared"]
    assert cleared["cleared_at"] == "1970-01-01T00:00:00Z"
    assert cleared["cleared_by"] == "user_override_dialog" and cleared["error_type"] == "TransactionScopeError"
    assert cleared["clear_note"] == "Model.rvt: OK" and cleared["document_id"] == "doc-token"
    safety.observe({"unsafe": True, "error_type": "UnsafeDocumentError"})
    with pytest.raises(MutationBlockedError):
        safety.require_safe()
    assert len(safety.snapshot()["cleared"]) == 1


def test_not_blocked_shows_no_dialog():
    dialog = Dialog(ALLOW)
    body, status = ask(ExecutionSafety(), dialog)
    assert (status, body["outcome"]) == (200, "not_blocked") and dialog.shown == []


def test_user_allows_after_a_passing_check():
    safety, dialog = latched(), Dialog(ALLOW)
    body, status = ask(safety, dialog)
    assert status == 200 and body["outcome"] == "allowed"
    assert not safety.snapshot()["blocked"]
    [(instruction, content, offer_allow)] = dialog.shown
    assert offer_allow and "asks you to allow model changes again" in instruction
    assert "TransactionScopeError at rollback of 'Flex': rollback failure" in content
    assert "Model.rvt: OK, no open transaction" in content
    assert "cannot see an open transaction group" in content


def test_escape_or_close_keeps_blocked_and_a_quick_retry_does_not_stack_a_dialog():
    safety, dialog = latched(), Dialog(KEEP)
    now = [1000.0]
    body, _ = ask(safety, dialog, clock=lambda: now[0])
    assert body["outcome"] == "kept_blocked" and safety.snapshot()["blocked"]
    now[0] += 10
    again, _ = ask(safety, dialog, clock=lambda: now[0])
    assert again["outcome"] == "kept_blocked" and "not asked again" in again["message"]
    assert len(dialog.shown) == 1
    now[0] += 60
    ask(safety, dialog, clock=lambda: now[0])
    assert len(dialog.shown) == 2


def test_a_request_while_the_dialog_is_open_is_not_shown_a_second_dialog():
    safety, nested = latched(), []
    dialog = Dialog(KEEP, during=lambda: nested.append(ask(safety, Dialog(ALLOW))))
    ask(safety, dialog)
    [(body, status)] = nested
    assert body["outcome"] == "dialog_already_open" and status == 200
    assert safety.snapshot()["blocked"]
    assert safety_override._state["open"] is False


@pytest.mark.parametrize("document", [Doc("Open.rvt", modifiable=True), Doc("Gone.rvt", valid=False)])
def test_a_failed_check_is_shown_prominently_and_the_override_is_refused(document):
    safety, dialog = latched(), Dialog(ALLOW)  # even a forged ALLOW cannot clear it
    body, status = ask(safety, dialog, app=uiapp(Doc(), document))
    assert status == 200 and body["outcome"] == "refused_check_failed"
    assert safety.snapshot()["blocked"]
    [(instruction, content, offer_allow)] = dialog.shown
    assert not offer_allow and instruction.startswith("CHECK FAILED")
    assert document.Title in content and "restart Revit" in content


def test_a_retained_connector_transaction_still_pending_refuses_the_override():
    scope = SimpleNamespace(name="Flex", native=SimpleNamespace(GetStatus=lambda: "Pending"))
    safety, dialog = latched(), Dialog(ALLOW)
    body, _ = ask(safety, dialog, retained=lambda: (SimpleNamespace(active=[scope]),))
    assert body["outcome"] == "refused_check_failed" and "'Flex' is still Pending" in body["message"]
    assert safety.snapshot()["blocked"]


def test_a_state_change_after_the_answer_still_refuses():
    document = Doc()
    safety = latched()
    dialog = Dialog(ALLOW, during=lambda: setattr(document, "IsModifiable", True))
    body, _ = ask(safety, dialog, app=uiapp(document))
    assert body["outcome"] == "refused_check_failed" and safety.snapshot()["blocked"]


def test_a_retained_guard_from_an_older_connector_fails_clearly_without_a_dialog():
    class OldGuard(object):
        """The pre-override class: no clear_by_user."""
        def require_safe(self):
            raise MutationBlockedError("blocked")

        def observe(self, result, document_id=None, operation_id=None):
            return self.snapshot()

        def snapshot(self):
            return {"blocked": True, "reasons": [{"error_type": "UnsafeDocumentError"}]}
    dialog = Dialog(ALLOW)
    body, status = ask(OldGuard(), dialog)
    assert status == 409 and body["error_code"] == "override_unsupported"
    assert "older connector version" in body["error"] and dialog.shown == []


def test_private_lane_quarantine_is_not_cleared():
    dialog = Dialog(ALLOW)
    body, status = ask(latched(), dialog, lane_active=lambda: True)
    assert status == 409 and body["error_code"] == "private_lane_quarantine" and dialog.shown == []


def test_no_dialog_while_an_execute_calls_dialog_capture_is_subscribed():
    events = SimpleNamespace(DialogBoxShowing=EventStub())
    dialog = Dialog(ALLOW)
    with DialogCapture(events, []):
        assert dialog_capture.active_captures() == 1
        body, status = request_override(uiapp(), latched(), show=dialog, retained=lambda: (),
                                        lane_active=lambda: False)
    assert status == 409 and body["error_code"] == "execution_running" and dialog.shown == []
    assert dialog_capture.active_captures() == 0


def test_the_dialog_is_shown_with_no_connector_dialog_capture_armed():
    seen = []
    dialog = Dialog(ALLOW, during=lambda: seen.append(dialog_capture.active_captures()))
    request_override(uiapp(), latched(), show=dialog, retained=lambda: (), lane_active=lambda: False)
    assert seen == [0]


def test_execute_dialog_capture_would_leave_the_override_dialog_for_the_user():
    # Defense in depth: even if a capture were subscribed, it answers exact IDs only.
    assert DIALOG_ID not in dialog_capture.ANSWERS
    failures, args = [], Mock(DialogId=DIALOG_ID, Message="Allow model changes again?")
    events = SimpleNamespace(DialogBoxShowing=EventStub())
    with DialogCapture(events, failures, stack=lambda: []):
        events.DialogBoxShowing.fire(args)
    args.OverrideResult.assert_not_called()
    assert failures[0]["action"] == "left_for_user"


class EventStub(object):
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


def test_after_the_user_allows_a_mutation_passes_every_routing_gate(host, monkeypatch):  # noqa: F811
    reg, a, b, app, ids = host
    a.IsModifiable = b.IsModifiable = False
    safety = latched()
    api = API()
    proxy = TargetedAPI(api, lambda: reg, safety=safety)
    handler = Mock(return_value={"status": "success"})

    @proxy.route("/execute_code/", methods=["POST"])
    def execute(doc, request):
        return handler()
    blocked = execute(app, SimpleNamespace(method="POST", data=dict(ids)))
    assert blocked.status == 409 and blocked.data["error_code"] == "mutation_blocked"

    dialog = Dialog(ALLOW)
    monkeypatch.setattr(safety_override, "show_task_dialog", dialog)
    monkeypatch.setattr(safety_override, "_retained", lambda: ())
    safety_override.register_safety_override_routes(proxy, safety_getter=lambda: safety)
    override_ids = {key: ids[key] for key in ("instance_id", "runtime_id")}
    answered = api.handlers["/safety/override/"](app, SimpleNamespace(method="POST", data=dict(override_ids)))
    assert answered.status == 200 and answered.data["outcome"] == "allowed"
    assert answered.data["actual_target"] == override_ids

    allowed = execute(app, SimpleNamespace(method="POST", data=dict(ids)))
    assert allowed.status == 200 and handler.call_count == 1


def test_an_expired_runtime_is_not_papered_over(host, monkeypatch):  # noqa: F811
    reg, a, b, app, ids = host
    safety, dialog, api = latched(), Dialog(ALLOW), API()
    monkeypatch.setattr(safety_override, "show_task_dialog", dialog)
    safety_override.register_safety_override_routes(TargetedAPI(api, lambda: reg, safety=safety),
                                                    safety_getter=lambda: safety)
    reg.expire()
    response = api.handlers["/safety/override/"](app, SimpleNamespace(
        method="POST", data={key: ids[key] for key in ("instance_id", "runtime_id")}))
    assert response.status == 409 and response.data["error_code"] == "stale_target"
    assert dialog.shown == [] and safety.snapshot()["blocked"]


def _tool(mock_mcp, post):
    from tools.safety_tools import register_safety_tools
    register_safety_tools(mock_mcp, post)
    return mock_mcp.tools["request_safety_override"]


async def test_tool_timeout_says_the_dialog_is_still_open(mock_mcp):
    result = RevitTransportResult(method="POST", url="u", failure_kind="timeout", error="read timeout",
                                  timeout_seconds=300.0)
    tool = _tool(mock_mcp, AsyncMock(return_value=compatibility_response(result)))
    text = await tool(target="t1")
    assert text.startswith("The safety override dialog is still open in Revit")
    assert "retry the blocked call" in text and "Error" not in text


async def test_tool_reports_the_users_answer(mock_mcp):
    body = {"status": "success", "outcome": "allowed", "message": "The user allowed model changes again."}
    result = RevitTransportResult(method="POST", url="u", status_code=200, body=body, json_received=True)
    post = AsyncMock(return_value=compatibility_response(result))
    tool = _tool(mock_mcp, post)
    assert await tool(target="t1") == "The user allowed model changes again.\n\noutcome: allowed"
    assert post.await_args.args[0] == "/safety/override/"
    assert post.await_args.kwargs["timeout"] >= 120


async def test_tool_refusals_are_tool_errors(mock_mcp):
    body = {"status": "error", "outcome": "override_unsupported", "error": "older connector version",
            "error_code": "override_unsupported"}
    result = RevitTransportResult(method="POST", url="u", status_code=409, body=body, json_received=True)
    tool = _tool(mock_mcp, AsyncMock(return_value=compatibility_response(result)))
    with pytest.raises(ToolError, match="older connector version"):
        await tool(target="t1")


def test_tool_docstring_forbids_answering_the_dialog():
    from tools import safety_tools
    import inspect
    source = inspect.getsource(safety_tools)
    for phrase in ("Never answer", "computer-use", "PostCommand", "mutation_blocked"):
        assert phrase in source
