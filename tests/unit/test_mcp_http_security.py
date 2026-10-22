# -*- coding: utf-8 -*-
"""main.py's HTTP transports accept only loopback Host/Origin headers.

A DNS-rebinding page reaches 127.0.0.1 under its own hostname, so its Host
header is foreign. A cross-site page sends its own Origin. Either one must be
rejected before a tool such as execute_revit_code can run.
"""
from starlette.testclient import TestClient

from main import mcp

INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "security-test", "version": "1.0"}}}
ACCEPT = {"Accept": "application/json, text/event-stream"}


def test_streamable_http_rejects_foreign_host_and_origin():
    with TestClient(mcp.streamable_http_app(), base_url="http://127.0.0.1:8000") as client:
        path = mcp.settings.streamable_http_path
        rebound = client.post(path, json=INITIALIZE, headers=dict(ACCEPT, host="attacker.example:8000"))
        assert rebound.status_code == 421
        cross_site = client.post(path, json=INITIALIZE, headers=dict(ACCEPT, origin="https://attacker.example"))
        assert cross_site.status_code == 403
        simple_form = client.post(path, content=b"{}", headers=dict(ACCEPT, **{"content-type": "text/plain"}))
        assert simple_form.status_code == 400
        local = client.post(path, json=INITIALIZE, headers=dict(ACCEPT, origin="http://localhost:6274"))
        assert local.status_code == 200
