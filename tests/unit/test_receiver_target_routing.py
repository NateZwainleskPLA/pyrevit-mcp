import inspect
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from revit_mcp.target_routing import TargetedAPI, validate_api_context
from tests.unit.test_target_identity import Document, registry


class API:
    def __init__(self):
        self.handlers = {}

    def route(self, endpoint, **options):
        def register(handler):
            self.handlers[endpoint] = handler
            return handler
        return register


@pytest.fixture
def host(monkeypatch):
    routes = SimpleNamespace(make_response=lambda data, status=200, headers=None:
                             SimpleNamespace(data=data, status=status, headers=headers or {}))
    monkeypatch.setitem(sys.modules, "pyrevit", SimpleNamespace(routes=routes))
    reg = registry()
    a, b = Document(), Document()
    snapshot = reg.refresh_documents([a, b], a)
    app = SimpleNamespace(Application=SimpleNamespace(Documents=[a, b]),
                          ActiveUIDocument=SimpleNamespace(Document=a))
    ids = {key: snapshot[key] for key in ("instance_id", "runtime_id")}
    ids["document_id"] = snapshot["documents"][0]["document_id"]
    return reg, a, b, app, ids


def test_active_switch_while_waiting_resolves_requested_database_doc(host):
    reg, a, b, app, ids = host
    app.ActiveUIDocument = SimpleNamespace(Document=b)
    doc, uidoc, actual = validate_api_context(reg, "/save_document/", ids, app)
    assert doc is a
    assert uidoc is None
    assert actual == ids


def test_active_switch_while_waiting_rejects_ui_work(host):
    reg, a, b, app, ids = host
    app.ActiveUIDocument = SimpleNamespace(Document=b)
    with pytest.raises(ValueError, match="specified document to be active"):
        validate_api_context(reg, "/current_view_info/", ids, app)


def test_execution_hides_ui_without_explicit_permission(host):
    reg, a, b, app, ids = host
    assert validate_api_context(reg, "/execute_code/", ids, app)[1] is None
    assert validate_api_context(reg, "/execute_code/", dict(ids, allow_ui_change=True), app)[1] is app.ActiveUIDocument


@pytest.mark.parametrize("change", ["runtime_id", "instance_id", "document_id", "missing", "closed"])
def test_invalid_receiver_identities_never_execute_handler(host, change):
    reg, a, b, app, ids = host
    if change in ids:
        ids[change] = "00000000-0000-0000-0000-000000000000"
    elif change == "missing":
        ids.pop("runtime_id")
    else:
        app.Application.Documents = [b]
        a.IsValidObject = False
    api = API()
    handler = Mock()

    @TargetedAPI(api, lambda: reg).route("/save_document/", methods=["POST"])
    def save(doc, request):
        handler(doc)
        return {"status": "success"}

    response = save(app, SimpleNamespace(method="POST", data=ids))
    assert response.status == 409
    assert "actual_target" in response.data
    handler.assert_not_called()


def test_get_request_and_real_uiapp_signature_are_retained(host):
    reg, a, b, app, ids = host
    api = API()

    @TargetedAPI(api, lambda: reg).route("/get_view/<view_name>", methods=["GET"])
    def export(doc, view_name):
        assert doc is a
        return {"status": "success", "view_name": view_name}

    assert list(inspect.signature(export).parameters) == ["uiapp", "request", "view_name"]
    response = export(app, SimpleNamespace(method="GET", query_params=ids), "Level 1")
    assert response.data["actual_target"] == ids
    assert response.data["view_name"] == "Level 1"


def test_mutation_admission_guard_runs_before_handler(host):
    reg, a, b, app, ids = host
    from revit_mcp.routing_policy import RoutingPolicyError
    guard = Mock(side_effect=RoutingPolicyError("legacy_disabled", "Private lane is exclusive"))
    handler = Mock()

    @TargetedAPI(API(), lambda: reg, guard).route("/save_document/", methods=["POST"])
    def save(doc, request):
        handler()

    response = save(app, SimpleNamespace(method="POST", data=ids))
    assert response.data["error_code"] == "legacy_disabled"
    handler.assert_not_called()


@pytest.mark.parametrize("endpoint", ["/execute_code/", "/execute_application_code/", "/place_family/", "/color_splash/", "/clear_colors/", "/open_document/", "/close_document/", "/save_document/", "/sync_with_central/"])
def test_same_unsafe_guard_blocks_every_mutation_route(host, endpoint):
    from revit_mcp.execution_safety import ExecutionSafety
    reg, a, b, app, ids = host
    safety = ExecutionSafety()
    safety.observe({"unsafe": True})
    handler = Mock()

    @TargetedAPI(API(), lambda: reg, safety=safety).route(endpoint, methods=["POST"])
    def mutate(doc, request):
        handler()
    data = dict(ids, allow_ui_change=True)
    if endpoint == "/execute_application_code/":
        data.pop("document_id")
    response = mutate(app, SimpleNamespace(method="POST", data=data))
    assert response.status == 409
    assert response.data["error_code"] == "mutation_blocked"
    handler.assert_not_called()


def test_raw_leak_quarantines_later_mutations_but_queries_remain_available(host):
    from revit_mcp.execution_safety import ExecutionSafety
    reg, a, b, app, ids = host
    a.IsModifiable = False
    safety = ExecutionSafety()
    proxy = TargetedAPI(API(), lambda: reg, safety=safety)

    @proxy.route("/save_document/", methods=["POST"])
    def leak(doc, request):
        doc.IsModifiable = True
        return {"status": "success"}

    response = leak(app, SimpleNamespace(method="POST", data=ids))
    assert response.status == 500
    assert response.data["unsafe"] is True
    assert response.data["effects"] == "unknown"
    assert safety.snapshot()["blocked"]

    @proxy.route("/list_levels/", methods=["GET"])
    def query(doc):
        return {"status": "success", "levels": []}

    assert query(app, SimpleNamespace(method="GET", query_params=ids)).status == 200


def test_process_retention_does_not_reset_unsafe_state(monkeypatch):
    from revit_mcp.target_routing import get_process_safety
    values = {}
    domain = SimpleNamespace(GetData=values.get, SetData=values.__setitem__)
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(AppDomain=SimpleNamespace(CurrentDomain=domain)))
    first = get_process_safety()
    first.observe({"unsafe": True})
    second = get_process_safety()
    assert second is first and second.snapshot()["blocked"]


def test_exclusive_mode_registers_http_rejections_without_api_arguments(host):
    from revit_mcp.target_routing import DisabledAPI
    reg, a, b, app, ids = host
    api = API()
    handler = Mock()

    @DisabledAPI(api, lambda: reg).route("/save_document/", methods=["POST"])
    def save(doc, uidoc, uiapp, request):
        handler()
    assert list(inspect.signature(save).parameters) == ["request"]
    assert save(SimpleNamespace()).status == 503
    handler.assert_not_called()


def test_exclusive_metadata_refresh_is_disabled_but_cached_metadata_is_not(host):
    from revit_mcp.target_routing import DisabledAPI
    reg, a, b, app, ids = host
    api = API()
    proxy = DisabledAPI(api, lambda: reg, metadata_only=True)

    @proxy.route("/metadata/", methods=["GET"])
    def metadata():
        return reg.snapshot()

    @proxy.route("/metadata/refresh/", methods=["GET"])
    def refresh(uiapp):
        pytest.fail("API refresh executed in exclusive mode")

    assert list(inspect.signature(metadata).parameters) == []
    assert list(inspect.signature(refresh).parameters) == ["request"]
    assert refresh(SimpleNamespace()).status == 503
