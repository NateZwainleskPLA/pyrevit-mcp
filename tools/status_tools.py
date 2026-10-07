# -*- coding: utf-8 -*-
"""Status and model information tools"""

from mcp.server.fastmcp import Context
from .utils import format_response


def register_status_tools(mcp, revit_get):
    """Register status-related tools"""

    @mcp.tool()
    async def get_revit_status(target: str, ctx: Context) -> str:
        """Check the addressed instance's active-document status in API context.

        Busy/modal Revit can delay this document-context call. Discovery reads
        cached /metadata/ separately; neither proves model execution readiness.
        """
        response = await revit_get("/status/", ctx, timeout=10.0, target=target)
        return format_response(response)

    @mcp.tool()
    async def get_revit_model_info(target: str, document: str, ctx: Context) -> str:
        """Get comprehensive information about the current Revit model"""
        response = await revit_get(
            "/model_info/", ctx, target=target, document=document
        )
        return format_response(response)
