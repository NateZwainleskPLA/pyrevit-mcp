from unittest.mock import AsyncMock

import pytest

from tools.execution_tools import register_execution_tools
from tools.revit_transport import RevitTransportResult


async def test_submission_preserves_receipt_and_does_not_retry_loss(mock_mcp):
    router = AsyncMock()
    router.call.return_value = RevitTransportResult("POST", "http://host", failure_kind="timeout",
                                                    mutation_outcome_unknown=True)
    register_execution_tools(mock_mcp, router)
    response = await mock_mcp.tools["submit_revit_execution"]("r17", "d4", "stable", "pass")
    assert response["operation_id"] == "stable"
    assert response["mutation_outcome_unknown"]
    assert router.call.await_count == 1
    router.call.return_value = RevitTransportResult("POST", "http://host", status_code=200,
        body={"operation_id": "stable", "effects": "committed", "state": "succeeded"}, json_received=True)
    receipt = await mock_mcp.tools["get_revit_operation"]("r17", "d4", "stable")
    assert receipt["response"]["effects"] == "committed"
    assert router.call.call_args.kwargs["data"]["operation_id"] == "stable"


async def test_requires_handles_and_stable_id_before_transport(mock_mcp):
    router = AsyncMock()
    register_execution_tools(mock_mcp, router)
    with pytest.raises(ValueError):
        await mock_mcp.tools["get_revit_operation"]("", "d4", "one")
    router.call.assert_not_called()
