from unittest.mock import AsyncMock

import anyio
import pytest

from revit_mcp.routing_policy import RoutingPolicyError
from tools.target_router import TargetRouter


class Directory:
    def __init__(self):
        self.resolutions = {
            "r1": dict(endpoint="http://127.0.0.1:49001/revit_mcp", instance_id="instance1", runtime_id="runtime1", document_id="doc1"),
            "r2": dict(endpoint="http://revit.remote:49002/revit_mcp", instance_id="instance2", runtime_id="runtime2", document_id="doc2"),
        }

    async def revalidate(self, target, handshake):
        await handshake(self.resolutions[target]["endpoint"])

    def resolve(self, target, document):
        if document and document != "d" + target[1:]:
            raise ValueError("crossed document")
        return dict(self.resolutions[target])


async def test_two_interleaved_targets_and_remote_host_keep_independent_destinations():
    arrived = anyio.Event()
    release = anyio.Event()
    calls = []

    async def request(method, url, **kwargs):
        if "49001" in url:
            arrived.set()
            await release.wait()
        calls.append((url, kwargs))

    router = TargetRouter(Directory(), AsyncMock(), request)
    async with anyio.create_task_group() as group:
        group.start_soon(_invoke, router, "r1", "d1")
        await arrived.wait()
        await router.call("POST", "/execute_code/", target="r2", document="d2", data={"code": "two"})
        release.set()
    assert calls[0][0] == "http://revit.remote:49002/revit_mcp/execute_code/"
    assert calls[0][1]["data"]["instance_id"] == "instance2"
    assert calls[1][1]["data"]["document_id"] == "doc1"


async def _invoke(router, target, document):
    await router.call("POST", "/execute_code/", target=target, document=document, data={"code": "one"})


@pytest.mark.parametrize("target,document", [(None, "d1"), ("r1", None), ("r1", "d2"), ("unknown", "d1")])
async def test_invalid_handles_never_send_execution(target, document):
    request = AsyncMock()
    router = TargetRouter(Directory(), AsyncMock(), request)
    with pytest.raises((ValueError, KeyError)):
        await router.call("POST", "/execute_code/", target=target, document=document)
    request.assert_not_awaited()


async def test_get_conveys_full_identities_and_does_not_mutate_input():
    request = AsyncMock()
    params = {"limit": 3}
    router = TargetRouter(Directory(), AsyncMock(), request)
    await router.call("GET", "/list_levels/", target="r1", document="d1", params=params)
    assert params == {"limit": 3}
    assert request.await_args.kwargs["params"] == {
        "limit": 3, "instance_id": "instance1", "runtime_id": "runtime1",
        "document_id": "doc1", "allow_ui_change": "false"
    }


async def test_failed_handshake_never_sends_or_retries_mutation():
    request = AsyncMock()
    router = TargetRouter(Directory(), AsyncMock(side_effect=ValueError("port reused")), request)
    with pytest.raises(ValueError, match="port reused"):
        await router.call("POST", "/execute_code/", target="r1", document="d1")
    request.assert_not_awaited()


async def test_reserved_identity_cannot_be_overridden():
    router = TargetRouter(Directory(), AsyncMock(), AsyncMock())
    with pytest.raises(RoutingPolicyError) as exc:
        await router.call("POST", "/execute_code/", target="r1", document="d1", data={"instance_id": "other"})
    assert exc.value.code == "reserved_identity"
    router.request.assert_not_awaited()
