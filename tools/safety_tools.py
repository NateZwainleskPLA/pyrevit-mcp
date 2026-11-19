# -*- coding: utf-8 -*-
"""Ask the human at Revit to lift the safety guard's block on model changes."""

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from .utils import format_response

# The user needs time to read and answer. The MCP host may still cut it shorter.
DIALOG_WAIT_SECONDS = 300.0

STILL_OPEN = ("The safety override dialog is still open in Revit, waiting for the user. "
              "Tell the user a Revit MCP dialog is waiting for them in Revit and ask them to "
              "answer it, then retry the blocked call. Do not call request_safety_override "
              "again while it is open.")


def register_safety_tools(mcp, revit_post):
    """Register the user-answered safety override tool."""

    @mcp.tool()
    async def request_safety_override(target: str, ctx: Context = None) -> str:
        """Ask the human at Revit whether model changes may resume after a safety block.

        Use this only after a call failed with error_code 'mutation_blocked'
        ("Model changes are blocked because ..."). It opens a dialog in Revit
        that tells the user why changes were blocked and shows a fresh check of
        every open document. The user then chooses to allow model changes again
        or keep them blocked; keeping them blocked is the default. If a document
        still has an open transaction, the dialog only informs and changes stay
        blocked until Revit restarts.

        Before calling, tell the user a dialog is about to appear in Revit and
        that they must answer it. The decision belongs to the user. Never answer
        the dialog yourself: no computer-use clicks or key presses, no
        PostCommand or UI automation, no scripts. The call waits for the answer;
        if it times out, the dialog is still open, so ask the user to answer it,
        then retry the blocked call instead of calling this again.

        Returns the outcome: allowed (retry the blocked call), kept_blocked
        (continue read-only and ask the user before asking again),
        refused_check_failed, not_blocked or dialog_already_open.
        """
        if ctx:
            await ctx.info("Asking the user in Revit to allow model changes again")
        response = await revit_post("/safety/override/", {}, ctx, target=target,
                                    timeout=DIALOG_WAIT_SECONDS)
        result = getattr(response, "transport_result", None)
        if result is not None and result.failure_kind == "timeout":
            return STILL_OPEN
        body = response if isinstance(response, dict) else {}
        if (result is not None and (result.failure_kind or not result.http_success or result.revit_error)) \
                or "outcome" not in body:
            raise ToolError(format_response(response))
        return "{0}\n\noutcome: {1}".format(body.get("message", ""), body["outcome"])
