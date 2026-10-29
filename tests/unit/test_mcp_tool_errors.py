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
