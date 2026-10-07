import pytest

from tools.code_execution_tools import register_code_execution_tools


@pytest.mark.asyncio
async def test_wrapper_passes_managed_mode_and_filename(mock_mcp, mock_revit_get, mock_revit_post):
    register_code_execution_tools(mock_mcp, mock_revit_get, mock_revit_post)
    mock_revit_post.return_value = {"status": "success", "effects": "committed"}
    await mock_mcp.tools["execute_revit_code"](target="r1", document="d1", code="doc.value = 5", transaction_mode="managed", script_name="edit.py")
    assert mock_revit_post.call_args.args[1] == {
        "code": "doc.value = 5", "description": "Code execution", "transaction_mode": "managed", "script_name": "edit.py"}


@pytest.mark.asyncio
async def test_invalid_mode_does_not_submit(mock_mcp, mock_revit_get, mock_revit_post):
    register_code_execution_tools(mock_mcp, mock_revit_get, mock_revit_post)
    result = await mock_mcp.tools["execute_revit_code"](target="r1", document="d1", code="pass", transaction_mode="invalid")
    assert "transaction_mode" in result
    mock_revit_post.assert_not_awaited()
