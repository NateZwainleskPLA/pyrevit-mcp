# -*- coding: utf-8 -*-
"""Document management tools for Revit MCP Server"""

from mcp.server.fastmcp import Context
from .utils import format_response


def register_document_tools(mcp, revit_get, revit_post):
    """Register document management tools with the MCP server."""

    @mcp.tool()
    async def open_document(
        target: str,
        ctx: Context,
        file_path: str,
        detach: bool = False,
        audit: bool = False,
        allow_ui_change: bool = False,
    ) -> str:
        """Open a Revit document file in the specified Revit target.

        Supports workshared (central) files with options to detach from
        central or audit the file on open. Requires allow_ui_change=True.
        After opening, call list_revit_targets again to obtain the new document
        handle; this response does not allocate a client document handle.

        Args:
            target: Explicit handle of the Revit instance to open the file in.
            file_path: Absolute path to a .rvt, .rfa, or .rte file.
            detach: If True, open detached from central (workshared files only).
                    Preserves worksets but severs the link to the central model.
            audit: If True, audit the file on open to check for corruption.
            allow_ui_change: Must be True to permit opening the document.
        """
        data = {
            "file_path": file_path,
            "detach": detach,
            "audit": audit,
        }
        response = await revit_post(
            "/open_document/",
            data,
            ctx,
            timeout=120.0,
            target=target,
            allow_ui_change=allow_ui_change,
        )
        return format_response(response)

    @mcp.tool()
    async def close_document(
        target: str,
        document: str,
        ctx: Context,
        save: bool = False,
        allow_ui_change: bool = False,
    ) -> str:
        """Close the specified inactive Revit document with allow_ui_change=True.

        Closing the active document is rejected. This tool does not activate
        another document or post a delayed Close command.

        Args:
            target: Explicit handle of the owning Revit instance.
            document: Handle of the inactive document to close.
            save: If True, save the document before closing.
                  If False (default), close without saving.
            allow_ui_change: Must be True to permit closing the document.
        """
        data = {"save": save}
        response = await revit_post(
            "/close_document/",
            data,
            ctx,
            target=target,
            document=document,
            allow_ui_change=allow_ui_change,
        )
        return format_response(response)

    @mcp.tool()
    async def save_document(
        target: str,
        document: str,
        ctx: Context,
        file_path: str = None,
    ) -> str:
        """Save the specified Revit document.

        If file_path is omitted, saves the document in place.
        If file_path is provided, performs a Save As to the new location.

        Args:
            file_path: Optional path for Save As. If omitted, saves in place.
        """
        data = {"file_path": file_path}
        response = await revit_post(
            "/save_document/", data, ctx, target=target, document=document
        )
        return format_response(response)

    @mcp.tool()
    async def sync_with_central(
        target: str,
        document: str,
        ctx: Context,
        comment: str = "",
        compact: bool = False,
        relinquish_all: bool = True,
    ) -> str:
        """Synchronize the specified workshared document with central.

        Only works with workshared (central model) documents. For non-workshared
        documents, use save_document instead.

        Args:
            comment: Sync comment visible in the worksharing log.
            compact: If True, compact the central model during sync.
            relinquish_all: If True (default), relinquish all borrowed elements
                           and worksets after sync.
        """
        data = {
            "comment": comment,
            "compact": compact,
            "relinquish_all": relinquish_all,
        }
        response = await revit_post(
            "/sync_with_central/",
            data,
            ctx,
            timeout=120.0,
            target=target,
            document=document,
        )
        return format_response(response)
