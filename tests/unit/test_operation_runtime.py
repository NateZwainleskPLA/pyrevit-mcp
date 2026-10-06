"""No Revit process needed: actual registry/runner concurrency and invariants."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from revit_mcp.operation_store import OperationStore, OperationError
from revit_mcp.execution_runtime import ExecutionRuntime
from revit_mcp.execution_routes import register_execution_routes


def payload(operation_id="one", **changes):
    value = dict(operation_id=operation_id, target="r17", document="d4", code="pass",
                 transaction_mode="script", description="trial", allow_ui_change=False)
    value.update(changes)
    return value


class Event:
    def __init__(self):
        self.raises, self.disposed = 0, False
        self.response = "Accepted"

    def Raise(self):
        self.raises += 1
        return self.response

    def Dispose(self):
        self.disposed = True


def runtime(execute=None, **options):
    store = options.pop("store", OperationStore("generation"))
    engine = ExecutionRuntime(store, lambda p: None, lambda p, a: object(),
                              execute or (lambda p, c: dict(state="succeeded", effects="none", result={})),
                              experimental=True, exclusive=True, **options)
    engine.bind_event(Event())
    return engine


def test_concurrent_duplicate_admits_and_executes_once():
    engine = runtime()
    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda _: engine.submit(payload()), range(100)))
    assert sum(created for _, created in results) == 1
    assert engine.event.raises == 1
    engine.on_external_event(None)
    assert engine.store.inspect("one")["state"] == "succeeded"
    assert not engine.command_running
    assert engine.store.take_next() is None


def test_changed_behavior_conflicts_before_full_queue():
    store = OperationStore("generation", max_queue=1)
    store.admit(payload())
    assert store.admit(payload())[1] is False
    for field, value in [("code", "print(1)"), ("description", "other"),
                         ("transaction_mode", "managed"), ("allow_ui_change", True),
                         ("document", "d5"), ("future_policy", {"dismiss": True})]:
        with pytest.raises(OperationError) as failure:
            store.admit(payload(**{field: value}))
        assert failure.value.code == "operation_conflict"
    with pytest.raises(OperationError) as failure:
        store.admit(payload("two"))
    assert failure.value.code == "queue_full"


def test_fifo_one_callback_per_operation_and_reentry():
    seen = []
    engine = runtime(lambda p, c: (seen.append(p["operation_id"]) or
                                  engine.on_external_event(None) or
                                  dict(state="succeeded", effects="none", result={})))
    for key in ("one", "two", "three"):
        engine.submit(payload(key))
    for index in range(3):
        engine.on_external_event(None)
        assert len(seen) == index + 1
    assert seen == ["one", "two", "three"]


def test_inspection_responsive_during_blocking_execution():
    started, release = threading.Event(), threading.Event()
    def execute(p, c):
        started.set()
        assert release.wait(3)
        return dict(state="succeeded", effects="none", result={})
    engine = runtime(execute)
    engine.submit(payload())
    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(engine.on_external_event, None)
        assert started.wait(2)
        assert engine.store.inspect("one")["state"] == "running"
        release.set()
        work.result(3)


def test_revalidation_error_never_enters_executor():
    engine = runtime(lambda p, c: pytest.fail("must not execute"))
    def reject(p, a):
        raise OperationError("closed_document", "Document wrapper no longer valid")
    engine.validate_api = reject
    engine.submit(payload())
    engine.on_external_event(None)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "none")


def test_cleanup_error_quarantines_and_refresh_cannot_strand_ownership():
    def refresh(_):
        raise RuntimeError("snapshot refresh failed")
    engine = runtime(lambda p, c: dict(state="succeeded", effects="rolled_back", result={},
                                      cleanup_errors=["Pending transaction"]), refresh=refresh)
    engine.submit(payload())
    engine.on_external_event(None)
    receipt = engine.store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "unknown")
    assert engine.quarantined and not engine.command_running
    assert engine.submit(payload())[1] is False
    with pytest.raises(OperationError):
        engine.submit(payload("two"))


def test_safe_disposal_waits_for_pending_callback_and_generation_expires():
    engine = runtime()
    event = engine.event
    engine.submit(payload())
    engine.stop()
    with pytest.raises(RuntimeError):
        engine.dispose_in_api_context()
    with pytest.raises(OperationError) as failure:
        engine.store.inspect("one")
    assert failure.value.code == "expired_runtime"
    engine.on_external_event(None)
    engine.dispose_in_api_context()
    assert event.disposed


def test_denied_wakeup_retains_admission_and_duplicate_retries_wakeup():
    engine = runtime()
    engine.event.response = "Denied"
    engine.submit(payload())
    assert engine.store.inspect("one")["state"] == "queued"
    engine.event.response = "Accepted"
    assert engine.submit(payload())[1] is False
    assert engine.event.raises == 2


def test_registry_bounds_and_expired_receipt_does_not_replay():
    now = [0]
    store = OperationStore("generation", max_operations=1, max_receipt_bytes=100,
                           retention_seconds=2, clock=lambda: now[0])
    store.admit(payload())
    store.take_next()
    store.complete("one", "succeeded", "committed", {"output": "x" * 1000})
    assert store.inspect("one")["result"]["receipt_truncated"]
    now[0] = 3
    assert store.admit(payload())[0]["receipt_expired"]
    assert not store.has_queued()
    with pytest.raises(OperationError) as failure:
        store.admit(payload("two"))
    assert failure.value.code == "registry_full"


def test_live_wrappers_cannot_enter_registry():
    with pytest.raises(TypeError):
        OperationStore("generation").admit(payload(wrapper=object()))


def test_disabled_without_exclusive_opt_in():
    engine = ExecutionRuntime(OperationStore("generation"), lambda p: None,
                              lambda p, a: None, lambda p, c: None, experimental=True)
    engine.bind_event(Event())
    with pytest.raises(OperationError) as failure:
        engine.submit(payload())
    assert failure.value.code == "runtime_disabled"


def test_http_handlers_have_no_api_context_parameters_and_reject_wrong_target():
    class API:
        def __init__(self):
            self.handlers = {}
        def route(self, path, methods):
            def register(fn):
                self.handlers[path] = fn
                return fn
            return register
    engine, api = runtime(), API()
    register_execution_routes(api, engine, lambda **kw: kw)
    import inspect
    assert all(list(inspect.signature(fn).parameters) == ["request"] for fn in api.handlers.values())
    submitted = api.handlers["/operations/submit/"](SimpleNamespace(data=payload()))
    assert submitted["status"] == 202
    inspected = api.handlers["/operations/inspect/"](SimpleNamespace(data=payload(target="r18")))
    assert inspected["status"] == 409
