import sys

import pytest

from tests.unit.test_execution_output import execution_route
from tests.unit.test_execution_context import FakeDB
from tests.unit.test_execution_identity_integration import setup


@pytest.mark.parametrize("code,state,effects,value", [
    ("doc.value = 42", "succeeded", "committed", 42),
    ("doc.value = 42\nprint('partial')\nassert False", "failed", "rolled_back", 0),
])
def test_real_managed_service_effects_and_stream_restoration(execution_route, code, state, effects, value):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, a, b = setup(execution_route.execute_payload)
    a.value = 0
    request.update(transaction_mode="managed", code=code)
    streams = sys.stdout, sys.stderr
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == (state, effects)
    assert a.value == value and not a.IsModifiable
    assert (sys.stdout, sys.stderr) == streams
    assert not engine.command_running


def test_real_pending_failure_cannot_claim_success_or_rollback(execution_route):
    execution_route.DB = FakeDB({"commit_status": "Pending"})
    engine, adapter, reg, uiapp, request, a, b = setup(execution_route.execute_payload)
    a.value = 0
    request.update(transaction_mode="managed", code="doc.value = 4")
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "unknown")
    assert engine.quarantined and adapter.safety.snapshot()["blocked"]
    assert not engine.command_running
    assert not execution_route.DB.created[0].disposed


def test_real_script_commit_then_checkpoint_cancel_keeps_commit(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, a, b = setup(execution_route.execute_payload)
    a.value = 0
    # A callable in the inert document requests cancellation at the scripted point.
    a.request_cancel = lambda: engine.store.cancel("one")
    request["code"] = "with execution.transaction(doc, 'first'):\n    doc.value = 1\ndoc.request_cancel()\nexecution.checkpoint()"
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("canceled", "committed")
    assert receipt["result"]["error_type"] == "ExecutionCanceled"
    assert a.value == 1 and not a.IsModifiable


def test_real_capture_is_bounded_during_execution_without_changing_effects(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, a, b = setup(execution_route.execute_payload)
    adapter.output_limit_chars = 10
    a.value = 0
    request.update(transaction_mode="managed", code="print('x' * 50000)\ndoc.value = 7")
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "succeeded" and receipt["effects"] == "committed"
    assert receipt["result"]["output_truncated"]
    assert len(receipt["result"]["output"]) == 10
    assert a.value == 7
