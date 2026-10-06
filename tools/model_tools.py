# -*- coding: utf-8 -*-
"""Model structure and hierarchy tools"""

from mcp.server.fastmcp import Context
from .utils import format_response


def register_model_tools(mcp, revit_get):
    """Register model structure tools"""

    @mcp.tool()
    async def list_levels(target: str, document: str, ctx: Context = None) -> str:
        """Get a list of all levels in the current Revit model"""
        response = await revit_get(
            "/list_levels/", ctx, target=target, document=document
        )
        return format_response(response)
