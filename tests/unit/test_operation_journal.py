import json

import pytest

from revit_mcp.operation_store import ReceiptJournal, OperationStore, OperationError
from tests.unit.test_operation_runtime import runtime, payload


def journal_store(tmp_path, **options):
    return OperationStore("generation", journal=ReceiptJournal(str(tmp_path)), **options)


def test_admission_is_on_disk_before_queue_and_start_before_executor(tmp_path):
    store = journal_store(tmp_path)
    journal = store.journal
    def execute(p, c):
        persisted = journal.load("generation")[0]
        assert persisted["state"] == "unknown_after_restart"
        data = json.loads(next(tmp_path.glob("*.json")).read_text())
        assert [e["kind"] for e in data["events"]] == ["admission", "start"]
        return dict(state="succeeded", effects="committed", result={"output": "done"})
    engine = runtime(execute, store=store)
    engine.submit(payload())
    data = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert data["receipt"]["state"] == "queued"
    assert data["events"][0]["kind"] == "admission"
    engine.on_external_event(None)
    recovered = journal.load("generation")[0]
    assert (recovered["state"], recovered["effects"]) == ("succeeded", "committed")
    assert [e["kind"] for e in json.loads(next(tmp_path.glob("*.json")).read_text())["events"]] == ["admission", "start", "completion"]


@pytest.mark.parametrize("started", [False, True])
def test_restart_never_replays_unfinished_work_and_duplicate_stays_unknown(tmp_path, started):
    store = journal_store(tmp_path)
    store.admit(payload())
    if started:
        store.take_next()
    recovered = journal_store(tmp_path)
    assert recovered.take_next() is None
    receipt, created = recovered.admit(payload())
    assert not created
    assert (receipt["state"], receipt["effects"]) == ("unknown_after_restart", "unknown")
    with pytest.raises(OperationError) as failure:
        recovered.admit(payload(code="different"))
    assert failure.value.code == "operation_conflict"


def test_new_generation_does_not_replay_old_but_archive_remains_inspectable(tmp_path):
    old = journal_store(tmp_path)
    old.admit(payload())
    new = OperationStore("new-generation", journal=ReceiptJournal(str(tmp_path)))
    assert new.take_next() is None
    assert new.journal.load("generation")[0]["state"] == "unknown_after_restart"
    with pytest.raises(OperationError):
        new.inspect("one")


def test_failed_admission_write_never_becomes_visible_or_executable(tmp_path, monkeypatch):
    store = journal_store(tmp_path)
    monkeypatch.setattr(store.journal, "_replace", lambda *a: (_ for _ in ()).throw(OSError("disk failed")))
    with pytest.raises(OperationError) as failure:
        store.admit(payload())
    assert failure.value.code == "journal_unavailable"
    assert not store.records and not store.has_queued()
    assert not list(tmp_path.iterdir())


def test_failed_start_receipt_never_enters_executor(tmp_path, monkeypatch):
    store = journal_store(tmp_path)
    engine = runtime(lambda p, c: pytest.fail("executor must not run"), store=store)
    engine.submit(payload())
    monkeypatch.setattr(store.journal, "write", lambda *a: (_ for _ in ()).throw(OSError("disk failed")))
    engine.on_external_event(None)
    receipt = store.inspect("one")
    assert (receipt["state"], receipt["effects"]) == ("failed", "none")
    assert receipt["durability"] == "uncertain"
    assert not engine.command_running


def test_completion_failure_retains_memory_result_and_blocks_queued_and_new_work(tmp_path, monkeypatch):
    store = journal_store(tmp_path)
    engine = runtime(store=store)
    engine.submit(payload())
    engine.submit(payload("two"))
    original = store.journal.write
    def fail_completion(kind, receipt):
        if kind == "completion":
            raise OSError("completion failed")
        original(kind, receipt)
    monkeypatch.setattr(store.journal, "write", fail_completion)
    engine.on_external_event(None)
    receipt = store.inspect("one")
    assert receipt["state"] == "succeeded" and receipt["durability"] == "uncertain"
    assert not engine.command_running
    assert engine.submit(payload())[1] is False
    with pytest.raises(OperationError):
        engine.submit(payload("three"))
    engine.on_external_event(None)
    assert store.inspect("two")["effects"] == "none"
    assert store.inspect("two")["state"] == "failed"
    assert store.journal.load("generation")[0]["state"] == "unknown_after_restart"


def test_atomic_replacement_failure_preserves_last_valid_record(tmp_path, monkeypatch):
    store = journal_store(tmp_path)
    store.admit(payload())
    previous = next(tmp_path.glob("*.json")).read_bytes()
    monkeypatch.setattr(store.journal, "_replace", lambda *a: (_ for _ in ()).throw(OSError("rename failed")))
    assert store.take_next() is None
    assert next(tmp_path.glob("*.json")).read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_journal_capacity_and_receipt_retention_keep_dedup_tombstones(tmp_path):
    now = [0]
    journal = ReceiptJournal(str(tmp_path), max_records=1)
    store = OperationStore("generation", journal=journal, retention_seconds=2, clock=lambda: now[0])
    store.admit(payload())
    store.take_next()
    store.complete("one", "succeeded", "committed", {"output": "private retained output"})
    now[0] = 3
    assert store.inspect("one")["receipt_expired"]
    assert "result" not in journal.load("generation")[0]
    with pytest.raises(OperationError):
        store.admit(payload("two"))
    assert journal.load("generation")[0]["payload_hash"] == store.inspect("one")["payload_hash"]


def test_corrupt_journal_fails_closed_without_admission(tmp_path):
    (tmp_path / "corrupt.json").write_text('{"version":9000}')
    with pytest.raises(ValueError):
        journal_store(tmp_path)


def test_operation_ids_cannot_escape_journal_directory(tmp_path):
    store = journal_store(tmp_path)
    store.admit(payload("../elsewhere/../operation"))
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert store.journal.load("generation")[0]["operation_id"] == "../elsewhere/../operation"
