"""Transaction state/effect simulation; native Revit checks remain pending."""
import sys
from types import SimpleNamespace

import pytest

from revit_mcp.execution_context import ExecutionContext, retained_contexts
from revit_mcp.execution_output import execute_script
from tests.unit.test_execution_output import execution_route


class Document:
    IsValidObject = True
    IsModifiable = False
    value = 0


class NativeScope:
    def __init__(self, db, doc, name, kind, plan):
        self.db, self.doc, self.name, self.kind, self.plan = db, doc, name, kind, plan
        self.status = "Uninitialized"
        self.disposed = False
        self.snapshot = None

    def Start(self):
        self.snapshot = self.doc.value
        self.status = "Started"
        if self.kind == "transaction":
            self.doc.IsModifiable = True
        self.db.events.append((self.name, "start"))
        if self.plan.get("start_error"):
            raise RuntimeError("failure after start")
        return self.status

    def GetStatus(self):
        if self.plan.get("status_error"):
            raise RuntimeError("status unavailable")
        return self.status

    def Commit(self):
        self.db.events.append((self.name, "commit"))
        if self.plan.get("commit_error"):
            raise RuntimeError("commit failure")
        self.status = self.plan.get("commit_status", "Committed")
        if self.status == "RolledBack":
            self.doc.value = self.snapshot
        if self.status != "Pending":
            self.doc.IsModifiable = False
        return self.plan.get("commit_return", self.status)

    def RollBack(self):
        self.db.events.append((self.name, "rollback"))
        if self.plan.get("rollback_error"):
            raise RuntimeError("rollback failure")
        self.status = self.plan.get("rollback_status", "RolledBack")
        if self.status == "RolledBack":
            self.doc.value = self.snapshot
            self.doc.IsModifiable = False
        return self.status

    def Dispose(self):
        self.db.events.append((self.name, "dispose"))
        if self.plan.get("dispose_error"):
            raise RuntimeError("dispose failure")
        self.disposed = True


class FakeDB:
    TransactionStatus = SimpleNamespace(**{name: name for name in
        ["Uninitialized", "Started", "Committed", "RolledBack", "Pending", "Error"]})
    def __init__(self, *plans):
        self.plans = list(plans)
        self.events = []
        self.created = []
    def _create(self, doc, name, kind):
        scope = NativeScope(self, doc, name, kind, self.plans.pop(0) if self.plans else {})
        self.created.append(scope)
        return scope
    def Transaction(self, doc, name):
        return self._create(doc, name, "transaction")
    def TransactionGroup(self, doc, name):
        return self._create(doc, name, "group")


def run(code, mode="script", db=None, doc=None, cancellation_check=None):
    db, doc = db or FakeDB(), doc or Document()
    context = ExecutionContext(db, doc, mode, cancellation_check)
    result = execute_script(code, {"doc": doc, "execution": context}, "trial.py", runner=context.run)
    context.close()
    result.update(context.summary())
    return result, context, db, doc


def test_managed_commit():
    result, context, db, doc = run("doc.value = 42", "managed")
    assert result["status"] == "success"
    assert result["effects"] == "committed"
    assert result["unsafe"] is False
    assert doc.value == 42 and not doc.IsModifiable
    assert db.events == [("Managed execution", "start"), ("Managed execution", "commit"), ("Managed execution", "dispose")]


def test_managed_exception_rollback_preserves_error_and_output():
    streams = sys.stdout, sys.stderr
    result, context, db, doc = run("doc.value = 42\nprint('before')\nassert False", "managed")
    assert result["error_type"] == "AssertionError"
    assert result["partial_output"] == "before\n"
    assert result["effects"] == "rolled_back"
    assert not result["unsafe"] and doc.value == 0
    assert (sys.stdout, sys.stderr) == streams


def test_start_raises_after_native_start_is_cleaned():
    result, context, db, doc = run("doc.value = 99", "managed", FakeDB({"start_error": True}))
    assert result["error_type"] == "RuntimeError"
    assert result["effects"] == "rolled_back"
    assert not doc.IsModifiable and db.created[0].disposed
    assert db.events[1] == ("Managed execution", "rollback")


def test_rollback_group_undoes_inner_committed_transaction():
    code = "with execution.rollback_scope(doc, u'试验'):\n    with execution.transaction(doc, 'edit'):\n        doc.value = 77"
    result, context, db, doc = run(code)
    assert result["status"] == "success"
    assert doc.value == 0
    assert result["owned_effects"] == "rolled_back"
    # Raw transactions/file effects outside helper scopes are not proven absent.
    assert result["effects"] == "unknown"
    assert all(item["effect"] == "rolled_back" for item in result["transaction_receipts"])


def test_earlier_commit_survives_later_failure():
    code = "with execution.transaction(doc, 'first'):\n    doc.value = 1\nwith execution.transaction(doc, 'second'):\n    doc.value = 2\n    assert False"
    result, context, db, doc = run(code)
    assert result["effects"] == "committed"
    assert result["error_type"] == "AssertionError"
    assert doc.value == 1


def test_leaked_scopes_unwind_in_reverse_order_and_fail():
    code = "g = execution.rollback_scope(doc, 'group')\ng.__enter__()\nt = execution.transaction(doc, 'edit')\nt.__enter__()\ndoc.value = 1"
    result, context, db, doc = run(code)
    assert result["error_type"] == "TransactionScopeError"
    assert db.events[-4:] == [("edit", "rollback"), ("edit", "dispose"), ("group", "rollback"), ("group", "dispose")]
    assert doc.value == 0 and not result["unsafe"]


def test_cleanup_error_preserves_primary_and_retains_only_owned_scopes():
    db = FakeDB({}, {"rollback_error": True})
    code = "with execution.rollback_scope(doc, 'group'):\n    with execution.transaction(doc, 'edit'):\n        doc.value = 9\n        assert False"
    result, context, db, doc = run(code, db=db)
    assert result["error_type"] == "AssertionError"
    assert result["effects"] == "unknown" and result["unsafe"]
    assert result["cleanup_errors"]
    assert ("group", "rollback") not in db.events
    assert context in retained_contexts()
    assert not any(item.disposed for item in db.created)


@pytest.mark.parametrize("plan", [{"commit_status": "Pending"},
                                  {"commit_return": "Pending"},
                                  {"commit_return": "RolledBack"},
                                  {"rollback_status": "Pending"}])
def test_pending_or_mismatched_status_is_not_proven_or_disposed(plan):
    code = "doc.value = 1\nassert False" if "rollback_status" in plan else "doc.value = 1"
    result, context, db, doc = run(code, "managed", FakeDB(plan))
    assert result["status"] == "error"
    assert result["effects"] == "unknown" and result["unsafe"]
    assert not db.created[0].disposed
    assert context in retained_contexts()


def test_commit_failure_processing_rollback_is_failed_but_confirmed_safe():
    result, context, db, doc = run("doc.value = 9", "managed", FakeDB({"commit_status": "RolledBack"}))
    assert result["status"] == "error"
    assert result["effects"] == "rolled_back"
    assert not result["unsafe"] and db.created[0].disposed


@pytest.mark.parametrize("plan", [{"commit_error": True}, {"dispose_error": True}, {"status_error": True}])
def test_cleanup_errors_are_never_reported_as_successful_rollback(plan):
    result, context, db, doc = run("doc.value = 7", "managed", FakeDB(plan))
    assert result["status"] == "error" and result["unsafe"]
    assert result["effects"] == "unknown"
    assert result["cleanup_errors"]


def test_foreign_modifiable_document_is_rejected_without_cleanup():
    doc = Document()
    doc.IsModifiable = True
    result, context, db, doc = run("doc.value = 9", "managed", doc=doc)
    assert result["error_type"] == "UnsafeDocumentError"
    assert result["unsafe"] and not db.created
    assert doc.IsModifiable and doc.value == 0


def test_untracked_leak_is_observed_and_never_cleaned():
    result, context, db, doc = run("doc.IsModifiable = True")
    assert result["status"] == "error" and result["unsafe"]
    assert result["effects"] == "unknown"
    assert not db.created and doc.IsModifiable


def test_managed_rejects_additional_helper_transactions():
    result, context, db, doc = run("with execution.transaction(doc, 'illegal'):\n    pass", "managed")
    assert result["error_type"] == "TransactionScopeError"
    assert len(db.created) == 1 and db.created[0].disposed
    assert result["effects"] == "rolled_back"


def test_cancellation_checkpoint_rolls_back_managed_work():
    doc = Document()
    result, context, db, doc = run("doc.value = 8\nexecution.checkpoint()", "managed", doc=doc,
                                  cancellation_check=lambda: doc.value == 8)
    assert result["error_type"] == "ExecutionCanceled"
    assert result["effects"] == "rolled_back" and doc.value == 0


def test_cancellation_after_script_before_commit():
    doc = Document()
    result, context, db, doc = run("doc.value = 8", "managed", doc=doc,
                                  cancellation_check=lambda: doc.value == 8)
    assert result["error_type"] == "ExecutionCanceled"
    assert result["effects"] == "rolled_back" and doc.value == 0


def test_canceled_before_start_and_syntax_error_have_no_effects():
    result, context, db, doc = run("doc.value = 8", "managed", cancellation_check=lambda: True)
    assert result["error_type"] == "ExecutionCanceled"
    assert result["effects"] == "none" and not db.created
    result, context, db, doc = run("x =", "managed")
    assert result["error_type"] == "SyntaxError"
    assert result["effects"] == "none" and not db.created


def test_named_checks_preserve_expected_actual():
    result, context, db, doc = run("execution.check(u'名称', 2, 3)", "managed")
    assert result["error_type"] == "AssertionError"
    assert result["checks"] == [{"name": "名称", "expected": 2, "actual": 3, "passed": False}]
    assert result["effects"] == "rolled_back"


def test_context_and_scopes_cannot_be_reused():
    context = ExecutionContext(FakeDB(), Document())
    context.close()
    with pytest.raises(Exception, match="cannot be reused"):
        with context.transaction(context.document, "late"):
            pass


@pytest.mark.parametrize("mode", ["managed", "script"])
def test_full_payload_execution_service(execution_route, mode):
    db, doc = FakeDB(), Document()
    execution_route.DB = db
    code = "doc.value = 5" if mode == "managed" else "with execution.transaction(doc, 'edit'):\n    doc.value = 5"
    result, status = execution_route.execute_payload(
        {"code": code, "transaction_mode": mode, "script_name": "C:\\files\\edit.py"}, doc, None)
    assert status == 200 and result["effects"] == "committed"
    assert result["script_name"] == "edit.py" and doc.value == 5
    assert result["transaction_receipts"][0]["disposed"]


def test_full_payload_cancellation_and_mode_validation(execution_route):
    execution_route.DB = FakeDB()
    result, status = execution_route.execute_payload({"code": "pass", "transaction_mode": "managed"}, Document(), None,
                                                    cancellation_check=lambda: True)
    assert status == 500 and result["error_type"] == "ExecutionCanceled"
    assert result["effects"] == "none"
    assert execution_route.execute_payload({"code": "pass", "transaction_mode": "invalid"}, Document(), None)[1] == 400
    assert execution_route.execute_payload({"code": "pass", "transaction_mode": "managed"}, None, None)[1] == 400


@pytest.mark.parametrize("allow_ui_change", [False, True])
def test_namespace_binds_specified_document_and_ui_permission(execution_route, allow_ui_change):
    execution_route.DB = FakeDB()
    doc, uidoc = Document(), SimpleNamespace()
    execution_route.revit = SimpleNamespace(doc=Document(), uidoc=object())
    code = "assert revit.doc is doc\nassert revit.uidoc is uidoc\nassert (uidoc is not None) == " + repr(allow_ui_change)
    result, status = execution_route.execute_payload({"code": code, "allow_ui_change": allow_ui_change}, doc, uidoc)
    assert status == 200, result
    assert execution_route.revit.doc is not doc


def test_optional_revit_facade_seam(execution_route):
    execution_route.DB = FakeDB()
    result, status = execution_route.execute_payload({"code": "assert revit.marker == 42"}, Document(), None,
                                                    revit_context=SimpleNamespace(marker=42))
    assert status == 200, result
