"""Real receiver/identity/execution composition with controlled native doubles."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from revit_mcp.execution_safety import ExecutionSafety
from revit_mcp.target_routing import TargetedAPI
from tests.unit.test_execution_context import FakeDB
from tests.unit.test_execution_output import execution_route
from tests.unit.test_receiver_target_routing import API
from tests.unit.test_target_identity import Document, registry


@pytest.fixture
def composed(execution_route):
    selected, active = Document(), Document()
    for doc in (selected, active):
        doc.IsModifiable = False
        doc.value = 0
    selected.requested_view = SimpleNamespace(Id=2)
    selected.ui_view = SimpleNamespace(ViewId=2)
    selected_uidoc = SimpleNamespace(Document=selected, ActiveView=SimpleNamespace(Id=1),
                                    GetOpenUIViews=lambda: [selected.ui_view])
    host_uidoc = SimpleNamespace(Document=active, ActiveView=SimpleNamespace(Id=99))
    helper_calls = []
    def helper(kind):
        def invoke(name=None, doc=None, *args, **kwargs):
            helper_calls.append((kind, name, doc, args, kwargs))
            return SimpleNamespace()
        return invoke
    execution_route.revit = SimpleNamespace(
        doc=active, uidoc=host_uidoc, docs=(active,), active_view=host_uidoc.ActiveView,
        active_ui_view=SimpleNamespace(ViewId=99),
        Transaction=helper("transaction"), TransactionGroup=helper("group"))
    execution_route.DB = FakeDB()
    execution_route.routes.make_response = lambda data, status=200, headers=None: SimpleNamespace(
        data=data, status=status, headers=headers or {})
    reg = registry()
    snap = reg.refresh_documents([selected, active], selected)
    ids = {key: snap[key] for key in ("instance_id", "runtime_id")}
    ids["document_id"] = snap["documents"][0]["document_id"]
    uiapp = SimpleNamespace(Application=SimpleNamespace(Documents=[selected, active]),
                            ActiveUIDocument=host_uidoc)
    safety, api = ExecutionSafety(), API()
    proxy = TargetedAPI(api, lambda: reg, safety=safety)
    execution_route.register_code_execution_routes(proxy)
    return SimpleNamespace(api=api, proxy=proxy, reg=reg, selected=selected, active=active,
                           uiapp=uiapp, ids=ids, safety=safety, helper_calls=helper_calls,
                           selected_uidoc=selected_uidoc, host_uidoc=host_uidoc,
                           execution=execution_route)


def execute(host, code, **options):
    return host.api.handlers["/execute_code/"](
        host.uiapp, SimpleNamespace(method="POST", data=dict(host.ids, code=code, **options)))


def test_inactive_document_execution_and_default_helpers_use_requested_document(composed):
    result = execute(composed, """
assert revit.doc is doc
assert revit.docs == (doc,)
assert uidoc is None and revit.uidoc is None
assert revit.active_view is None and revit.active_ui_view is None
revit.Transaction('bound')
revit.TransactionGroup('bound group', None)
with execution.transaction(doc, 'owned edit'):
    doc.value = 42
""")
    assert result.status == 200
    assert result.data["actual_target"] == composed.ids
    assert result.data["effects"] == "committed" and not result.data["unsafe"]
    assert composed.selected.value == 42 and composed.active.value == 0
    assert [call[2] for call in composed.helper_calls] == [composed.selected, composed.selected]
    assert composed.uiapp.ActiveUIDocument is composed.host_uidoc
    assert not composed.safety.snapshot()["blocked"]


def test_ui_permission_changes_supplied_uidocument_only(composed):
    composed.uiapp.ActiveUIDocument = composed.selected_uidoc
    host_view = composed.host_uidoc.ActiveView
    result = execute(composed, """
assert revit.uidoc is uidoc
revit.active_view = doc.requested_view
assert revit.active_view is doc.requested_view
assert revit.active_ui_view is doc.ui_view
""", allow_ui_change=True)
    assert result.status == 200 and not result.data["unsafe"]
    assert composed.selected_uidoc.ActiveView is composed.selected.requested_view
    assert composed.host_uidoc.ActiveView is host_view
    # UI and untracked pyRevit helpers do not prove owned transaction effects.
    assert result.data["effects"] == "unknown"


def test_inactive_document_with_ui_permission_rejected_before_execution(composed):
    service = Mock(wraps=composed.execution.execute_payload)
    composed.execution.execute_payload = service
    result = execute(composed, "doc.value = 42", allow_ui_change=True)
    assert result.status == 409 and result.data["error_code"] == "inactive_document"
    assert result.data["effects"] == "none"
    service.assert_not_called()
    assert composed.selected.value == 0 and composed.active.value == 0


def test_withheld_ui_assignment_fails_without_host_fallback_or_safety_reset(composed):
    before = composed.host_uidoc.ActiveView
    result = execute(composed, "revit.active_view = doc.requested_view")
    assert result.status == 500 and result.data["error_type"] == "AttributeError"
    assert "allow_ui_change" in result.data["error"]
    assert composed.host_uidoc.ActiveView is before
    assert not result.data["unsafe"] and not composed.safety.snapshot()["blocked"]


def test_actual_execution_unsafe_result_blocks_other_mutations_with_same_guard(composed):
    first = execute(composed, "doc.IsModifiable = True")
    assert first.status == 500 and first.data["unsafe"]
    assert first.data["effects"] == "unknown"
    assert composed.safety.snapshot()["blocked"]
    # Settling the double's document cannot reset the retained safety verdict.
    composed.selected.IsModifiable = False
    save = Mock()
    @composed.proxy.route("/save_document/", methods=["POST"])
    def save_route(doc, request):
        save(doc)
    @composed.proxy.route("/list_levels/", methods=["GET"])
    def query(doc):
        return {"status": "success", "title": doc.Title}
    for path in ("/execute_code/", "/save_document/"):
        response = composed.api.handlers[path](composed.uiapp, SimpleNamespace(
            method="POST", data=dict(composed.ids, code="doc.value = 42")))
        assert response.status == 409 and response.data["error_code"] == "mutation_blocked"
        assert response.data["effects"] == "none"
    save.assert_not_called()
    assert composed.selected.value == 0
    assert query(composed.uiapp, SimpleNamespace(method="GET", query_params=composed.ids)).status == 200


def test_link_status_changed_after_snapshot_rejected_by_fresh_live_resolution(composed):
    assert any(d["document_id"] == composed.ids["document_id"] for d in composed.reg.snapshot()["documents"])
    composed.selected.IsLinked = True
    result = execute(composed, "doc.value = 42")
    assert result.status == 409 and result.data["error_code"] == "stale_document"
    assert result.data["effects"] == "none" and composed.selected.value == 0


def test_family_eligibility_uses_resolved_native_document_not_old_descriptor(composed):
    assert composed.reg.snapshot()["documents"][0]["is_family_document"] is False
    # A prior/defaulted descriptor is descriptive. It cannot prohibit a valid
    # family workflow supported by execution; live native properties govern it.
    composed.selected.IsFamilyDocument = True
    result = execute(composed, "assert doc.IsFamilyDocument\nassert revit.doc is doc")
    assert result.status == 200 and result.data["actual_target"] == composed.ids
    assert not result.data["unsafe"] and not composed.safety.snapshot()["blocked"]
