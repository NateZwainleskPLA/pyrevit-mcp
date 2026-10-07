import threading
from concurrent.futures import ThreadPoolExecutor

from revit_mcp.operation_store import OperationStore
from tests.unit.test_operation_runtime import runtime, payload


def test_cancel_queued_removes_without_execution_and_releases_capacity():
    store = OperationStore("generation", max_queue=1)
    engine = runtime(lambda p, c: (_ for _ in ()).throw(AssertionError("must not execute")), store=store)
    engine.submit(payload())
    receipt = store.cancel("one")
    assert (receipt["state"], receipt["effects"]) == ("canceled", "none")
    assert engine.submit(payload())[0]["state"] == "canceled"
    engine.on_external_event(None)
    assert not engine.command_running
    engine.submit(payload("two"))


def test_cancel_take_race_has_exactly_one_owner():
    for _ in range(60):
        store = OperationStore("generation")
        store.admit(payload())
        barrier = threading.Barrier(2)
        def take():
            barrier.wait()
            return store.take_next()
        def cancel():
            barrier.wait()
            return store.cancel("one")
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(take), pool.submit(cancel)
            work, receipt = a.result(), b.result()
        assert not store.has_queued()
        if work is None:
            assert receipt["state"] == "canceled" and receipt["effects"] == "none"
        else:
            assert store.cancellation_requested("one")
            assert receipt["state"] == "running"


def test_running_cancel_only_observed_at_checkpoint_preserves_prior_commits():
    entered, checkpoint = threading.Event(), threading.Event()
    engine = runtime()
    def execute(p, c, cancellation_check):
        entered.set()
        assert checkpoint.wait(3)
        assert cancellation_check()
        return dict(state="canceled", effects="committed", result={"prior_commit": True})
    engine.execute = execute
    engine.submit(payload())
    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(engine.on_external_event, None)
        assert entered.wait(2)
        receipt = engine.store.cancel("one")
        assert receipt["state"] == "running"
        assert receipt["effects"] == "unknown"
        assert not work.done()
        checkpoint.set()
        work.result(3)
    assert engine.store.inspect("one")["effects"] == "committed"


def test_cancellation_flag_does_not_mislabel_completed_uncooperative_script():
    engine = runtime()
    def execute(p, c, check):
        engine.store.cancel("one")
        return dict(state="succeeded", effects="unknown", result={})
    engine.execute = execute
    engine.submit(payload())
    engine.on_external_event(None)
    receipt = engine.store.inspect("one")
    assert receipt["state"] == "succeeded" and receipt["cancellation_requested"]
    assert engine.store.cancel("one") == receipt


def test_known_interaction_is_explicit_and_cannot_be_forced():
    store = OperationStore("generation")
    store.admit(payload())
    store.take_next()
    assert store.inspect("one")["state"] == "running"
    store.interaction("one", True, "PickObject")
    assert store.cancel("one")["state"] == "waiting_for_user"
    store.interaction("one", False)
    store.complete("one", "canceled", "none", {"outcome": "user_canceled"})
    assert store.inspect("one")["result"]["outcome"] == "user_canceled"
