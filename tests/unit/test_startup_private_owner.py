"""Reload composition cannot enable a second execution mechanism."""
import inspect
import runpy
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from revit_mcp.execution_safety import ExecutionSafety
from revit_mcp.routing_policy import ROUTES
from revit_mcp.target_routing import PRIVATE_OWNER_SLOT, SAFETY_SLOT, startup_owner_guard
from tests.unit.test_receiver_target_routing import API


@pytest.fixture
def startup_host(monkeypatch):
    safety = ExecutionSafety()
    slots = {SAFETY_SLOT: safety}
    domain = SimpleNamespace(GetData=slots.get, SetData=Mock(side_effect=slots.__setitem__))
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(AppDomain=SimpleNamespace(CurrentDomain=domain)))
    api = API()
    monkeypatch.setitem(sys.modules, "pyrevit", SimpleNamespace(routes=SimpleNamespace(API=lambda name: api)))
    events = []

    def initialize(metadata_api):
        events.append("identity")
        metadata_api.route("/metadata/", methods=["GET"])(lambda: {})
        def refresh(uiapp):
            return {}
        metadata_api.route("/metadata/refresh/", methods=["GET"])(refresh)
    initialize_mock = Mock(side_effect=initialize)
    monkeypatch.setitem(sys.modules, "revit_mcp.target_runtime", SimpleNamespace(initialize_identity=initialize_mock))
    paths = [path for path in ROUTES if not path.startswith("/operations/")]
    paths.remove("/get_view/")
    paths.append("/get_view/<view_name>")
    registrations = (("status", "register_status_routes"), ("model_info", "register_model_info_routes"),
                     ("views", "register_views_routes"), ("placement", "register_placement_routes"),
                     ("colors", "register_color_routes"), ("code_execution", "register_code_execution_routes"),
                     ("document", "register_document_routes"))
    for index, (module_name, function_name) in enumerate(registrations):
        def register(route_api, paths=paths[index::len(registrations)]):
            events.append("routes")
            for path in paths:
                def handler(doc, request):
                    return {}
                route_api.route(path, methods=["POST"])(handler)
        monkeypatch.setitem(sys.modules, "revit_mcp." + module_name,
                            SimpleNamespace(**{function_name: register}))
    return slots, domain, api, initialize_mock, events


def load_startup():
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "startup.py"))


@pytest.mark.parametrize("state", ["running", "stopping", "pending", "disposed_but_lease_retained"])
def test_retained_private_lease_rejects_default_reload_before_identity(startup_host, state):
    slots, domain, api, initialize, events = startup_host
    runtime = SimpleNamespace(state=state)
    owner = {"lock": threading.RLock(), "runtime": runtime, "safety": slots[SAFETY_SLOT]}
    slots[PRIVATE_OWNER_SLOT] = owner
    with pytest.raises(RuntimeError, match="private execution lane owns"):
        load_startup()
    initialize.assert_not_called()
    assert events == [] and api.handlers == {}
    assert owner["runtime"] is runtime
    domain.SetData.assert_not_called()


def test_no_private_owner_keeps_default_synchronous_startup(startup_host):
    slots, domain, api, initialize, events = startup_host
    loaded = load_startup()
    assert events[0] == "identity"
    assert list(inspect.signature(api.handlers["/save_document/"]).parameters) == ["uiapp", "request"]
    assert list(inspect.signature(api.handlers["/execute_application_code/"]).parameters) == ["uiapp", "request"]
    assert loaded["register_routes"]()["legacy_api_excluded"] is False
    domain.SetData.assert_not_called()


def test_idle_owner_preserves_shared_safety_and_holds_lock_through_initialization(startup_host):
    slots, domain, api, initialize, events = startup_host
    owner = {"lock": threading.RLock(), "runtime": None, "safety": slots[SAFETY_SLOT]}
    slots[PRIVATE_OWNER_SLOT] = owner
    attempts = []
    previous = initialize.side_effect
    def initializer(metadata_api):
        def probe():
            acquired = owner["lock"].acquire(False)
            attempts.append(acquired)
            if acquired:
                owner["lock"].release()
        worker = threading.Thread(target=probe)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        return previous(metadata_api)
    initialize.side_effect = initializer
    load_startup()
    assert attempts == [False]
    assert owner["runtime"] is None
    assert owner["safety"] is slots[SAFETY_SLOT]
    domain.SetData.assert_not_called()


@pytest.mark.parametrize("owner", [object(), {}, {"lock": None, "runtime": None, "safety": None},
                                    {"lock": threading.RLock(), "runtime": None, "safety": ExecutionSafety()}])
def test_corrupt_or_mismatched_retained_owner_fails_before_identity(startup_host, owner):
    slots, domain, api, initialize, events = startup_host
    slots[PRIVATE_OWNER_SLOT] = owner
    with pytest.raises(RuntimeError):
        load_startup()
    initialize.assert_not_called()
    assert api.handlers == {}
    assert slots[PRIVATE_OWNER_SLOT] is owner


def test_unreadable_retained_owner_fails_closed_before_identity(startup_host):
    slots, domain, api, initialize, events = startup_host
    domain.GetData = Mock(side_effect=RuntimeError("cross-engine object unavailable"))
    with pytest.raises(RuntimeError, match="owner is unreadable"):
        load_startup()
    initialize.assert_not_called()
    assert api.handlers == {}


def test_busy_owner_lock_rejects_startup_instead_of_waiting_indefinitely(startup_host):
    slots, domain, api, initialize, events = startup_host
    lock = Mock(acquire=Mock(return_value=False), release=Mock())
    slots[PRIVATE_OWNER_SLOT] = {"lock": lock, "runtime": None, "safety": slots[SAFETY_SLOT]}
    with pytest.raises(RuntimeError, match="owner is busy"):
        load_startup()
    lock.acquire.assert_called_once_with(False)
    lock.release.assert_not_called()
    initialize.assert_not_called()


def test_releasing_lease_allows_later_sync_startup_without_resetting_safety(startup_host):
    slots, domain, api, initialize, events = startup_host
    safety = slots[SAFETY_SLOT]
    safety.observe({"unsafe": True})
    owner = {"lock": threading.RLock(), "runtime": object(), "safety": safety}
    slots[PRIVATE_OWNER_SLOT] = owner
    with pytest.raises(RuntimeError):
        load_startup()
    owner["runtime"] = None  # Simulated operations-owner release after safe disposal.
    load_startup()
    assert safety.snapshot()["blocked"]
    assert slots[SAFETY_SLOT] is safety


def test_explicit_disabled_mode_still_registers_only_http_rejections(startup_host):
    slots, domain, api, initialize, events = startup_host
    loaded = load_startup()
    receipt = loaded["register_routes"](legacy_api_enabled=False)
    assert receipt["legacy_api_excluded"]
    assert receipt["private_runtime_reload_guard"] is True
    assert "/execute_application_code/" in receipt["excluded_routes"]
    for path in receipt["excluded_routes"]:
        assert list(inspect.signature(api.handlers[path]).parameters) == ["request"]


def test_disabled_receipt_is_not_issued_after_private_lease_acquisition(startup_host):
    slots, domain, api, initialize, events = startup_host
    loaded = load_startup()
    owner = {"lock": threading.RLock(), "runtime": object(), "safety": slots[SAFETY_SLOT]}
    slots[PRIVATE_OWNER_SLOT] = owner
    initialize.reset_mock()
    prior_handlers = dict(api.handlers)
    with pytest.raises(RuntimeError, match="private execution lane owns"):
        loaded["register_routes"](legacy_api_enabled=False)
    initialize.assert_not_called()
    assert api.handlers == prior_handlers
