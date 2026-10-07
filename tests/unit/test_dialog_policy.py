"""Offline contract tests; synthetic IDs/buttons establish no native support."""
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from revit_mcp.dialog_policy import (
    DialogPolicy, DialogSubscription, remove_subscription, replace_subscription,
)

TASK = "Autodesk.Revit.UI.Events.TaskDialogShowingEventArgs"
MESSAGE = "Autodesk.Revit.UI.Events.MessageBoxShowingEventArgs"
BUILD = "synthetic-build-25"
DIALOG = "Synthetic_Test_Only"


@pytest.fixture(autouse=True)
def refresh_classes_after_reload_tests():
    # Reload tests deliberately replace class identities, as pyRevit can do.
    import revit_mcp.dialog_policy as module
    global DialogPolicy, DialogSubscription, remove_subscription, replace_subscription
    DialogPolicy = module.DialogPolicy
    DialogSubscription = module.DialogSubscription
    remove_subscription = module.remove_subscription
    replace_subscription = module.replace_subscription


def catalog():
    return {DIALOG: {"event_type": TASK, "revit_builds": [BUILD], "actions": {
        "continue_fixture": {"result_code": 1002, "description": "Synthetic continue",
                             "evidence": "Synthetic fixture definition, not Revit"}}}}


def policy(enabled=True):
    return DialogPolicy(catalog(), {DIALOG: "continue_fixture"}, enabled=enabled)


class Event:
    def __init__(self, dialog_id=DIALOG, event_type=TASK, result=True, error=None):
        self.DialogId = dialog_id
        self.Message = "Could not find Desktop Connector / unresolved references"
        self.HelpId = DIALOG
        self.event_type = event_type
        self.result = result
        self.error = error
        self.calls = []

    def GetType(self):
        return SimpleNamespace(FullName=self.event_type)

    def OverrideResult(self, code):
        self.calls.append(code)
        if self.error:
            raise self.error
        return self.result


class Host:
    def __init__(self):
        self.handlers = []
        self.detach_error = None
        self.add_count = 0

    def attach(self, handler):
        self.handlers.append(handler)
        self.add_count += 1

    def detach(self, handler):
        if self.detach_error:
            raise self.detach_error
        self.handlers.remove(handler)

    def fire(self, event):
        for handler in list(self.handlers):
            handler(self, event)


def subscribe(host, state=None, selected=None, build=BUILD, limit=128):
    return replace_subscription({} if state is None else state,
                                DialogPolicy() if selected is None else selected,
                                build, host.attach, host.detach, lambda f: f, limit)


def test_default_and_import_reload_leave_every_dialog_alone():
    host = Host()
    sub = subscribe(host)
    import revit_mcp.dialog_policy as module
    importlib.reload(module)
    event = Event()
    host.fire(event)
    assert event.calls == []
    assert sub.snapshot()["receipts"][0]["reason"] == "policy_disabled"
    assert len(host.handlers) == 1


@pytest.mark.parametrize("dialog_id,event_type,build,reason", [
    (DIALOG.lower(), TASK, BUILD, "unsupported_dialog"),
    (DIALOG + " suffix", TASK, BUILD, "unsupported_dialog"),
    ("prefix " + DIALOG, TASK, BUILD, "unsupported_dialog"),
    ("could not find", TASK, BUILD, "unsupported_dialog"),
    ("", TASK, BUILD, "unsupported_dialog"),
    (DIALOG, MESSAGE, BUILD, "event_type_mismatch"),
    (DIALOG, TASK, BUILD + "-patch", "unverified_revit_build"),
])
def test_only_exact_verified_identity_can_override(dialog_id, event_type, build, reason):
    host = Host()
    sub = subscribe(host, selected=policy(), build=build)
    event = Event(dialog_id, event_type)
    host.fire(event)
    assert event.calls == []
    assert sub.snapshot()["receipts"][0]["reason"] == reason


def test_enabled_without_selected_action_still_observes():
    host = Host()
    sub = subscribe(host, selected=DialogPolicy(catalog(), enabled=True))
    event = Event()
    host.fire(event)
    assert event.calls == []
    assert sub.snapshot()["receipts"][0]["reason"] == "action_not_selected"


@pytest.mark.parametrize("result,error,reason,accepted", [
    (True, None, "override_accepted", True),
    (False, None, "override_rejected", False),
    (None, RuntimeError("invalid result"), "override_error", None),
])
def test_receipt_reports_actual_override_without_fallback(result, error, reason, accepted):
    host = Host()
    sub = subscribe(host, selected=policy())
    event = Event(result=result, error=error)
    host.fire(event)
    assert event.calls == [1002]
    receipt = sub.snapshot()["receipts"][0]
    assert receipt["reason"] == reason
    assert receipt["override_attempted"] is True
    assert receipt["override_accepted"] is accepted
    assert receipt["action"]["evidence"].startswith("Synthetic")
    assert receipt["dialog_id"] == DIALOG
    assert receipt["event_type"] == TASK
    assert receipt["revit_build"] == BUILD
    json.dumps(receipt)


def test_configuration_and_receipts_are_snapshots():
    source = catalog()
    selection = {DIALOG: "continue_fixture"}
    selected = DialogPolicy(source, selection, enabled=True)
    source[DIALOG]["actions"]["continue_fixture"]["result_code"] = 1
    selection.clear()
    _, decision = selected.decide(DIALOG, TASK, BUILD)
    decision["result_code"] = 2
    host = Host()
    sub = subscribe(host, selected=selected)
    event = Event()
    host.fire(event)
    assert event.calls == [1002]
    sub.snapshot()["receipts"][0]["action"]["result_code"] = 1
    assert sub.snapshot()["receipts"][0]["action"]["result_code"] == 1002


@pytest.mark.parametrize("code", [True, False, 0, "1002", 1.5, 2147483648, -2147483649])
def test_invalid_result_codes_are_rejected(code):
    source = catalog()
    source[DIALOG]["actions"]["continue_fixture"]["result_code"] = code
    with pytest.raises(ValueError, match="Int32"):
        DialogPolicy(source)


@pytest.mark.parametrize("field,value", [
    ("event_type", "TaskDialog"), ("revit_builds", []),
    ("revit_builds", "2025"), ("revit_builds", [""]), ("actions", {}),
])
def test_catalog_requires_documented_types_builds_actions(field, value):
    source = catalog()
    source[DIALOG][field] = value
    with pytest.raises(ValueError):
        DialogPolicy(source)


@pytest.mark.parametrize("field", ["evidence", "description"])
def test_action_requires_semantics_and_evidence(field):
    source = catalog()
    source[DIALOG]["actions"]["continue_fixture"][field] = ""
    with pytest.raises(ValueError):
        DialogPolicy(source)


@pytest.mark.parametrize("responses", [
    {"Unknown": "continue_fixture"}, {DIALOG: "OK"}, {DIALOG: 1002},
])
def test_arbitrary_actions_and_unknown_ids_cannot_be_selected(responses):
    with pytest.raises(ValueError):
        DialogPolicy(catalog(), responses, enabled=True)


@pytest.mark.parametrize("enabled", [1, "true", None])
def test_opt_in_must_be_boolean(enabled):
    with pytest.raises(ValueError):
        DialogPolicy(catalog(), enabled=enabled)


def test_reinitialization_detaches_exact_old_delegate_even_across_module_reload():
    host, state = Host(), {}
    first = subscribe(host, state, selected=policy())
    first.start()
    assert host.add_count == 1
    old_delegate = host.handlers[0]
    import revit_mcp.dialog_policy as module
    importlib.reload(module)
    second = module.replace_subscription(state, module.DialogPolicy(), BUILD,
                                         host.attach, host.detach, lambda f: f)
    assert len(host.handlers) == 1
    assert host.handlers[0] is not old_delegate
    event = Event()
    old_delegate(host, event)  # stale callback cannot override after replacement
    host.fire(event)
    assert event.calls == []
    assert first.snapshot()["active"] is False
    second.start()
    assert host.add_count == 2
    module.remove_subscription(state)
    module.remove_subscription(state)
    assert host.handlers == []
    assert state == {}


def test_failed_detach_disables_old_handler_and_blocks_replacement():
    host, state = Host(), {}
    first = subscribe(host, state, selected=policy())
    host.detach_error = RuntimeError("cannot unsubscribe")
    with pytest.raises(RuntimeError, match="cannot unsubscribe"):
        subscribe(host, state, selected=policy())
    assert len(host.handlers) == 1
    assert host.add_count == 1
    event = Event()
    host.fire(event)
    assert event.calls == []
    assert first.snapshot()["attached"] is True
    assert first.snapshot()["active"] is False
    with pytest.raises(RuntimeError):
        remove_subscription(state)
    assert state
    host.detach_error = None
    remove_subscription(state)
    assert state == {}


def test_invalid_replacement_does_not_touch_existing_subscription():
    host, state = Host(), {}
    first = subscribe(host, state, selected=policy())
    with pytest.raises(ValueError):
        subscribe(host, state, selected=policy(), limit=0)
    assert first.snapshot()["active"] is True
    assert len(host.handlers) == 1


def test_observation_error_is_receipted_and_never_overridden():
    host = Host()
    sub = subscribe(host, selected=policy())
    event = Event(dialog_id=object())
    host.fire(event)
    receipt = sub.snapshot()["receipts"][0]
    assert receipt["reason"] == "observation_error"
    assert receipt["dialog_id"] is None
    assert receipt["override_attempted"] is False
    assert event.calls == []
    json.dumps(receipt)


def test_receipt_retention_is_bounded_and_reports_loss():
    host = Host()
    sub = subscribe(host, limit=2)
    for number in range(5):
        host.fire(Event(str(number)))
    snapshot = sub.snapshot()
    assert snapshot["dropped_receipts"] == 3
    assert [r["sequence"] for r in snapshot["receipts"]] == [4, 5]
    assert [r["dialog_id"] for r in snapshot["receipts"]] == ["3", "4"]


def test_receipt_clock_failure_does_not_escape_native_callback():
    host = Host()

    def broken_clock():
        raise RuntimeError("clock failed")

    sub = DialogSubscription(DialogPolicy(), BUILD, host.attach, host.detach,
                             lambda f: f, clock=broken_clock)
    sub.start()
    host.fire(Event())
    assert sub.snapshot()["dropped_receipts"] == 1
    assert sub.current_sequence() == 1


def test_diagnostics_expose_policy_opt_in_and_selections_without_events():
    host = Host()
    sub = subscribe(host, selected=policy())
    configured = sub.snapshot()["policy"]
    assert configured["enabled"] is True
    assert configured["responses"] == {DIALOG: "continue_fixture"}
    configured["catalog"].clear()
    assert sub.snapshot()["policy"]["catalog"]


def test_native_adapter_uses_loaded_build_and_retains_actual_delegate(monkeypatch):
    import revit_mcp.dialog_policy as module

    class NativeEvent:
        def __init__(self):
            self.handlers = []

        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

        def __isub__(self, handler):
            self.handlers.remove(handler)
            return self

    class Delegate:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, sender, event):
            self.callback(sender, event)

    class EventHandlerFactory:
        def __getitem__(self, event_type):
            assert event_type is Event
            return Delegate

    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(EventHandler=EventHandlerFactory()))
    monkeypatch.setitem(sys.modules, "Autodesk.Revit.UI.Events",
                        SimpleNamespace(DialogBoxShowingEventArgs=Event))
    uiapp = SimpleNamespace(Application=SimpleNamespace(VersionBuild=BUILD),
                            DialogBoxShowing=NativeEvent())
    state = {}
    sub = module.initialize_for_uiapplication(uiapp, state, policy())
    delegate = uiapp.DialogBoxShowing.handlers[0]
    event = Event()
    delegate(uiapp, event)
    assert event.calls == [1002]
    assert sub.snapshot()["receipts"][0]["revit_build"] == BUILD
    assert isinstance(delegate, Delegate)
    module.remove_subscription(state)
    assert uiapp.DialogBoxShowing.handlers == []


def test_attachment_failure_is_visible_and_retains_removable_state():
    host, state = Host(), {}

    def cannot_attach(handler):
        raise RuntimeError("cannot subscribe")

    with pytest.raises(RuntimeError, match="cannot subscribe"):
        replace_subscription(state, DialogPolicy(), BUILD, cannot_attach,
                             host.detach, lambda callback: callback)
    assert state
    assert host.handlers == []
    sub = subscribe(host, state)
    assert sub.snapshot()["active"] is True
    assert len(host.handlers) == 1
    remove_subscription(state)
    assert not state


def test_policy_swaps_keep_delegate_and_all_receipt_ordinals():
    host = Host()
    sub = subscribe(host)
    delegate = host.handlers[0]
    idle = sub._policy
    selected = policy()
    assert sub.current_sequence() == 0
    host.fire(Event())
    assert sub.set_policy(selected, "caller-supplied-scope") is idle
    host.fire(Event())
    assert sub.set_policy(idle) is selected
    host.fire(Event())
    assert host.add_count == 1
    assert host.handlers == [delegate]
    snapshot = sub.snapshot()
    receipts = snapshot["receipts"]
    assert [r["sequence"] for r in receipts] == [1, 2, 3]
    assert [r["policy_generation"] for r in receipts] == [0, 1, 2]
    assert [r["scope_token"] for r in receipts] == [None, "caller-supplied-scope", None]
    assert [r["reason"] for r in receipts] == ["policy_disabled", "override_accepted", "policy_disabled"]
    assert sub.current_sequence() == snapshot["current_sequence"] == 3
    json.dumps(snapshot)


def test_scoped_policy_restores_prior_policy_and_token_on_exception():
    host = Host()
    sub = subscribe(host)
    original = policy(enabled=False)
    sub.set_policy(original, "outer-token")
    with pytest.raises(RuntimeError, match="script failed"):
        with sub.scoped_policy(policy(), "active-token") as active:
            assert active is sub
            host.fire(Event())
            raise RuntimeError("script failed")
    assert sub.snapshot()["policy"] == original.snapshot()
    assert sub.snapshot()["scope_token"] == "outer-token"
    assert sub.snapshot()["policy_generation"] == 3
    host.fire(Event())
    assert sub.snapshot()["receipts"][-1]["reason"] == "policy_disabled"
    assert host.add_count == 1
    assert len(host.handlers) == 1


def test_nested_scopes_restore_in_order_without_resetting_sequence():
    host = Host()
    sub = subscribe(host)
    with sub.scoped_policy(policy(), "outer"):
        host.fire(Event())
        with sub.scoped_policy(DialogPolicy(), "inner"):
            host.fire(Event())
        host.fire(Event())
    host.fire(Event())
    receipts = sub.snapshot()["receipts"]
    assert [r["sequence"] for r in receipts] == [1, 2, 3, 4]
    assert [r["policy_generation"] for r in receipts] == [1, 2, 3, 4]
    assert [r["scope_token"] for r in receipts] == ["outer", "inner", "outer", None]
    assert [r["override_attempted"] for r in receipts] == [True, False, True, False]


@pytest.mark.parametrize("invalid", [None, object(), {}, "policy"])
def test_swap_rejects_non_policy_without_changing_state(invalid):
    host = Host()
    sub = subscribe(host)
    before = sub.snapshot()
    with pytest.raises(ValueError, match="DialogPolicy"):
        sub.set_policy(invalid)
    with pytest.raises(ValueError, match="DialogPolicy"):
        with sub.scoped_policy(invalid):
            pytest.fail("invalid scope entered")
    assert sub.snapshot() == before
    assert host.add_count == 1


@pytest.mark.parametrize("invalid", [object(), {}, 1, True, ""])
def test_scope_token_rejects_wrappers_and_non_string_data(invalid):
    host = Host()
    sub = subscribe(host)
    before = sub.snapshot()
    with pytest.raises(ValueError, match="scope_token"):
        sub.set_policy(policy(), invalid)
    assert sub.snapshot() == before


@pytest.mark.parametrize("state", ["not_started", "closed", "detach_failed"])
def test_swapping_never_reactivates_an_inactive_or_closed_subscription(state):
    host = Host()
    sub = DialogSubscription(DialogPolicy(), BUILD, host.attach, host.detach, lambda f: f)
    if state != "not_started":
        sub.start()
        if state == "detach_failed":
            host.detach_error = RuntimeError("cannot detach")
            with pytest.raises(RuntimeError):
                sub.close()
        else:
            sub.close()
    lifecycle_before = (sub.snapshot()["attached"], sub.snapshot()["active"], host.add_count)
    sub.set_policy(policy(), "inactive-scope")
    event = Event()
    sub._handler(host, event)  # also checks a stale delegate after detach
    assert event.calls == []
    assert sub.snapshot()["receipts"][-1]["reason"] == "subscription_inactive"
    assert lifecycle_before == (sub.snapshot()["attached"], sub.snapshot()["active"], host.add_count)


def test_scope_restoration_after_close_does_not_mask_error_or_reactivate():
    host = Host()
    sub = subscribe(host)
    with pytest.raises(RuntimeError, match="script failed"):
        with sub.scoped_policy(policy(), "operation"):
            sub.close()
            raise RuntimeError("script failed")
    snapshot = sub.snapshot()
    assert snapshot["policy"]["enabled"] is False
    assert snapshot["policy_generation"] == 2
    assert snapshot["scope_token"] is None
    assert snapshot["active"] is False
    assert snapshot["attached"] is False


def test_retained_subscription_restores_policies_across_multiple_module_reloads():
    import revit_mcp.dialog_policy as module

    host = Host()
    sub = subscribe(host)
    original = sub._policy
    delegate = host.handlers[0]
    importlib.reload(module)
    middle = module.DialogPolicy()
    with sub.scoped_policy(middle, "middle"):
        importlib.reload(module)
        with sub.scoped_policy(module.DialogPolicy(), "newest"):
            host.fire(Event())
        assert sub._policy is middle
        host.fire(Event())
    assert sub._policy is original
    assert host.handlers == [delegate]
    assert host.add_count == 1
    assert sub.snapshot()["policy_generation"] == 4
    assert sub.current_sequence() == 2


@pytest.mark.parametrize("event_type", [TASK, MESSAGE])
def test_empty_id_dialog_is_observation_only_even_under_enabled_policy(event_type):
    host = Host()
    sub = subscribe(host, selected=policy())
    event = Event(dialog_id="", event_type=event_type)
    host.fire(event)
    receipt = sub.snapshot()["receipts"][0]
    assert receipt["dialog_id"] == ""
    assert receipt["reason"] == "unsupported_dialog"
    assert receipt["override_attempted"] is False
    assert event.calls == []


def test_message_box_type_is_not_an_exact_id_supported_catalog_type():
    source = catalog()
    source[DIALOG]["event_type"] = MESSAGE
    with pytest.raises(ValueError, match="unsupported dialog event type"):
        DialogPolicy(source)


def test_out_of_order_scope_exits_fail_closed_and_preserve_native_handler():
    host = Host()
    sub = subscribe(host)
    delegate = host.handlers[0]
    first = sub.scoped_policy(policy(), "op-A")
    second = sub.scoped_policy(policy(), "op-B")
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    assert sub.snapshot()["policy"]["enabled"] is False
    second.__exit__(None, None, None)
    event = Event()
    host.fire(event)
    snapshot = sub.snapshot()
    assert snapshot["scope_conflicts"] == 2
    assert snapshot["policy"]["enabled"] is False
    assert snapshot["scope_token"] is None
    assert snapshot["receipts"][-1]["reason"] == "policy_disabled"
    assert event.calls == []
    assert host.handlers == [delegate]
    assert host.add_count == 1


def test_conflicting_scope_exit_does_not_mask_script_exception():
    host = Host()
    sub = subscribe(host)
    late = sub.scoped_policy(policy(), "late-scope")
    with pytest.raises(ValueError, match="script error"):
        with sub.scoped_policy(policy(), "first-scope"):
            late.__enter__()
            raise ValueError("script error")
    assert sub.snapshot()["scope_conflicts"] == 1
    late.__exit__(None, None, None)
    assert sub.snapshot()["scope_conflicts"] == 2
    assert sub.snapshot()["policy"]["enabled"] is False
    event = Event()
    host.fire(event)
    assert event.calls == []


def test_unrelated_policy_swap_inside_scope_cannot_be_restored_as_finished_work():
    host = Host()
    sub = subscribe(host, selected=policy())
    with sub.scoped_policy(policy(), "active"):
        sub.set_policy(policy(), "unrelated")
    snapshot = sub.snapshot()
    assert snapshot["scope_conflicts"] == 1
    assert snapshot["policy"]["enabled"] is False
    assert snapshot["scope_token"] is None


def test_nested_scope_cannot_hide_prior_unrelated_policy_swap():
    host = Host()
    sub = subscribe(host, selected=policy())
    with sub.scoped_policy(policy(), "outer"):
        sub.set_policy(policy(), "unrelated")
        with sub.scoped_policy(policy(), "inner"):
            host.fire(Event())
    snapshot = sub.snapshot()
    assert snapshot["scope_conflicts"] == 1
    assert snapshot["policy"]["enabled"] is False
    assert snapshot["scope_token"] is None


def test_three_ordered_nested_scopes_remain_valid():
    host = Host()
    sub = subscribe(host)
    with sub.scoped_policy(policy(), "outer"):
        with sub.scoped_policy(policy(), "middle"):
            with sub.scoped_policy(policy(), "inner"):
                host.fire(Event())
            assert sub.snapshot()["scope_token"] == "middle"
        assert sub.snapshot()["scope_token"] == "outer"
    snapshot = sub.snapshot()
    assert snapshot["scope_conflicts"] == 0
    assert snapshot["policy_generation"] == 6
    assert snapshot["policy"]["enabled"] is False
