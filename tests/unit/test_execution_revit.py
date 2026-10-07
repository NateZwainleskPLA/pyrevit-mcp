from types import SimpleNamespace

import pytest

from revit_mcp.execution_helpers import build_hints
from revit_mcp.execution_revit import ScopedRevit
from tests.unit.test_execution_context import FakeDB, Document
from tests.unit.test_execution_output import execution_route


class HostRevit:
    def __getattr__(self, name):
        raise AssertionError("Host context accessed: " + name)


def test_active_view_setter_updates_bound_uidoc_and_cannot_be_shadowed():
    uidoc = SimpleNamespace(ActiveView="old")
    facade = ScopedRevit(HostRevit(), object(), uidoc)
    facade.active_view = "new"
    assert uidoc.ActiveView == "new"
    assert facade.active_view == "new"
    assert "active_view" not in facade.__dict__


def test_ui_properties_are_withheld_without_uidoc():
    facade = ScopedRevit(HostRevit(), object(), None)
    assert facade.active_view is None
    assert facade.active_ui_view is None
    with pytest.raises(AttributeError, match="allow_ui_change"):
        facade.active_view = "new"


def test_active_ui_view_matches_supplied_uidoc_view():
    match = SimpleNamespace(ViewId=42)
    uidoc = SimpleNamespace(ActiveView=SimpleNamespace(Id=42),
                           GetOpenUIViews=lambda: [SimpleNamespace(ViewId=11), match])
    facade = ScopedRevit(HostRevit(), object(), uidoc)
    assert facade.active_ui_view is match


def test_docs_are_scoped_and_public_names_cannot_be_assigned():
    doc = object()
    facade = ScopedRevit(HostRevit(), doc, None)
    assert facade.docs == (doc,)
    assert ScopedRevit(HostRevit(), None, None).docs == ()
    for name in ("doc", "uidoc", "docs", "active_ui_view", "Transaction", "misspelled_property"):
        with pytest.raises(AttributeError):
            setattr(facade, name, object())


@pytest.mark.parametrize("helper", ["Transaction", "TransactionGroup"])
def test_transaction_helpers_default_to_bound_doc_and_preserve_explicit_args(helper):
    calls = []
    def transaction(*args, **kwargs):
        calls.append((args, kwargs))
        return "scope"
    host = SimpleNamespace(**{helper: transaction})
    doc, other = object(), object()
    facade = ScopedRevit(host, doc, None)
    assert getattr(facade, helper)("default") == "scope"
    assert calls[-1] == (("default", doc), {})
    getattr(facade, helper)("explicit", other, False, log_errors=False)
    assert calls[-1] == (("explicit", other, False), {"log_errors": False})
    getattr(facade, helper)(name="named", doc=other)
    assert calls[-1] == (("named", other), {})
    with pytest.raises(ValueError, match="document"):
        getattr(ScopedRevit(host, None, None), helper)("no document")


def test_active_view_none_error_hint_points_to_ui_permission():
    hint = build_hints("AttributeError", "'NoneType' object has no attribute 'ActiveView'")
    assert "allow_ui_change" in hint[0]


def test_context_property_error_never_falls_back_to_host():
    class InvalidUIDoc:
        @property
        def ActiveView(self):
            raise AttributeError("invalid wrapper")
    facade = ScopedRevit(HostRevit(), object(), InvalidUIDoc())
    with pytest.raises(AttributeError):
        _ = facade.active_view


@pytest.mark.parametrize("allow_ui_change", [False, True])
def test_payload_facade_ui_gate_and_inactive_transaction_default(execution_route, allow_ui_change):
    doc, active_doc = Document(), Document()
    calls = []
    def transaction(name, document):
        calls.append(document)
    execution_route.DB = FakeDB()
    execution_route.revit = SimpleNamespace(doc=active_doc, Transaction=transaction)
    uidoc = SimpleNamespace(ActiveView=SimpleNamespace(Id=42), GetOpenUIViews=lambda: [])
    code = "revit.Transaction('bound')\nassert revit.docs == (doc,)\n"
    if allow_ui_change:
        code += "revit.active_view = 'new'\nassert revit.active_view == uidoc.ActiveView"
    else:
        code += "assert revit.active_view is None\nassert revit.active_ui_view is None"
    result, status = execution_route.execute_payload({"code": code, "allow_ui_change": allow_ui_change}, doc, uidoc)
    assert status == 200, result
    assert calls == [doc]
    assert execution_route.revit.doc is active_doc
