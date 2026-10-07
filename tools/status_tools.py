# -*- coding: utf-8 -*-
"""Status and model information tools"""

from mcp.server.fastmcp import Context
from .utils import format_response


def register_status_tools(mcp, revit_get):
    """Register status-related tools"""

    @mcp.tool()
    async def get_revit_status(ctx: Context) -> str:
        """Check active-document status in Revit API context.

        This can time out while Revit is busy or modal. The document-free
        /health/ endpoint checks listener liveness without waiting for that context.
        """
        response = await revit_get("/status/", ctx, timeout=10.0)
        return format_response(response)

    @mcp.tool()
    async def get_revit_model_info(ctx: Context) -> str:
        """Get comprehensive information about the current Revit model"""
        response = await revit_get("/model_info/", ctx)
        return format_response(response)
