"""Application bootstrap through real receiver/execution and native doubles."""
import inspect
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from revit_mcp.execution_safety import ExecutionSafety
from revit_mcp.target_routing import TargetedAPI
from tests.unit.test_execution_context import FakeDB
from tests.unit.test_execution_output import execution_route
from tests.unit.test_receiver_target_routing import API
from tests.unit.test_target_identity import Document, registry


@pytest.fixture
def application_host(execution_route):
    native_db = FakeDB()
    execution_route.DB = native_db
    execution_route.routes.make_response = lambda data, status=200, headers=None: SimpleNamespace(
        data=data, status=status, headers=headers or {})
    application = SimpleNamespace(Documents=[])
    uiapp = SimpleNamespace(Application=application, ActiveUIDocument=None)
    opened = []

    def open_document(path):
        doc = Document(path=path)
        doc.IsModifiable, doc.value = False, 0
        def close(save):
            doc.IsValidObject = False
            application.Documents.remove(doc)
        doc.Close = close
        application.Documents.append(doc)
        opened.append(doc)
        return doc

    def open_ui_document(path):
        uidoc = SimpleNamespace(Document=open_document(path))
        uiapp.ActiveUIDocument = uidoc
        return uidoc

    application.OpenDocumentFile = open_document
    uiapp.OpenAndActivateDocument = open_ui_document
    # A deliberately unrelated host must never supply the new execution context.
    execution_route.revit = SimpleNamespace(app=object(), uiapp=object(), doc=object(), uidoc=object())
    reg = registry()
    snap = reg.refresh_documents([])
    ids = {key: snap[key] for key in ("instance_id", "runtime_id")}
    safety, api = ExecutionSafety(), API()
    proxy = TargetedAPI(api, lambda: reg, safety=safety)
    execution_route.register_code_execution_routes(proxy)
    return SimpleNamespace(api=api, proxy=proxy, reg=reg, ids=ids, safety=safety,
                           uiapp=uiapp, opened=opened, db=native_db, execution=execution_route)


def execute(host, code, **options):
    return host.api.handlers["/execute_application_code/"](
        host.uiapp, SimpleNamespace(method="POST", data=dict(host.ids, code=code, **options)))


def test_home_bootstrap_opens_first_document_then_commits_owned_work(application_host):
    host = application_host
    response = execute(host, """
assert doc is None and uidoc is None
assert revit.doc is None and revit.uidoc is None and revit.docs == ()
assert app is revit.app and uiapp is None and revit.uiapp is None
new_doc = app.OpenDocumentFile('fixture.rvt')
with execution.transaction(new_doc, 'Bootstrap edit'):
    new_doc.value = 42
assert doc is None and revit.doc is None
execution.check('new value', 42, new_doc.value)
print('continued')
""")
    assert response.status == 200
    assert response.data["actual_target"] == host.ids
    assert response.data["output"] == "continued\n"
    assert response.data["effects"] == "committed" and not response.data["unsafe"]
    assert host.opened[0].value == 42 and not host.opened[0].IsModifiable
    descriptor = response.data["opened_documents"][0]
    assert host.reg.resolve_document(host.ids["instance_id"], host.ids["runtime_id"],
                                     descriptor["document_id"], host.uiapp.Application.Documents) is host.opened[0]
    assert not host.safety.snapshot()["blocked"]
    assert list(inspect.signature(host.api.handlers["/execute_application_code/"]).parameters) == ["uiapp", "request"]


def test_foreign_open_transaction_rejected_before_application_script(application_host):
    host = application_host
    doc = host.uiapp.Application.OpenDocumentFile('already-open.rvt')
    raw = host.db.Transaction(doc, 'Foreign')
    raw.Start()
    response = execute(host, "app.OpenDocumentFile('must-not-open.rvt')")
    assert response.status == 409 and response.data["error_code"] == "modifiable_document"
    assert response.data["effects"] == "none"
    assert len(host.opened) == 1 and raw.status == "Started" and not raw.disposed
    assert not host.safety.snapshot()["blocked"]


@pytest.mark.parametrize("mode", ["active_document", "home"])
def test_application_binding_stays_none_without_creating_transaction(application_host, mode):
    host = application_host
    if mode == "active_document":
        host.uiapp.OpenAndActivateDocument('active.rvt')
    response = execute(host, "assert doc is None and uidoc is None\nassert execution.document is None")
    assert response.status == 200 and response.data["actual_target"] == host.ids
    assert response.data["transaction_receipts"] == [] and host.db.created == []
    assert response.data["opened_documents"] == []


@pytest.mark.parametrize("selector", [{"document_id": None}, {"document_id": "foreign"}, {"document": "d1"}])
def test_application_route_rejects_any_document_selector_before_script(application_host, selector):
    response = execute(application_host, "app.OpenDocumentFile('must-not-open.rvt')", **selector)
    assert response.status == 409 and response.data["error_code"] == "unexpected_document"
    assert response.data["effects"] == "none" and application_host.opened == []


@pytest.mark.parametrize("key,value", [("instance_id", str(uuid4())), ("runtime_id", str(uuid4())),
                                      ("instance_id", None), ("runtime_id", "invalid")])
def test_stale_or_foreign_application_identity_rejected_without_native_access(application_host, key, value):
    host = application_host
    class NoNativeAccess:
        def __getattr__(self, name):
            pytest.fail("Native access before target validation: " + name)
    payload = dict(host.ids, code="raise AssertionError('must not run')")
    payload[key] = value
    response = host.api.handlers["/execute_application_code/"](
        NoNativeAccess(), SimpleNamespace(method="POST", data=payload))
    assert response.status == 409 and response.data["effects"] == "none"
    assert application_host.opened == []


def test_document_execution_does_not_infer_application_scope(application_host):
    host = application_host
    response = host.api.handlers["/execute_code/"](host.uiapp, SimpleNamespace(
        method="POST", data=dict(host.ids, code="app.OpenDocumentFile('must-not-open.rvt')")))
    assert response.status == 409 and response.data["effects"] == "none"
    assert host.opened == []


def test_application_managed_mode_rejected_without_execution(application_host):
    host = application_host
    response = execute(host, "app.OpenDocumentFile('must-not-open.rvt')", transaction_mode="managed")
    assert response.status == 400 and response.data["effects"] == "none"
    assert "requires a document" in response.data["error"]
    assert host.opened == [] and host.db.created == []


@pytest.mark.parametrize("permission", [False, True])
def test_application_ui_is_explicitly_supplied_or_withheld(application_host, permission):
    host = application_host
    code = """
assert doc is None and uidoc is None
assert uiapp is revit.uiapp
new_uidoc = uiapp.OpenAndActivateDocument('visible.rvt')
assert new_uidoc.Document is app.Documents[0]
assert doc is None and uidoc is None and revit.uidoc is None
print('activated')
"""
    response = execute(host, code, allow_ui_change=permission)
    if permission:
        assert response.status == 200 and response.data["output"] == "activated\n"
        assert response.data["opened_documents"][0]["is_active"]
        assert host.uiapp.ActiveUIDocument.Document is host.opened[0]
    else:
        assert response.status == 500 and response.data["error_type"] == "AttributeError"
        assert host.opened == [] and host.uiapp.ActiveUIDocument is None
    assert not response.data["unsafe"] and not host.safety.snapshot()["blocked"]


@pytest.mark.parametrize("permission", ["true", 1, None])
def test_invalid_ui_permission_rejected_before_application_script(application_host, permission):
    response = execute(application_host, "app.OpenDocumentFile('must-not-open.rvt')", allow_ui_change=permission)
    assert response.status == 409 and response.data["error_code"] == "invalid_ui_permission"
    assert application_host.opened == []


@pytest.mark.parametrize("existing", [False, True])
def test_raw_transaction_leak_on_any_application_document_latches_shared_guard(application_host, existing):
    host = application_host
    if existing:
        host.uiapp.Application.OpenDocumentFile('existing.rvt')
    code = ("new_doc = app.Documents[0]\n" if existing else "new_doc = app.OpenDocumentFile('new.rvt')\n")
    response = execute(host, code + "raw = DB.Transaction(new_doc, 'Raw leaked')\nraw.Start()")
    assert response.status == 500 and response.data["unsafe"]
    assert response.data["effects"] == "unknown" and response.data["transaction_receipts"] == []
    assert any(item["stage"] == "document_postcondition" for item in response.data["cleanup_errors"])
    raw = host.db.created[0]
    assert raw.status == "Started" and not raw.disposed
    assert host.safety.snapshot()["blocked"]
    assert host.db.events == [("Raw leaked", "start")]
    host.opened[0].IsModifiable = False  # Later clean state does not reset the latch.
    again = execute(host, "app.OpenDocumentFile('must-not-open.rvt')")
    assert again.status == 409 and again.data["error_code"] == "mutation_blocked"
    doc_snapshot = host.reg.refresh_documents(host.uiapp.Application.Documents)
    document_ids = dict(host.ids, document_id=doc_snapshot["documents"][0]["document_id"])
    legacy = host.api.handlers["/execute_code/"](host.uiapp, SimpleNamespace(
        method="POST", data=dict(document_ids, code="doc.value = 99")))
    assert legacy.status == 409 and legacy.data["error_code"] == "mutation_blocked"
    assert len(host.opened) == 1 and host.opened[0].value == 0


def test_preblocked_instance_rejects_application_without_native_access(application_host):
    host = application_host
    host.safety.observe({"unsafe": True})
    class NoNativeAccess:
        def __getattr__(self, name):
            pytest.fail("Native access after safety rejection: " + name)
    response = host.api.handlers["/execute_application_code/"](NoNativeAccess(), SimpleNamespace(
        method="POST", data=dict(host.ids, code="pass")))
    assert response.status == 409 and response.data["error_code"] == "mutation_blocked"


def test_application_trial_rolls_back_and_closed_helper_is_accepted(application_host):
    host = application_host
    response = execute(host, """
helper = app.OpenDocumentFile('helper.rfa')
with execution.rollback_scope(helper, 'Trial'):
    with execution.transaction(helper, 'Flex'):
        helper.value = 42
assert helper.value == 0
helper.Close(False)
print('closed helper')
""")
    assert response.status == 200 and not response.data["unsafe"]
    assert response.data["owned_effects"] == "rolled_back" and response.data["effects"] == "unknown"
    assert response.data["document_notes"] == [{"stage": "document_closed"}]
    assert response.data["opened_documents"] == []
    assert all(item["disposed"] for item in response.data["transaction_receipts"])
    assert not host.safety.snapshot()["blocked"]


def test_committed_closed_helper_preserves_known_effects(application_host):
    response = execute(application_host, """
helper = app.OpenDocumentFile('helper.rfa')
with execution.transaction(helper, 'Edit'):
    helper.value = 42
helper.Close(False)
""")
    assert response.status == 200 and not response.data["unsafe"]
    assert response.data["owned_effects"] == "committed" and response.data["effects"] == "committed"
    assert response.data["document_notes"] == [{"stage": "document_closed"}]


def test_application_error_preserves_opened_registry_context_and_partial_output(application_host):
    response = execute(application_host, "print(u'雪')\nnew_doc = app.OpenDocumentFile('new.rvt')\nassert False",
                       script_name="C:\\client\\bootstrap.py")
    assert response.status == 500 and response.data["error_type"] == "AssertionError"
    assert response.data["partial_output"] == "雪\n" and not response.data["unsafe"]
    assert response.data["script_location"] == {"filename": "bootstrap.py", "line": 3, "column": None}
    assert response.data["actual_target"] == application_host.ids
    assert len(response.data["opened_documents"]) == 1


@pytest.mark.parametrize("via_file", [False, True])
async def test_real_client_directory_receiver_bootstrap_then_document_execution(application_host, tmp_path, via_file):
    from scripts.execute_revit_file import execute_application_script_file
    from tools.revit_transport import RevitTransportResult
    from tools.target_directory import TargetDirectory
    from tools.target_router import TargetRouter
    host = application_host
    directory = TargetDirectory()
    try:
        target = directory.observe(host.reg.snapshot())["target"]
        async def handshake(endpoint):
            assert endpoint == host.reg.snapshot()["endpoint"]
            return host.reg.snapshot()
        submitted = []
        async def request(method, url, **kwargs):
            payload = kwargs["data"]
            submitted.append(payload)
            endpoint = url[len(host.reg.snapshot()["endpoint"]):]
            response = host.api.handlers[endpoint](host.uiapp, SimpleNamespace(method=method, data=payload))
            return RevitTransportResult(method=method, url=url, status_code=response.status,
                                        json_received=True, body=response.data)
        router = TargetRouter(directory, handshake, request)
        code = "new_doc = app.OpenDocumentFile('fixture.rvt')\nwith execution.transaction(new_doc, 'Edit'):\n    new_doc.value = 42"
        if via_file:
            path = tmp_path / "bootstrap.py"
            path.write_text(code, encoding="utf-8")
            result = await execute_application_script_file(router, path, target=target)
            assert submitted[0]["script_name"] == "bootstrap.py"
            assert "file_path" not in submitted[0]
        else:
            result = await router.call("POST", "/execute_application_code/", target=target, data={"code": code})
        assert result.http_success and result.failure_kind is None and not result.revit_error
        assert result.body["actual_target"] == host.ids
        assert "document_id" not in submitted[0]
        # Existing registry and directory own both native token and client handle.
        metadata = directory.observe(host.reg.snapshot())
        assert metadata["documents"][0]["document_id"] == result.body["opened_documents"][0]["document_id"]
        handle = metadata["documents"][0]["document"]
        followup = await router.call("POST", "/execute_code/", target=target, document=handle,
                                     data={"code": "assert doc.value == 42\nprint('continued with selected document')"})
        assert followup.http_success and followup.failure_kind is None
        assert followup.body["actual_target"]["document_id"] == metadata["documents"][0]["document_id"]
    finally:
        directory.close()


def test_application_capture_budget_and_checkpoint_cleanup_are_shared(application_host):
    host = application_host
    streams = sys.stdout, sys.stderr
    result, status = host.execution.execute_application_payload({"code": """
import sys
print('abcdef')
sys.stderr.write('lost')
new_doc = app.OpenDocumentFile('fixture.rvt')
with execution.transaction(new_doc, 'Edit'):
    new_doc.value = 42
"""}, host.uiapp, output_limit_chars=3)
    assert status == 200 and result["output"] == "abc" and result["stderr"] == ""
    assert result["output_truncated"] and result["stderr_truncated"]
    assert result["effects"] == "committed"
    assert (sys.stdout, sys.stderr) == streams
    # Cancel at the script's checkpoint inside a scope: rollback only our work.
    calls = []
    def cancel():
        calls.append(True)
        return len(calls) == 3
    result, status = host.execution.execute_application_payload({"code": """
new_doc = app.OpenDocumentFile('cancel.rvt')
with execution.transaction(new_doc, 'Canceled edit'):
    new_doc.value = 99
    execution.checkpoint()
"""}, host.uiapp, cancellation_check=cancel)
    assert status == 500 and result["error_type"] == "ExecutionCanceled"
    assert result["owned_effects"] == "rolled_back" and not result["unsafe"]
    assert host.opened[-1].value == 0


def test_application_document_enumeration_failure_after_raw_work_is_unsafe(application_host):
    host = application_host
    response = execute(host, "app.OpenDocumentFile('new.rvt')\napp.Documents = None")
    assert response.status == 500 and response.data["unsafe"]
    assert response.data["effects"] == "unknown" and host.safety.snapshot()["blocked"]
    assert {item["stage"] for item in response.data["cleanup_errors"]} >= {
        "application_document_snapshot", "application_identity_snapshot"}


def test_application_latch_survives_new_route_registration_in_same_appdomain(application_host, monkeypatch):
    from revit_mcp.target_routing import SAFETY_SLOT, get_process_safety
    host = application_host
    slots = {SAFETY_SLOT: host.safety}
    domain = SimpleNamespace(GetData=slots.get, SetData=slots.__setitem__)
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(AppDomain=SimpleNamespace(CurrentDomain=domain)))
    assert get_process_safety() is host.safety
    first = execute(host, "new_doc = app.OpenDocumentFile('fixture.rvt')\nnew_doc.IsModifiable = True")
    assert first.status == 500 and first.data["unsafe"]
    host.opened[0].IsModifiable = False
    api = API()
    host.execution.register_code_execution_routes(TargetedAPI(api, lambda: host.reg, safety=get_process_safety()))
    response = api.handlers["/execute_application_code/"](host.uiapp, SimpleNamespace(
        method="POST", data=dict(host.ids, code="app.OpenDocumentFile('must-not-open.rvt')")))
    assert response.status == 409 and response.data["error_code"] == "mutation_blocked"
    assert slots[SAFETY_SLOT] is host.safety and host.safety.snapshot()["blocked"]
    assert len(host.opened) == 1


def test_receiver_postcondition_backstop_catches_native_handler_failure_with_new_document(application_host):
    host = application_host
    @host.proxy.route("/execute_application_code/", methods=["POST"])
    def native_failure(uiapp, request):
        new_doc = uiapp.Application.OpenDocumentFile('new.rvt')
        raw = host.db.Transaction(new_doc, 'Raw native failure')
        raw.Start()
        raise RuntimeError('Native handler failed outside the script runner')
    response = execute(host, "pass")
    assert response.status == 500 and response.data["unsafe"]
    assert response.data["effects"] == "unknown" and host.safety.snapshot()["blocked"]
    assert response.data["actual_target"] == host.ids
    assert response.data["cleanup_errors"][0]["stage"] == "routing_postcondition"
    assert host.db.created[0].status == "Started" and not host.db.created[0].disposed


def test_actual_application_registration_is_request_only_when_disabled(application_host):
    from revit_mcp.target_routing import DisabledAPI
    host = application_host
    api = API()
    proxy = DisabledAPI(api, lambda: host.reg)
    host.execution.register_code_execution_routes(proxy)
    receipt = proxy.assert_excluded(["/execute_code/", "/execute_application_code/"])
    assert receipt["legacy_api_excluded"]
    for endpoint in receipt["excluded_routes"]:
        assert list(inspect.signature(api.handlers[endpoint]).parameters) == ["request"]
        response = api.handlers[endpoint](SimpleNamespace())
        assert response.status == 503 and response.data["effects"] == "none"
        assert response.data["actual_target"] == host.ids
    assert host.opened == [] and host.db.created == []
