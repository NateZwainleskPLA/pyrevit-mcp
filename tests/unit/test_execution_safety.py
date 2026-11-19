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


def test_blocked_message_says_why_it_latched_and_the_recovery_step():
    guard = ExecutionSafety()
    guard.observe({"unsafe": True, "error_type": "TransactionScopeError",
                   "cleanup_errors": [{"scope": "Flex", "stage": "commit",
                                       "error": "Pending/unconfirmed failure processing; cleanup is not proven"}]},
                  "doc-token", "op-1")
    guard.observe({"unsafe": True, "error_type": "UnsafeDocumentError"})
    with pytest.raises(MutationBlockedError) as raised:
        guard.require_safe()
    message = str(raised.value)
    assert message.startswith(
        "Model changes are blocked because an earlier call left Revit in an unverified state: "
        "TransactionScopeError at commit of 'Flex': Pending/unconfirmed failure processing; cleanup is not "
        "proven (operation op-1, document doc-token) (1 more latch reasons). Recovery: call "
        "request_safety_override with this target, and tell the user that a dialog is waiting for them in Revit.")
    assert "Never answer that dialog yourself" in message and "restarts Revit" in message
    assert "get_revit_model_info" in message and "even for a script that only reads" in message


def test_blocked_message_tolerates_a_prior_engines_sparse_snapshot():
    from revit_mcp.execution_safety import blocked_message
    message = blocked_message({"blocked": True, "reasons": [{"error_type": None}, "unexpected"]})
    assert message.startswith("Model changes are blocked because an earlier call left Revit in an "
                              "unverified state: unsafe execution (1 more latch reasons). Recovery:")
    assert blocked_message({"blocked": True}).startswith(
        "Model changes are blocked because an earlier call left Revit in an unverified state. Recovery:")
