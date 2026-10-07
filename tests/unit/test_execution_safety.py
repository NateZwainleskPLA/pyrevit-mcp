from concurrent.futures import ThreadPoolExecutor

import pytest

from revit_mcp.execution_safety import ExecutionSafety, MutationBlockedError


def test_guard_latches_unsafe_and_success_does_not_clear():
    guard = ExecutionSafety()
    guard.require_safe()
    guard.observe({"unsafe": True, "error_type": "UnsafeDocumentError",
                   "cleanup_errors": [{"stage": "rollback", "error": "pending"}]}, "doc-token", "operation")
    guard.observe({"unsafe": False})
    with pytest.raises(MutationBlockedError):
        guard.require_safe()
    assert guard.snapshot()["reasons"][0]["document_id"] == "doc-token"


def test_output_error_does_not_block_mutations():
    guard = ExecutionSafety()
    guard.observe({"status": "error", "error_type": "OutputCleanupError", "unsafe": False})
    guard.require_safe()
    assert not guard.snapshot()["blocked"]


def test_snapshots_and_original_results_cannot_change_guard():
    guard = ExecutionSafety()
    result = {"unsafe": True, "cleanup_errors": [{"stage": "rollback", "error": "pending"}]}
    guard.observe(result)
    result["cleanup_errors"][0]["error"] = "changed"
    snapshot = guard.snapshot()
    snapshot["reasons"][0]["cleanup_errors"][0]["error"] = "changed"
    assert guard.snapshot()["reasons"][0]["cleanup_errors"][0]["error"] == "pending"


def test_concurrent_observation_is_not_lost():
    guard = ExecutionSafety()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: guard.observe({"unsafe": True}, operation_id=str(index)), range(20)))
    assert len(guard.snapshot()["reasons"]) == 20
