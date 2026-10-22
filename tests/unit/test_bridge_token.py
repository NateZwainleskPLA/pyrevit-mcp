# -*- coding: utf-8 -*-
"""Client side of the bridge token: who may receive it, and how it travels."""
import json
import os
import socket

import httpx
import pytest

from revit_mcp.bridge_auth import get_or_create_token
from revit_mcp.identity import IdentityError
from tools.bridge_token import token_for  # The real provider; conftest stubs the module attribute.
from tools.revit_transport import request_revit
from tools.target_discovery import metadata_handshake

OTHER = "f" * 64
windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows listener ownership")


@windows_only
def test_loopback_token_requires_current_user_listeners(monkeypatch):
    ports = []
    monkeypatch.setattr("tools.windows_target_evidence.require_current_user_listeners", ports.append)
    assert token_for("http://127.0.0.1:48886/revit_mcp/status/") == get_or_create_token()
    assert token_for("http://[::1]/revit_mcp") == get_or_create_token()
    assert ports == [48886, 80]

    def refuse(port):
        raise IdentityError("untrusted_listener", "foreign")
    monkeypatch.setattr("tools.windows_target_evidence.require_current_user_listeners", refuse)
    with pytest.raises(IdentityError) as error:
        token_for("http://localhost:48886/revit_mcp")
    assert error.value.code == "untrusted_listener"


@windows_only
def test_live_listener_ownership():
    from tools.windows_target_evidence import require_current_user_listeners
    with socket.socket() as own:
        own.bind(("127.0.0.1", 0))
        own.listen(1)
        require_current_user_listeners(own.getsockname()[1])
    with pytest.raises(IdentityError) as error:
        require_current_user_listeners(135)  # RPC endpoint mapper, owned by a service account.
    assert error.value.code == "untrusted_listener"


def test_remote_hosts_need_an_explicit_token(monkeypatch):
    with pytest.raises(IdentityError) as error:
        token_for("http://revit-vm:48884/revit_mcp")
    assert error.value.code == "bridge_token_unavailable"
    monkeypatch.setenv("REVIT_MCP_BRIDGE_TOKEN", OTHER)
    assert token_for("http://revit-vm:48884/revit_mcp") == OTHER
    monkeypatch.setenv("REVIT_MCP_BRIDGE_TOKEN", "too-short")
    with pytest.raises(IdentityError):
        token_for("http://revit-vm:48884/revit_mcp")


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_transport_sends_token_in_body_never_url(method, isolated_bridge_token):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await request_revit(method, "http://127.0.0.1:48884/revit_mcp/status/",
                            data={"code": "x"} if method == "POST" else None,
                            params={"instance_id": "i"}, client=client)
    (request,) = seen
    assert "bridge_token" not in str(request.url)
    body = json.loads(request.content)
    assert body == dict({"bridge_token": isolated_bridge_token}, **({"code": "x"} if method == "POST" else {}))


async def test_refused_token_means_nothing_is_sent(monkeypatch):
    def refuse(url):
        raise IdentityError("untrusted_listener", "foreign listener")
    monkeypatch.setattr("tools.bridge_token.token_for", refuse)
    sent = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(sent.append)) as client:
        result = await request_revit("POST", "http://127.0.0.1:48884/revit_mcp/execute_code/",
                                     data={"code": "x"}, client=client)
    assert sent == []
    assert result.failure_kind == "request_error" and not result.mutation_outcome_unknown
    with pytest.raises(IdentityError) as error:
        await metadata_handshake("http://127.0.0.1:48884/revit_mcp")
    assert error.value.code == "untrusted_listener"


async def test_handshake_reports_a_rejected_token(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, method, url, json=None):
            return httpx.Response(401, request=httpx.Request(method, url), json={"error_code": "bridge_unauthorized"})
    monkeypatch.setattr("tools.target_discovery.httpx.AsyncClient", Client)
    with pytest.raises(IdentityError) as error:
        await metadata_handshake("http://127.0.0.1:48884/revit_mcp")
    assert error.value.code == "bridge_unauthorized"
