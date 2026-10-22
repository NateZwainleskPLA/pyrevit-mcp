# -*- coding: utf-8 -*-
"""Connector side of the bridge token: storage, extraction, and the root API guard."""
import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from revit_mcp import bridge_auth
from revit_mcp.bridge_auth import (AuthenticatedAPI, BridgeAuthError, get_or_create_token, take_token,
                                   token_path, tokens_equal)
from tests.unit.test_receiver_target_routing import API

OTHER = "f" * 64


@pytest.fixture
def routes(monkeypatch):
    routes = SimpleNamespace(make_response=lambda data, status=200, headers=None:
                             SimpleNamespace(data=data, status=status, headers=headers or {}))
    monkeypatch.setitem(sys.modules, "pyrevit", SimpleNamespace(routes=routes))
    return routes


def test_token_is_created_once_under_localappdata(tmp_path):
    token = get_or_create_token()
    assert len(token) == 64 and set(token) <= set("0123456789abcdef")
    assert token_path() == str(tmp_path / "RevitMCP" / "bridge-token")
    assert get_or_create_token() == token
    assert os.listdir(str(tmp_path / "RevitMCP")) == ["bridge-token"]


def test_concurrent_creator_wins_and_staging_is_removed(tmp_path, monkeypatch):
    def lose_race(staging, path):
        with open(path, "w") as stream:  # The other side created it first...
            stream.write(OTHER)
        raise OSError("exists")  # ...so the Windows rename refuses to replace it.

    monkeypatch.setattr(bridge_auth.os, "rename", lose_race)
    assert get_or_create_token() == OTHER
    assert os.listdir(str(tmp_path / "RevitMCP")) == ["bridge-token"]


def test_corrupt_token_file_is_reported_not_replaced(tmp_path):
    path = tmp_path / "RevitMCP" / "bridge-token"
    path.parent.mkdir()
    path.write_text("not a token")
    with pytest.raises(BridgeAuthError) as error:
        get_or_create_token()
    assert error.value.code == "bridge_token_invalid"
    assert path.read_text() == "not a token"


def test_token_is_removed_from_every_body_shape():
    for data in ({"bridge_token": OTHER, "code": "x"}, '{"bridge_token": "%s", "code": "x"}' % OTHER,
                 ('{"bridge_token": "%s", "code": "x"}' % OTHER).encode("utf-8")):
        request = SimpleNamespace(data=data, query_params={})
        assert take_token(request) == OTHER
        assert request.data == {"code": "x"}  # Handlers and receipts never see it.
    for data in (None, "", "[1]", "not json", b"\xff"):
        assert take_token(SimpleNamespace(data=data, query_params={})) is None


def test_token_in_url_is_removed_and_refused():
    request = SimpleNamespace(data={"bridge_token": OTHER}, query_params={"bridge_token": OTHER, "x": "1"})
    with pytest.raises(BridgeAuthError) as error:
        take_token(request)
    assert error.value.code == "bridge_token_in_url"
    assert request.query_params == {"x": "1"}


def test_token_comparison():
    assert tokens_equal(OTHER, OTHER)
    assert not tokens_equal(OTHER, "e" + OTHER[1:])
    assert not tokens_equal(OTHER, OTHER[:-1])


@pytest.mark.parametrize("signature", [
    "def handler(uiapp, request): return locals()",
    "def handler(doc, request, view_name): return locals()",
    "def handler(): return {}",
    "def handler(uiapp, instance_id=None, runtime_id=None, request=None): return locals()",
])
def test_guard_keeps_the_argument_names_pyrevit_dispatches_on(signature, routes):
    scope = {}
    exec(signature, scope)
    handler = scope["handler"]
    api = API()
    routed = AuthenticatedAPI(api).route("/x/", methods=["POST"])(handler)
    names = list(inspect.signature(handler).parameters)
    assert list(inspect.signature(routed).parameters) == (names if "request" in names else names + ["request"])
    assert api.handlers["/x/"] is routed


def test_guard_rejects_before_the_handler_and_strips_the_token(routes):
    token = get_or_create_token()
    handler = Mock(return_value={"status": "success"})

    def execute(uiapp, request):
        return handler(uiapp, dict(request.data))

    routed = AuthenticatedAPI(API()).route("/execute_code/", methods=["POST"])(execute)
    for data in ({"code": "x"}, {"code": "x", "bridge_token": OTHER}, {"code": "x", "bridge_token": "short"},
                 '{"code": "x"}', None):
        response = routed(uiapp="app", request=SimpleNamespace(data=data, query_params={}))
        assert response.status == 401 and response.data["error_code"] == "bridge_unauthorized"
        assert response.data["effects"] == "none"
    handler.assert_not_called()

    assert routed(uiapp="app", request=SimpleNamespace(
        data={"code": "x", "bridge_token": token}, query_params={})) == {"status": "success"}
    handler.assert_called_once_with("app", {"code": "x"})


def test_guard_strips_callback_even_with_a_valid_token(routes):
    handler = Mock()
    routed = AuthenticatedAPI(API()).route("/metadata/", methods=["GET"])(lambda: handler())
    request = SimpleNamespace(data={"bridge_token": get_or_create_token(), "callbackUrl": "http://x/"},
                              query_params={})
    response = routed(request=request)
    assert response.status == 409 and response.data["error_code"] == "callback_unsupported"
    assert "callbackUrl" not in request.data
    handler.assert_not_called()


def test_unreadable_connector_token_is_a_server_error(tmp_path, routes):
    (tmp_path / "RevitMCP").mkdir()
    (tmp_path / "RevitMCP" / "bridge-token").write_text("corrupt")
    routed = AuthenticatedAPI(API()).route("/status/", methods=["GET"])(lambda uiapp, request: {})
    response = routed(uiapp=None, request=SimpleNamespace(data={"bridge_token": OTHER}, query_params={}))
    assert response.status == 503 and response.data["error_code"] == "bridge_token_invalid"


def test_variadic_handlers_are_refused_at_registration(routes):
    with pytest.raises(ValueError, match="named arguments"):
        AuthenticatedAPI(API()).route("/x/")(lambda request, **kwargs: None)
