"""Real directory/registry/receiver integration with simulated API callbacks."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from revit_mcp.identity import IdentityError
from revit_mcp.target_routing import TargetedAPI
from tools.revit_transport import RevitTransportResult
from tools.target_directory import TargetDirectory
from tools.target_router import TargetRouter
from tests.unit.test_receiver_target_routing import API
from tests.unit.test_target_identity import Document, registry


@pytest.fixture
def connected(monkeypatch):
    routes = SimpleNamespace(make_response=lambda data, status=200, headers=None:
                             SimpleNamespace(data=data, status=status, headers=headers or {}))
    monkeypatch.setitem(sys.modules, "pyrevit", SimpleNamespace(routes=routes))
    targets = []
    directory = TargetDirectory()
    executions = []
    hosts = {}
    for number, hostname in enumerate(("localhost", "remote.host"), 1):
        endpoint = "http://%s:%s/revit_mcp" % (hostname, 49000 + number)
        reg = registry(process_id=number, endpoint=endpoint)
        a, b = Document(), Document()
        uiapp = SimpleNamespace(Application=SimpleNamespace(Documents=[a, b]),
                                ActiveUIDocument=SimpleNamespace(Document=a))
        descriptor = directory.observe(reg.refresh_documents([a, b], a))
        targets.append((descriptor["target"], descriptor["documents"][0]["document"], a))
        api = API()

        @TargetedAPI(api, lambda reg=reg: reg).route("/save_document/", methods=["POST"])
        def save(doc, request):
            executions.append(doc)
            return {"status": "success", "message": doc.Title}

        hosts[endpoint] = dict(registry=reg, uiapp=uiapp, handler=save)

    async def handshake(endpoint):
        return hosts[endpoint]["registry"].snapshot()

    before_execution = Mock()

    async def request(method, url, **kwargs):
        endpoint = url.removesuffix("/save_document/")
        host = hosts[endpoint]
        before_execution(host)
        response = host["handler"](host["uiapp"], SimpleNamespace(method=method, data=kwargs["data"]))
        return RevitTransportResult(method=method, url=url, status_code=response.status,
                                    json_received=True, body=response.data)

    router = TargetRouter(directory, handshake, request)
    yield router, targets, hosts, executions, before_execution
    directory.close()


async def test_interleaved_remote_and_local_handles_execute_their_own_documents(connected):
    router, targets, hosts, executions, before = connected
    for index in (0, 1, 0, 1):
        target, document, doc = targets[index]
        result = await router.call("POST", "/save_document/", target=target, document=document)
        assert result.http_success
        assert result.body["actual_target"]["document_id"] == router.directory.resolve(target, document)["document_id"]
        assert executions[-1] is doc


async def test_port_reuse_after_handshake_fails_at_receiver(connected):
    router, targets, hosts, executions, before = connected
    target, document, _ = targets[0]
    endpoint = router.directory.resolve(target)["endpoint"]
    old_handler = hosts[endpoint]["handler"]

    def replace(host):
        new = registry(endpoint=endpoint)
        api = API()

        @TargetedAPI(api, lambda: new).route("/save_document/", methods=["POST"])
        def never(doc, request):
            pytest.fail("Wrong-target mutation executed")
        host["handler"] = never

    before.side_effect = replace
    result = await router.call("POST", "/save_document/", target=target, document=document)
    assert result.status_code == 409
    assert result.body["error_code"] == "stale_target"
    assert executions == []


async def test_crossed_document_handles_fail_before_sending(connected):
    router, targets, hosts, executions, before = connected
    with pytest.raises(IdentityError) as exc:
        await router.call("POST", "/save_document/", target=targets[0][0], document=targets[1][1])
    assert exc.value.code == "cross_target_document"
    before.assert_not_called()
    assert executions == []


async def test_active_doc_switch_after_admission_keeps_explicit_database_doc(connected):
    router, targets, hosts, executions, before = connected
    def switch(host):
        host["uiapp"].ActiveUIDocument = SimpleNamespace(Document=host["uiapp"].Application.Documents[1])
    before.side_effect = switch
    result = await router.call("POST", "/save_document/", target=targets[0][0], document=targets[0][1])
    assert result.http_success
    assert executions == [targets[0][2]]


async def test_closed_document_after_admission_never_executes(connected):
    router, targets, hosts, executions, before = connected
    def close(host):
        host["uiapp"].Application.Documents[0].IsValidObject = False
        host["uiapp"].Application.Documents = host["uiapp"].Application.Documents[1:]
        host["uiapp"].ActiveUIDocument = None
    before.side_effect = close
    result = await router.call("POST", "/save_document/", target=targets[0][0], document=targets[0][1])
    assert result.status_code == 409
    assert executions == []
