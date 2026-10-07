"""Inverted Opus PR8 cases: real registry/journal/runner, inert host only."""
import threading
from types import SimpleNamespace

import pytest

from revit_mcp.execution_runtime import NativeExecutionAdapter
from revit_mcp.execution_safety import ExecutionSafety
from revit_mcp.operation_store import (
    OperationStore, ReceiptJournal, OperationError, JournalCapacityError,
    JOURNAL_ENVELOPE_RESERVE,
)
from tests.unit.test_operation_runtime import runtime, payload


def shared_engine(store):
    engine = runtime(store=store)
    safety = ExecutionSafety()
    engine.adapter = SimpleNamespace(safety=safety, registry=SimpleNamespace(expire=lambda: None))
    return engine, safety


@pytest.mark.parametrize("waiting", [False, True])
def test_stop_keeps_running_owner_and_shared_safety_until_known_completion(tmp_path, waiting):
    store = OperationStore("generation", journal=ReceiptJournal(str(tmp_path)))
    engine, safety = shared_engine(store)

    def execute(data, context, check):
        if waiting:
            store.interaction("one", True, "known pick")
        engine.stop()
        assert store.records["one"]["receipt"]["state"] == ("waiting_for_user" if waiting else "running")
        assert check()
        return dict(state="succeeded", effects="committed", result={"output": "done"})

    engine.execute = execute
    engine.submit(payload())
    engine.on_external_event(None)
    record = store.journal.load("generation")[0]
    assert (record["state"], record["effects"]) == ("succeeded", "committed")
    assert record["generation_expired"] and record["result"]["output"] == "done"
    assert not engine.quarantined and not engine.command_running
    safety.require_safe()


def test_capacity_rejection_does_not_fail_running_or_queued_work(tmp_path):
    store = OperationStore("generation", journal=ReceiptJournal(str(tmp_path), max_records=2))
    engine, safety = shared_engine(store)
    seen = []

    def execute(data, context, check):
        seen.append(data["operation_id"])
        if data["operation_id"] == "a":
            engine.submit(payload("b"))
            with pytest.raises(JournalCapacityError) as failure:
                engine.submit(payload("c"))
            assert failure.value.code == "journal_full"
        return dict(state="succeeded", effects="none", result={})

    engine.execute = execute
    engine.submit(payload("a"))
    engine.on_external_event(None)
    assert not store.durability_failed and not engine.quarantined
    assert store.inspect("a")["durability"] == "journal"
    assert store.inspect("b")["state"] == "queued"
    engine.on_external_event(None)
    assert seen == ["a", "b"] and store.inspect("b")["state"] == "succeeded"
    safety.require_safe()


def test_old_known_terminal_archives_reclaimed_but_uncertain_records_retained(tmp_path):
    now = [0]
    journal = ReceiptJournal(str(tmp_path), max_records=3, archive_retention_seconds=10, clock=lambda: now[0])
    old = OperationStore("old", journal=journal, clock=lambda: now[0])
    for name, effects in (("known", "committed"), ("uncertain", "unknown")):
        old.admit(payload(name, runtime_id="old"))
        old.take_next()
        old.complete(name, "failed", effects, {})
    old.admit(payload("unfinished", runtime_id="old"))
    now[0] = 11
    fresh = OperationStore("new", journal=journal, clock=lambda: now[0])
    fresh.admit(payload("first", runtime_id="new"))
    archived = {item["operation_id"]: item for item in journal.load("old")}
    assert set(archived) == {"uncertain", "unfinished"}
    assert archived["unfinished"]["state"] == "unknown_after_restart"
    with pytest.raises(JournalCapacityError):
        fresh.admit(payload("second", runtime_id="new"))
    assert not fresh.durability_failed


def test_archive_retention_never_recycles_current_runtime_tombstones(tmp_path):
    now = [0]
    journal = ReceiptJournal(str(tmp_path), max_records=1, archive_retention_seconds=1, clock=lambda: now[0])
    store = OperationStore("generation", journal=journal, clock=lambda: now[0])
    store.admit(payload())
    store.take_next()
    store.complete("one", "succeeded", "none", {})
    now[0] = 100
    with pytest.raises(JournalCapacityError):
        store.admit(payload("two"))
    assert store.admit(payload())[1] is False
    assert not store.durability_failed


def test_record_size_rejection_happens_before_temp_write(tmp_path, monkeypatch):
    journal = ReceiptJournal(str(tmp_path), max_record_bytes=128)
    monkeypatch.setattr("revit_mcp.operation_store.tempfile.mkstemp", lambda **kw: pytest.fail("pre-write rejection"))
    with pytest.raises(JournalCapacityError, match="bound"):
        journal.write("admission", dict(runtime_id="generation", operation_id="one", state="queued",
                                       effects="none", admitted_at=0, extra="x" * 500))
    assert not list(tmp_path.iterdir())


def test_prewrite_start_rejection_still_prevents_executor_entry(tmp_path, monkeypatch):
    store = OperationStore("generation", journal=ReceiptJournal(str(tmp_path)))
    engine, safety = shared_engine(store)
    engine.execute = lambda *a: pytest.fail("start-before-execution invariant")
    engine.submit(payload())
    monkeypatch.setattr(store.journal, "write", lambda *a: (_ for _ in ()).throw(
        JournalCapacityError("pre-write start limit", "journal_record_too_large")))
    engine.on_external_event(None)
    record = store.inspect("one")
    assert (record["state"], record["effects"]) == ("failed", "none")
    assert record["durability"] == "not_recorded"
    assert not store.durability_failed and not engine.command_running
    safety.require_safe()


def test_receipt_and_journal_configuration_must_leave_envelope_space(tmp_path):
    journal = ReceiptJournal(str(tmp_path), max_record_bytes=4096)
    with pytest.raises(ValueError, match="envelope reserve"):
        OperationStore("generation", journal=journal)
    compatible = ReceiptJournal(str(tmp_path), max_record_bytes=128 + JOURNAL_ENVELOPE_RESERVE)
    store = OperationStore("generation", journal=compatible, max_receipt_bytes=128)
    store.admit(payload())
    store.take_next()
    store.complete("one", "succeeded", "committed", {"output": "x" * 8000})
    assert store.journal.load("generation")[0]["durability"] == "journal"
    assert not store.durability_failed


def test_identity_envelope_cannot_consume_reserved_completion_space(tmp_path):
    store = OperationStore("generation", journal=ReceiptJournal(str(tmp_path)))
    with pytest.raises(JournalCapacityError, match="identity envelope"):
        store.admit(payload(identity={"extra": "x" * JOURNAL_ENVELOPE_RESERVE}))
    assert not store.durability_failed and not store.records and not list(tmp_path.iterdir())


def test_admission_uses_last_complete_observation_while_healthy_api_scan_runs():
    registry = SimpleNamespace(validate_target=lambda i, r: None, snapshot=lambda: {
        "documents_known": True, "documents": [{"document_id": "d"}], "revit_version": "2025"})
    adapter = NativeExecutionAdapter(registry, lambda *a, **k: None)
    doc = SimpleNamespace(IsValidObject=True, IsModifiable=False)
    assert adapter.observe_safety_api(SimpleNamespace(Application=SimpleNamespace(Documents=[doc])))
    entered, release = threading.Event(), threading.Event()

    def documents():
        entered.set()
        assert release.wait(3)
        yield doc

    worker = threading.Thread(target=adapter.observe_safety_api,
                              args=(SimpleNamespace(Application=SimpleNamespace(Documents=documents())),))
    worker.start()
    assert entered.wait(2)
    try:
        adapter.admit_cached(payload(document_id="d"))
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    doc.IsModifiable = True
    assert not adapter.observe_safety_api(SimpleNamespace(Application=SimpleNamespace(Documents=[doc])))
    with pytest.raises(OperationError, match="safe API-context"):
        adapter.admit_cached(payload(document_id="d"))


def test_failed_api_observation_invalidates_previous_safe_snapshot():
    adapter = NativeExecutionAdapter(SimpleNamespace(validate_target=lambda *a: None), lambda *a: None)
    assert adapter.observe_safety_api(SimpleNamespace(Application=SimpleNamespace(Documents=[])))

    def broken():
        raise RuntimeError("enumeration unavailable")
        yield

    with pytest.raises(RuntimeError):
        adapter.observe_safety_api(SimpleNamespace(Application=SimpleNamespace(Documents=broken())))
    assert adapter._host_safety == (False, False)
