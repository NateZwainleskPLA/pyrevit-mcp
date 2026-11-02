# -*- coding: utf-8 -*-
"""A tool's own error text reaches the client through the real MCP server.

MCPServer replaces an unexpected exception's text with a generic message, so
an agent that passed a bad target handle or manifest could not tell why.
"""
import pytest
from mcp import Client

from main import mcp


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name, arguments, reason", [
    ("get_revit_target_metadata", {"target": "nope"}, "target handle is unknown in this namespace"),
    ("assess_family_backport", {"manifest": {}}, "Unsupported family manifest schema"),
    ("compare_family_backport", {"source_manifest": {}, "target_manifest": {}}, "Unsupported family manifest schema"),
])
async def test_tool_error_text_reaches_client(mode, name, arguments, reason):
    async with Client(mcp, mode=mode) as client:
        result = await client.call_tool(name, arguments)
    assert result.is_error
    assert result.content[0].text == "Error executing tool {}: {}".format(name, reason)


@pytest.mark.parametrize("name, arguments, text", [
    ("execute_revit_code", {"target": "nope", "document": "d1", "code": "pass"},
     "=== ERROR DETAILS ===\nStatus: error\nError: target handle is unknown in this namespace\n"),
    ("execute_revit_script_file", {"target": "r1", "document": "d1", "file_path": "missing-file.py"},
     "Error reading/executing local script: "),
    ("execute_revit_application_code", {"target": "r1", "code": "pass", "transaction_mode": "managed"},
     "Error during application code execution: Application execution requires transaction_mode='script'"),
    ("execute_revit_application_script_file", {"target": "r1", "file_path": "missing-file.py"},
     "Error reading/executing local application script: "),
])
async def test_execute_tool_failures_are_tool_errors(name, arguments, text):
    async with Client(mcp, mode="auto") as client:
        result = await client.call_tool(name, arguments)
    assert result.is_error
    assert result.content[0].text.startswith("Error executing tool {}: {}".format(name, text))
