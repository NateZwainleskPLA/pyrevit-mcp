import sys
from types import SimpleNamespace

import pytest

from tests.unit.test_execution_output import execution_route
from tests.unit.test_execution_context import FakeDB
from tests.unit.test_execution_identity_integration import setup
from tests.unit.test_execution_document_postconditions import AliasDocument


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


@pytest.mark.parametrize("rollback,effects", [(False, "committed"), (True, "unknown")])
def test_settled_closed_helper_does_not_quarantine_operations(execution_route, rollback, effects):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, selected, helper = setup(execution_route.execute_payload)
    selected.value = helper.value = 0
    selected.EditFamily = lambda: helper
    loaded_into = []
    helper.LoadFamily = lambda doc: loaded_into.append(doc)

    def close(save):
        helper.IsValidObject = False
        uiapp.Application.Documents.remove(helper)

    helper.Close = close
    code = "family = doc.EditFamily()\n"
    if rollback:
        code += "with execution.rollback_scope(family, 'trial'):\n"
        indent = "    "
    else:
        indent = ""
    code += (indent + "with execution.transaction(family, 'edit'):\n" +
             indent + "    family.value = 7\n" +
             "family.LoadFamily(doc)\nfamily.Close(False)")
    request["code"] = code
    safety = adapter.safety
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("succeeded", effects)
    assert loaded_into == [selected]
    assert receipt["result"]["document_notes"] == [{"stage": "document_closed"}]
    assert receipt["result"]["cleanup_errors"] == []
    assert not engine.quarantined and not safety.snapshot()["blocked"]
    assert adapter.safety is safety
    assert not engine.command_running
    # The same lane and guard accept a later operation after fresh snapshot refresh.
    engine.submit(dict(request, operation_id="next", code="print(doc.Title)"))
    engine.on_external_event(uiapp)
    assert engine.store.inspect("next")["state"] == "succeeded"
    assert adapter.safety is safety and not safety.snapshot()["blocked"]


def test_selected_document_loss_still_quarantines_operations(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, selected, helper = setup(execution_route.execute_payload)

    def close():
        selected.IsValidObject = False
        uiapp.Application.Documents.remove(selected)
        uiapp.ActiveUIDocument = None

    selected.close = close
    request["code"] = "doc.close()"
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "unknown")
    assert engine.quarantined and adapter.safety.snapshot()["blocked"]
    assert not engine.command_running


def test_equivalent_wrapper_child_commit_is_rolled_back_in_operation_receipt(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, selected, helper = setup(execution_route.execute_payload)
    selected.value = 0
    selected.alias = AliasDocument(selected)
    request["code"] = ("with execution.rollback_scope(doc, 'trial'):\n"
                       "    with execution.transaction(doc.alias, 'edit'):\n"
                       "        pass")
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "succeeded"
    assert receipt["effects"] == "unknown"  # Untracked script effects remain unproven.
    assert receipt["result"]["owned_effects"] == "rolled_back"
    assert all(item["effect"] == "rolled_back" for item in receipt["result"]["transaction_receipts"])
    assert not engine.quarantined and not adapter.safety.snapshot()["blocked"]


def test_closed_helper_with_pending_scope_still_quarantines_operations(execution_route):
    execution_route.DB = FakeDB({"commit_status": "Pending"})
    engine, adapter, reg, uiapp, request, selected, helper = setup(execution_route.execute_payload)
    selected.helper = helper
    helper.value = 0

    def close():
        helper.IsValidObject = False
        uiapp.Application.Documents.remove(helper)

    helper.close = close
    request["code"] = ("try:\n"
                       "    with execution.transaction(doc.helper, 'pending'):\n"
                       "        doc.helper.value = 7\n"
                       "except Exception:\n"
                       "    doc.helper.close()")
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "unknown")
    assert engine.quarantined and adapter.safety.snapshot()["blocked"]
    assert not execution_route.DB.created[0].disposed
    assert not engine.command_running


def test_inactive_facade_helpers_bind_selected_doc_and_withhold_ui(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, selected, active = setup(execution_route.execute_payload)
    uiapp.ActiveUIDocument = SimpleNamespace(Document=active)
    calls = []
    execution_route.revit = SimpleNamespace(
        doc=active, uidoc=uiapp.ActiveUIDocument, active_view="host view",
        active_ui_view="host UI view", docs=(active,),
        Transaction=lambda name, doc: calls.append(("transaction", doc)),
        TransactionGroup=lambda name, doc: calls.append(("group", doc)))
    request["code"] = ("assert revit.doc is doc\nassert revit.docs == (doc,)\n"
                       "assert uidoc is None and revit.uidoc is None\n"
                       "assert revit.active_view is None and revit.active_ui_view is None\n"
                       "revit.Transaction('bound')\nrevit.TransactionGroup('bound', None)")
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "succeeded" and receipt["effects"] == "unknown"
    assert calls == [("transaction", selected), ("group", selected)]
    assert uiapp.ActiveUIDocument.Document is active
    assert execution_route.revit.doc is active
    assert not adapter.safety.snapshot()["blocked"]


def test_opted_in_facade_view_updates_only_supplied_uidoc(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, selected, other = setup(execution_route.execute_payload)
    uidoc = uiapp.ActiveUIDocument
    selected.new_view = SimpleNamespace(Id=42)
    matching_ui_view = SimpleNamespace(ViewId=42)
    uidoc.ActiveView = SimpleNamespace(Id=11)
    uidoc.GetOpenUIViews = lambda: [SimpleNamespace(ViewId=11), matching_ui_view]
    execution_route.revit = SimpleNamespace(doc=other, active_view="host view")
    request.update(allow_ui_change=True, code=(
        "assert revit.doc is doc and revit.uidoc is uidoc\n"
        "revit.active_view = doc.new_view\n"
        "assert revit.active_view is uidoc.ActiveView\n"
        "assert revit.active_ui_view.ViewId == doc.new_view.Id"))
    safety = adapter.safety
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "succeeded"
    assert uidoc.ActiveView is selected.new_view
    assert execution_route.revit.active_view == "host view"
    assert adapter.safety is safety and not safety.snapshot()["blocked"]


def test_withheld_facade_view_assignment_fails_without_host_fallback(execution_route):
    execution_route.DB = FakeDB()
    engine, adapter, reg, uiapp, request, selected, other = setup(execution_route.execute_payload)
    uidoc = uiapp.ActiveUIDocument
    uidoc.ActiveView = "supplied view"
    execution_route.revit = SimpleNamespace(doc=other, active_view="host view")
    request["code"] = "revit.active_view = 'forbidden'"
    engine.submit(request)
    engine.on_external_event(uiapp)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "failed"
    assert receipt["result"]["error_type"] == "AttributeError"
    assert "allow_ui_change" in receipt["result"]["error"]
    assert uidoc.ActiveView == "supplied view" and execution_route.revit.active_view == "host view"
    assert not adapter.safety.snapshot()["blocked"]
