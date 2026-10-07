import inspect
from unittest.mock import AsyncMock

import pytest

from tools import register_tools


def test_all_directed_public_tools_require_target_and_document_where_scoped(mock_mcp):
    register_tools(mock_mcp, AsyncMock(), AsyncMock(), AsyncMock())
    exceptions = {"launch_revit", "list_revit_installations"}
    process_only = {"get_revit_status", "open_document", "execute_revit_application_code",
                    "execute_revit_application_script_file"}
    for name, tool in mock_mcp.tools.items():
        signature = inspect.signature(tool)
        if name in exceptions:
            assert "target" not in signature.parameters
            continue
        assert signature.parameters["target"].default is inspect.Parameter.empty
        if name in process_only:
            assert "document" not in signature.parameters
        else:
            assert signature.parameters["document"].default is inspect.Parameter.empty


async def test_missing_public_target_fails_before_transport(mock_mcp):
    get, post = AsyncMock(), AsyncMock()
    register_tools(mock_mcp, get, post, AsyncMock())
    with pytest.raises(TypeError, match="target"):
        await mock_mcp.tools["execute_revit_code"](document="d1", code="pass")
    get.assert_not_awaited()
    post.assert_not_awaited()
