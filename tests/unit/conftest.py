# -*- coding: utf-8 -*-
"""Unit tests never read or create the real bridge token or inspect real listeners."""
import pytest

TEST_TOKEN = "0123456789abcdef" * 4


@pytest.fixture(autouse=True)
def isolated_bridge_token(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("REVIT_MCP_BRIDGE_TOKEN", raising=False)
    monkeypatch.setattr("tools.bridge_token.token_for", lambda url: TEST_TOKEN)
    return TEST_TOKEN
