"""The execute tools take a validated client wait in seconds."""
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tools.code_execution_tools import register_code_execution_tools
from tools.revit_transport import RevitTransportResult
from tools.utils import compatibility_response

EXECUTE_TOOLS = ("execute_revit_code", "execute_revit_script_file",
                 "execute_revit_application_code", "execute_revit_application_script_file")


def _arguments(tool, tmp_path):
    arguments = {"target": "r1"}
    if tool in ("execute_revit_code", "execute_revit_script_file"):
        arguments["document"] = "d1"
    if tool.endswith("_script_file"):
        path = tmp_path / "long.py"
        path.write_text("print('done')", encoding="utf-8")
        arguments["file_path"] = str(path)
    else:
        arguments["code"] = "print('done')"
    return arguments


@pytest.fixture
def post(mock_mcp):
    post = AsyncMock(return_value={"status": "success", "output": "done"})
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    return post


@pytest.mark.parametrize("tool", EXECUTE_TOOLS)
@pytest.mark.parametrize("timeout,expected", [(None, 60.0), (300, 300.0), (1800, 1800.0), (1, 1.0)])
async def test_every_execute_tool_passes_its_timeout_to_the_transport(
        tool, timeout, expected, mock_mcp, post, tmp_path):
    arguments = _arguments(tool, tmp_path)
    if timeout is not None:
        arguments["timeout"] = timeout
    assert await mock_mcp.tools[tool](**arguments) == "done"
    assert post.await_args.kwargs["timeout"] == expected


@pytest.mark.parametrize("tool", EXECUTE_TOOLS)
@pytest.mark.parametrize("timeout,message", [
    (0, "between 1 and 1800, got 0"),
    (1801, "between 1 and 1800, got 1801"),
    (600000, "looks like milliseconds; pass 600"),
    ("600000", "looks like milliseconds; pass 600"),
    (float("nan"), "got nan"),
    (float("inf"), "got inf"),
    (True, "not a boolean"),
    ("ten minutes", "number of seconds"),
])
async def test_invalid_timeouts_fail_before_transport(tool, timeout, message, mock_mcp, post, tmp_path):
    with pytest.raises(ToolError, match=message):
        await mock_mcp.tools[tool](timeout=timeout, **_arguments(tool, tmp_path))
    post.assert_not_awaited()


@pytest.mark.parametrize("tool", EXECUTE_TOOLS)
async def test_timed_out_execute_keeps_warning_and_says_how_to_wait_longer(tool, mock_mcp, tmp_path):
    result = RevitTransportResult("POST", "http://host/execute", failure_kind="timeout",
                                  mutation_outcome_unknown=True, timeout_seconds=300.0)
    post = AsyncMock(return_value=compatibility_response(result))
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    with pytest.raises(ToolError) as failure:
        await mock_mcp.tools[tool](timeout=300, **_arguments(tool, tmp_path))
    text = str(failure.value)
    assert "Request timed out after 300 seconds" in text
    assert "The request may still be running in Revit" in text
    assert "check whether this one finished" in text and "up to 1800" in text


async def test_native_schema_offers_timeout_on_every_execute_tool():
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer("timeout-contract-test")
    register_code_execution_tools(mcp, AsyncMock(), AsyncMock())
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for name in EXECUTE_TOOLS:
        schema = tools[name].input_schema
        assert schema["properties"]["timeout"]["default"] == 60.0
        assert "timeout" not in schema["required"]
        assert "1800" in tools[name].description and "seconds" in tools[name].description


async def test_native_call_coerces_string_seconds_and_rejects_milliseconds(tmp_path):
    # Through the SDK's argument validation, as a client's JSON reaches the tool.
    # The script-file tool is used because it logs nothing through ctx.
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer("timeout-call-test")
    post = AsyncMock(return_value={"status": "success", "output": "done"})
    register_code_execution_tools(mcp, AsyncMock(), post)
    arguments = _arguments("execute_revit_script_file", tmp_path)
    await mcp.call_tool("execute_revit_script_file", dict(arguments, timeout="240"))
    assert post.await_args.kwargs["timeout"] == 240.0
    with pytest.raises(ToolError, match="milliseconds; pass 600"):
        await mcp.call_tool("execute_revit_script_file", dict(arguments, timeout="600000"))
    assert post.await_count == 1
