import concurrent.futures
import multiprocessing
import uuid

import pytest

from revit_mcp.identity import IdentityError, validate_snapshot
from revit_mcp.target_registry import TargetRegistry, retained_instance_id
from tools.target_directory import TargetDirectory


def uid():
    return str(uuid.uuid4())


def metadata(**changes):
    data = dict(instance_id=uid(), runtime_id=uid(), process_id=100,
                process_started_at="2026-10-05T12:00:00.0000000Z", revit_version="2025",
                endpoint="http://localhost:48884/revit_mcp", documents=[],
                documents_known=True, snapshot_at=100.0)
    data.update(changes)
    return data


def descriptor(token=None, **changes):
    result = dict(document_id=token or uid(), title="Same title", path="", is_active=False)
    result.update(changes)
    return result


class Document:
    def __init__(self, title="Same title", path=""):
        self.Title, self.PathName = title, path
        self.IsValidObject = True

    def Equals(self, other):
        return self is other


def registry(**changes):
    params = dict(process_id=100, process_started_at="2026-10-05T12:00:00Z",
                  revit_version="2025", endpoint="http://localhost:48884/revit_mcp")
    params.update(changes)
    return TargetRegistry(**params)


def assert_code(code, fn):
    with pytest.raises(IdentityError) as error:
        fn()
    assert error.value.code == code


def test_registry_same_titles_are_distinct_and_switch_preserves_tokens():
    reg = registry(clock=lambda: 100)
    a, b = Document(), Document()
    first = reg.refresh_documents([a, b], a)
    second = reg.refresh_documents([a, b], b)
    assert len({d["document_id"] for d in first["documents"]}) == 2
    assert [d["document_id"] for d in first["documents"]] == [d["document_id"] for d in second["documents"]]
    assert [d["is_active"] for d in second["documents"]] == [False, True]
    token = first["documents"][0]["document_id"]
    assert reg.resolve_document(first["instance_id"], first["runtime_id"], token, [a, b], b) is a


def test_closed_invalid_wrapper_is_never_compared_and_reopen_gets_new_token():
    reg, old = registry(), Document(path="C:/same.rvt")
    first = reg.refresh_documents([old], old)
    token = first["documents"][0]["document_id"]
    old.IsValidObject = False
    old.Equals = lambda other: pytest.fail("invalid wrapper was compared")
    reopened = Document(path="C:/same.rvt")
    second = reg.refresh_documents([reopened], reopened)
    assert second["documents"][0]["document_id"] != token
    assert_code("stale_document", lambda: reg.resolve_document(first["instance_id"], first["runtime_id"], token, [reopened]))


def test_snapshot_never_reads_wrappers_and_exposes_freshness():
    now = [100.0]
    reg = registry(clock=lambda: now[0])
    doc = Document()
    reg.refresh_documents([doc], doc)
    # Any wrapper access now would raise, including validity checks.
    class Poison:
        def __getattribute__(self, name):
            raise AssertionError("background read of live document")
    reg._documents = [(Poison(), uid())]
    now[0] = 120
    snapshot = reg.snapshot()
    assert snapshot["snapshot_age_seconds"] == 20
    snapshot["documents"][0]["title"] = "changed copy"
    assert reg.snapshot()["documents"][0]["title"] == "Same title"


def test_failed_refresh_keeps_previous_snapshot_age_and_docs():
    now = [100]
    reg = registry(clock=lambda: now[0])
    doc = Document()
    first = reg.refresh_documents([doc])
    class Broken(Document):
        @property
        def Title(self):
            raise RuntimeError("invalidated")
        @Title.setter
        def Title(self, value):
            pass
    now[0] = 120
    with pytest.raises(RuntimeError):
        reg.refresh_documents([doc, Broken()])
    reg.record_refresh_error("invalidated")
    assert reg.snapshot()["documents"] == first["documents"]
    assert reg.snapshot()["snapshot_at"] == 100


def test_reload_preserves_only_reliably_retained_process_uuid():
    first = registry()
    snap = first.snapshot()
    instance = retained_instance_id(snap["process_id"], snap["process_started_at"], snap)
    second = registry(instance_id=instance)
    assert second.snapshot()["instance_id"] == snap["instance_id"]
    assert second.snapshot()["runtime_id"] != snap["runtime_id"]
    assert retained_instance_id(100, "different start", snap) != instance
    assert retained_instance_id(100, snap["process_started_at"], None) != instance
    assert_code("stale_target", lambda: second.validate_target(instance, snap["runtime_id"]))
    assert_code("invalid_identity", lambda: second.validate_target(instance[:8], snap["runtime_id"]))
    first.expire()
    assert_code("stale_target", lambda: first.validate_target(instance, snap["runtime_id"]))


def test_directory_same_titles_cross_target_close_and_reopen():
    directory = TargetDirectory(clock=lambda: 120)
    a, b = descriptor(), descriptor()
    snap = metadata(documents=[a, b])
    first = directory.observe(snap)
    assert first["snapshot_age_seconds"] == 20
    assert first["documents"][0]["document"] != first["documents"][1]["document"]
    assert directory.observe(snap) == first
    alias = first["documents"][0]["document"]
    dest = directory.resolve(first["target"], alias)
    assert dest["document_id"] == a["document_id"]
    other = directory.observe(metadata(process_id=101, endpoint="http://localhost:48885/revit_mcp"))
    assert_code("cross_target_document", lambda: directory.resolve(other["target"], alias))
    snap.update(documents=[b], snapshot_at=101)
    directory.observe(snap)
    assert_code("expired_document", lambda: directory.resolve(first["target"], alias))
    snap.update(documents=[b, descriptor()], snapshot_at=102)
    reopened = directory.observe(snap)
    assert reopened["documents"][1]["document"] != alias
    snap.update(documents=[a, b], snapshot_at=103)
    assert_code("expired_document", lambda: directory.observe(snap))


@pytest.mark.parametrize("change", ["runtime", "pid_reuse", "port_reuse"])
def test_runtime_process_or_endpoint_replacement_retires_old_handle(change):
    directory = TargetDirectory()
    snap = metadata(documents=[descriptor()])
    first = directory.observe(snap)
    replacement = dict(snap, runtime_id=uid())
    if change == "pid_reuse":
        replacement.update(instance_id=uid(), process_started_at="2026-10-06T12:00:00Z")
    if change == "port_reuse":
        replacement.update(instance_id=uid(), process_id=222)
    second = directory.observe(replacement)
    assert second["target"] != first["target"]
    assert_code("expired_target", lambda: directory.resolve(first["target"]))
    assert_code("expired_target", lambda: directory.observe(snap))


def test_registration_endpoint_and_uuid_checks_reject_bad_discovery():
    directory = TargetDirectory()
    snap = metadata()
    assert_code("stale_registration", lambda: directory.observe(snap, registration={"process_id": 22}))
    assert_code("stale_registration", lambda: directory.observe(snap, registration={"process_started_at": "old"}))
    assert_code("endpoint_mismatch", lambda: directory.observe(snap, expected_endpoint="http://localhost:48885/revit_mcp"))
    assert_code("invalid_identity", lambda: directory.observe(dict(snap, runtime_id=snap["runtime_id"][:8])))
    assert directory.targets() == []


async def test_persistence_requires_revalidation_and_lost_state_changes_namespace(tmp_path):
    path = tmp_path / "directory.sqlite"
    directory = TargetDirectory(path)
    snap = metadata(documents=[descriptor()])
    original = directory.observe(snap)
    directory.close()
    restarted = TargetDirectory(path)
    assert restarted.targets()[0]["target"] == original["target"]
    assert not restarted.targets()[0]["verified"]
    assert_code("verification_required", lambda: restarted.resolve(original["target"]))
    async def handshake(endpoint):
        assert endpoint == snap["endpoint"]
        return snap
    await restarted.revalidate(original["target"], handshake)
    assert restarted.resolve(original["target"], original["documents"][0]["document"])["document_id"] == snap["documents"][0]["document_id"]
    restarted.close()
    path.unlink()
    fresh = TargetDirectory(path)
    assert fresh.observe(snap)["target"] != original["target"]
    assert_code("unknown_target", lambda: fresh.resolve(original["target"]))


async def test_revalidation_never_falls_back_and_transport_failure_unverifies():
    directory = TargetDirectory()
    snap = metadata()
    target = directory.observe(snap)["target"]
    async def unavailable(endpoint):
        raise OSError("disconnected")
    with pytest.raises(OSError):
        await directory.revalidate(target, unavailable)
    assert_code("verification_required", lambda: directory.resolve(target))
    async def replacement(endpoint):
        return metadata(process_id=333)
    with pytest.raises(IdentityError, match="another process"):
        await directory.revalidate(target, replacement)
    assert_code("expired_target", lambda: directory.resolve(target))
    assert directory.targets() == []


def allocate_in_process(path, snap, output):
    directory = TargetDirectory(path)
    result = directory.observe(snap)
    output.put((result["target"], result["documents"][0]["document"]))
    directory.close()


def test_concurrent_allocation_across_threads_and_processes(tmp_path):
    path = tmp_path / "shared.sqlite"
    snap = metadata(documents=[descriptor()])
    def allocate(i):
        directory = TargetDirectory(path)
        result = directory.observe(snap)
        directory.close()
        return result["target"], result["documents"][0]["document"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        aliases = list(executor.map(allocate, range(24)))
    assert len(set(aliases)) == 1
    ctx = multiprocessing.get_context("spawn")
    output = ctx.Queue()
    processes = [ctx.Process(target=allocate_in_process, args=(path, snap, output)) for _ in range(3)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert {output.get(timeout=2) for _ in processes} == set(aliases)
    directory = TargetDirectory(path)
    assert directory.namespace
    assert len(directory.targets()) == 1


def test_out_of_order_snapshot_does_not_retire_live_document():
    directory = TargetDirectory()
    snap = metadata()
    original = dict(snap)
    snap.update(documents=[descriptor()], snapshot_at=101)
    first = directory.observe(snap)
    older = directory.observe(original)
    assert older["documents"] == first["documents"]
    assert older["snapshot_at"] == 101


@pytest.mark.parametrize("changes", [dict(process_id=True), dict(documents_known=False, documents=[descriptor()]),
                                     dict(snapshot_at=float("nan")), dict(endpoint="http://localhost/revit_mcp")])
def test_schema_rejects_invalid_primitives(changes):
    assert_code("invalid_metadata", lambda: validate_snapshot(metadata(**changes)))
