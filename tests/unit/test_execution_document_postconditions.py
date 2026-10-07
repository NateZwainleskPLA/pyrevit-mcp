"""Regression cases from Opus PR #3; native wrapper behavior is still pending."""
import pytest

from revit_mcp.execution_context import ExecutionContext
from revit_mcp.execution_output import execute_script
from revit_mcp.execution_safety import ExecutionSafety
from tests.unit.test_execution_context import Document, FakeDB
from tests.unit.test_execution_output import execution_route


class AliasDocument(Document):
    def __init__(self, target):
        self.target = target

    @property
    def IsModifiable(self):
        return self.target.IsModifiable

    @IsModifiable.setter
    def IsModifiable(self, value):
        self.target.IsModifiable = value

    def Equals(self, other):
        return other is self.target or other is self


def execute(code, doc, db, **extra):
    context = ExecutionContext(db, doc)
    namespace = {"doc": doc, "execution": context}
    namespace.update(extra)
    result = execute_script(code, namespace, "trial.py", runner=context.run)
    context.close()
    result.update(context.summary())
    return result, context


def test_successful_family_edit_and_close_is_informational(execution_route):
    doc, family = Document(), Document()
    family.Close = lambda save: setattr(family, "IsValidObject", False)
    doc.EditFamily = lambda: family
    execution_route.DB = FakeDB()
    code = ("famdoc = doc.EditFamily()\n"
            "with execution.transaction(famdoc, 'Edit family'):\n"
            "    famdoc.value = 1\n"
            "famdoc.Close(False)\nprint('loaded and closed')")
    result, status = execution_route.execute_payload({"code": code}, doc, None)
    assert status == 200 and result["status"] == "success"
    assert result["unsafe"] is False
    assert result["owned_effects"] == "committed"
    assert result["cleanup_errors"] == []
    assert result["document_notes"] == [{"stage": "document_closed"}]
    assert all(item["disposed"] for item in result["transaction_receipts"])
    safety = ExecutionSafety()
    safety.observe(result)
    safety.require_safe()


def test_closed_secondary_rollback_preserves_receipt_and_unknown_raw_effects():
    doc, family = Document(), Document()
    code = "with execution.rollback_scope(family, 'Trial'):\n    with execution.transaction(family, 'edit'):\n        family.value = 1\nfamily.IsValidObject = False"
    result, context = execute(code, doc, FakeDB(), family=family)
    assert result["status"] == "success" and not result["unsafe"]
    assert result["owned_effects"] == "rolled_back"
    assert result["effects"] == "unknown"
    assert result["cleanup_errors"] == []
    assert result["document_notes"] == [{"stage": "document_closed"}]


@pytest.mark.parametrize("case", ["selected_closed", "secondary_modifiable", "secondary_active_closed"])
def test_unsafe_document_postconditions_still_fail(case):
    doc, family = Document(), Document()
    if case == "selected_closed":
        code, db = "doc.IsValidObject = False", FakeDB()
    elif case == "secondary_modifiable":
        code = "with execution.transaction(family, 'edit'):\n    pass\nfamily.IsModifiable = True"
        db = FakeDB()
    else:
        code = "t = execution.transaction(family, 'edit')\nt.__enter__()\nfamily.IsValidObject = False"
        db = FakeDB({"rollback_error": True})
    result, context = execute(code, doc, db, family=family)
    assert result["unsafe"] and result["status"] == "error"
    assert any(item["stage"] == "document_postcondition" for item in result["cleanup_errors"])


def test_alias_wrapper_is_parented_and_deduplicated_for_group_rollback():
    doc = Document()
    alias = AliasDocument(doc)
    code = "with execution.rollback_scope(doc, 'Trial'):\n    with execution.transaction(alias, 'Flex'):\n        pass"
    result, context = execute(code, doc, FakeDB(), alias=alias)
    group, transaction = context.scopes
    assert transaction.parent is group
    assert context.documents == [doc]
    assert result["owned_effects"] == "rolled_back"
    assert result["effects"] == "unknown"
    assert transaction.receipt["effect"] == "rolled_back"


def test_alias_leaked_child_is_unwound_before_group_exit():
    doc, db = Document(), FakeDB()
    alias = AliasDocument(doc)
    code = "with execution.rollback_scope(doc, 'Trial'):\n    t = execution.transaction(alias, 'Flex')\n    t.__enter__()"
    result, context = execute(code, doc, db, alias=alias)
    assert db.events[-4:] == [("Flex", "rollback"), ("Flex", "dispose"), ("Trial", "rollback"), ("Trial", "dispose")]
    assert not result["unsafe"] and result["owned_effects"] == "rolled_back"
