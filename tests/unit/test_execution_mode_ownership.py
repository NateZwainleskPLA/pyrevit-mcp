import threading
import sys
from types import SimpleNamespace

import pytest

from revit_mcp.execution_safety import ExecutionSafety
from revit_mcp.routing_policy import ROUTES
from revit_mcp import execution_runtime as module
from tests.unit.test_execution_identity_integration import setup
from tests.unit.test_operation_runtime import Event
from tests.unit.test_startup_private_owner import startup_host, load_startup


def exclusion_receipt():
    paths = set(path for path in ROUTES if not path.startswith("/operations/"))
    paths.remove("/get_view/")
    paths.update(("/get_view/<view_name>", "/metadata/refresh/"))
    return dict(legacy_api_excluded=True, private_runtime_reload_guard=True, excluded_routes=list(paths))


def configured(monkeypatch):
    import revit_mcp.target_routing as routing
    owner = dict(lock=threading.RLock(), safety=ExecutionSafety(), runtime=None)
    slots = {routing.PRIVATE_OWNER_SLOT: owner, routing.SAFETY_SLOT: owner["safety"]}
    domain = SimpleNamespace(GetData=slots.get, SetData=slots.__setitem__)
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(AppDomain=SimpleNamespace(CurrentDomain=domain)))
    monkeypatch.setattr(module, "get_process_owner_state", lambda: owner)
    monkeypatch.setattr(routing, "get_process_safety", lambda: owner["safety"])
    def create(engine):
        engine.bind_event(Event())
        return engine
    monkeypatch.setattr(module, "_create_external_event", create)
    return owner


def test_factory_refuses_boolean_only_and_incomplete_exclusion():
    engine, adapter, reg, uiapp, value, a, b = setup()
    with pytest.raises(ValueError, match="exclusion"):
        module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                                           experimental=True, exclusive=True)
    partial = exclusion_receipt()
    partial["excluded_routes"].remove("/metadata/refresh/")
    with pytest.raises(ValueError, match="exclusion"):
        module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                     experimental=True, exclusive=True, exclusion_receipt=partial)
    missing_application = exclusion_receipt()
    missing_application["excluded_routes"].remove("/execute_application_code/")
    with pytest.raises(ValueError, match="exclusion"):
        module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                     experimental=True, exclusive=True, exclusion_receipt=missing_application)
    missing_reload = exclusion_receipt()
    missing_reload.pop("private_runtime_reload_guard")
    with pytest.raises(ValueError, match="reload guard"):
        module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                     experimental=True, exclusive=True, exclusion_receipt=missing_reload)


def test_one_process_lane_until_safe_disposal_even_across_generation(monkeypatch):
    owner = configured(monkeypatch)
    _, adapter, reg, uiapp, value, a, b = setup()
    engine = module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                 experimental=True, exclusive=True, exclusion_receipt=exclusion_receipt())
    assert engine.adapter.safety is owner["safety"]
    _, second_adapter, second_reg, second_uiapp, _, _, _ = setup()
    with pytest.raises(RuntimeError, match="private execution lane owns"):
        module.build_runtime_in_api_context(second_reg, second_uiapp, second_adapter.execute_payload,
            experimental=True, exclusive=True, exclusion_receipt=exclusion_receipt())
    engine.submit(value)
    engine.stop()
    assert reg.snapshot()["runtime_available"] is False
    with pytest.raises(RuntimeError):
        engine.dispose_in_api_context()
    assert owner["runtime"] is engine
    engine.on_external_event(uiapp)
    engine.dispose_in_api_context()
    assert owner["runtime"] is None
    new = module.build_runtime_in_api_context(second_reg, second_uiapp, second_adapter.execute_payload,
            experimental=True, exclusive=True, exclusion_receipt=exclusion_receipt())
    assert owner["runtime"] is new


def test_disposal_failure_keeps_lease_and_prevents_replacement(monkeypatch):
    owner = configured(monkeypatch)
    _, adapter, reg, uiapp, _, _, _ = setup()
    engine = module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
            experimental=True, exclusive=True, exclusion_receipt=exclusion_receipt())
    engine.event.Dispose = lambda: (_ for _ in ()).throw(RuntimeError("dispose failed"))
    engine.stop()
    with pytest.raises(RuntimeError, match="dispose failed"):
        engine.dispose_in_api_context()
    assert owner["runtime"] is engine and engine.event is not None


def test_factory_disabled_without_side_effect_of_event_creation(monkeypatch):
    _, adapter, reg, uiapp, _, _, _ = setup()
    monkeypatch.setattr(module, "_create_external_event", lambda _: pytest.fail("must not create event"))
    engine = module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload)
    assert not engine.enabled and engine.event is None


def test_cannot_supply_independent_safety_map(monkeypatch):
    configured(monkeypatch)
    _, adapter, reg, uiapp, _, _, _ = setup()
    other = dict(lock=threading.RLock(), safety=ExecutionSafety())
    with pytest.raises(ValueError, match="shared process"):
        module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
            experimental=True, exclusive=True, owner_state=other, exclusion_receipt=exclusion_receipt())


def test_factory_consumes_actual_guarded_startup_receipt_and_blocks_later_reload(startup_host, monkeypatch):
    slots, domain, api, initialize, events = startup_host
    loaded = load_startup()
    receipt = loaded["register_routes"](legacy_api_enabled=False)
    assert receipt["private_runtime_reload_guard"] is True
    _, adapter, reg, uiapp, _, _, _ = setup()
    monkeypatch.setattr(module, "_create_external_event", lambda engine: engine.bind_event(Event()))
    engine = module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                  experimental=True, exclusive=True, exclusion_receipt=receipt)
    assert engine.enabled and engine.adapter.safety is slots["revit_mcp.routing.safety.v1"]
    assert slots[module.OWNER_SLOT]["runtime"] is engine
    prior_calls, prior_handlers = initialize.call_count, dict(api.handlers)
    with pytest.raises(RuntimeError, match="private execution lane owns"):
        loaded["register_routes"]()
    assert initialize.call_count == prior_calls and api.handlers == prior_handlers
    engine.stop()
    engine.dispose_in_api_context()
    assert slots[module.OWNER_SLOT]["runtime"] is None


def test_partial_event_creation_keeps_lease_until_unbound_event_disposal(monkeypatch):
    owner = configured(monkeypatch)
    _, adapter, reg, uiapp, _, _, _ = setup()
    event = Event()
    def fail_binding(engine):
        engine._unbound_event = event
        raise RuntimeError("binding failed after creation")
    monkeypatch.setattr(module, "_create_external_event", fail_binding)
    with pytest.raises(RuntimeError, match="binding failed"):
        module.build_runtime_in_api_context(reg, uiapp, adapter.execute_payload,
                    experimental=True, exclusive=True, exclusion_receipt=exclusion_receipt())
    retained = owner["runtime"]
    assert retained is not None and retained.stopping
    retained.dispose_in_api_context()
    assert event.disposed and owner["runtime"] is None
