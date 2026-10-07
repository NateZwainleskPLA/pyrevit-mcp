# -*- coding: utf-8 -*-
"""Code execution tools for the MCP server."""

from mcp.server.fastmcp import Context
from .utils import format_response


def register_code_execution_tools(mcp, revit_get, revit_post, revit_image=None):
    """Register code execution tools with the MCP server."""
    # Note: revit_get and revit_image are unused but kept for interface consistency
    _ = revit_get, revit_image  # Acknowledge unused parameters

    @mcp.tool()
    async def execute_revit_application_code(
        target: str, code: str, description: str = "Application code execution",
        transaction_mode: str = "script", script_name: str = "<revit-script>",
        allow_ui_change: bool = False, ctx: Context = None,
    ) -> str:
        """Execute synchronous IronPython in the explicit target instance, including at Home.

        No document handle is accepted. Initial doc/uidoc and revit.doc/uidoc
        are None even if another document is active; they do not rebind after
        opening. app/revit.app are the bound Revit Application. uiapp/revit.uiapp
        are the supplied UIApplication only with allow_ui_change=True.

        Script mode opens no automatic transaction; managed mode is rejected.
        Open and continue with explicit local variables, for example:
            new_doc = app.OpenDocumentFile(r'C:\\models\\fixture.rvt')
            with execution.transaction(new_doc, 'Edit'):
                execution.checkpoint()

        With UI permission, use uiapp.OpenAndActivateDocument(path) and retain
        its returned UIDocument. execution.rollback_scope(new_doc, name), DB,
        System, conversion helpers, bounded stdout/stderr and diagnostics match
        execute_revit_code. opened_documents contains fresh registry descriptors
        for documents still open; refresh target documents for client handles.

        Only owned scopes are cleaned. Raw/external effects may remain unknown;
        unsafe postconditions block all subsequent mutations in this process.
        This is arbitrary IronPython 2.7 execution, not a security sandbox.
        """
        try:
            if transaction_mode != "script":
                raise ValueError("Application execution requires transaction_mode='script'; select a document for managed mode")
            if ctx:
                await ctx.info("Executing application code: {}".format(description))
            payload = dict(code=code, description=description, transaction_mode=transaction_mode,
                           script_name=script_name)
            response = await revit_post("/execute_application_code/", payload, ctx,
                                        target=target, allow_ui_change=allow_ui_change, timeout=60.0)
            return format_response(response)
        except (ConnectionError, ValueError, RuntimeError) as error:
            message = "Error during application code execution: {}".format(error)
            if ctx:
                await ctx.error(message)
            return message

    @mcp.tool()
    async def execute_revit_application_script_file(
        target: str, file_path: str, description: str = "Application script file execution",
        transaction_mode: str = "script", allow_ui_change: bool = False, ctx: Context = None,
    ) -> str:
        """Read a LOCAL UTF-8/BOM file and execute in the explicit instance, without a document.

        Application binding, UI permission, transactions and safety rules match
        execute_revit_application_code. Only basename, content hash and code are
        transmitted; no server file access or automatic retry occurs.
        """
        from scripts.execute_revit_file import read_script_file
        try:
            if transaction_mode != "script":
                raise ValueError("Application execution requires transaction_mode='script'; select a document for managed mode")
            payload = read_script_file(file_path)
            payload.update(description=description, transaction_mode=transaction_mode)
            response = await revit_post("/execute_application_code/", payload, ctx,
                                        target=target, allow_ui_change=allow_ui_change, timeout=60.0)
            return format_response(response)
        except (OSError, ConnectionError, ValueError, RuntimeError) as error:
            return "Error reading/executing local application script: {}".format(error)

    @mcp.tool()
    async def execute_revit_script_file(
        target: str, document: str, file_path: str,
        description: str = "Script file execution", transaction_mode: str = "script",
        allow_ui_change: bool = False, ctx: Context = None,
    ) -> str:
        """Read a local UTF-8/BOM script and execute its contents in the specified document.

        The file is read on the MCP client machine, including for remote Revit.
        Only the basename, content hash and code are transmitted. No server-side
        file access or retry occurs. UI/transaction rules match execute_revit_code.
        """
        from scripts.execute_revit_file import read_script_file
        try:
            if transaction_mode not in ("script", "managed"):
                raise ValueError("transaction_mode must be script or managed")
            payload = read_script_file(file_path)
            payload.update(description=description, transaction_mode=transaction_mode)
            response = await revit_post("/execute_code/", payload, ctx, target=target,
                                        document=document, allow_ui_change=allow_ui_change, timeout=60.0)
            return format_response(response)
        except (OSError, ValueError) as error:
            return "Error reading/executing local script: {}".format(error)

    @mcp.tool()
    async def execute_revit_code(
        target: str,
        document: str,
        code: str,
        description: str = "Code execution",
        ctx: Context = None,
        transaction_mode: str = "script",
        script_name: str = "<revit-script>",
        allow_ui_change: bool = False,
    ) -> str:
        """
        Execute IronPython code directly in Revit context.

        The code has access to:
        - doc: The explicitly targeted Revit document
        - uidoc: Supplied UIDocument only with allow_ui_change=true and routing validation
        - DB: Revit API Database namespace
        - revit: Facade with supplied doc, gated UI properties and bound transaction defaults
        - execution: Owned transaction/rollback scopes and cooperative checkpoints
        - eid, id_of, name_of, to_json: Revit/IronPython conversion helpers
        - json: Local adapter for supported Revit/.NET values
        - System: .NET namespace
        - stdout and stderr: Captured separately in the response

        transaction_mode='script' opens no transaction automatically:
            with execution.transaction(doc, "My change"):
                # ... modify model ...
                execution.checkpoint()

        transaction_mode='managed' opens one owned transaction on doc and
        commits on success, rolls back on exception or checkpoint cancellation.
        Do not start additional transactions in managed mode. Document open/
        close, UI changes, family load and multiple-document workflows use script.

        For a trial that undoes its contained committed transactions:
            with execution.rollback_scope(doc, "Trial"):
                with execution.transaction(doc, "Flex"):
                    # ... trial edit ...
                    pass

        Only helper-owned scopes are cleaned. Raw transactions, file writes and
        other external effects cannot be automatically recovered. Pending failure
        processing and cleanup errors are reported as unverified. script_name is
        a diagnostic basename, never a server-side file path. Use IronPython 2.7
        syntax; no f-strings. Imports of json shadow the local adapter: use to_json.

        For UI operations that cannot run inside a transaction, such as switching
        the active view (requires allow_ui_change=True):
            all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
            target = next((v for v in all_views if v.Name == "Level 1"), None)
            if target:
                uidoc.ActiveView = target

        Tips:
        - Use name_of(element) for the hidden Name descriptor
        - Use eid(value) and id_of(element_or_id) for 64-bit ElementId values
        - Check elements exist before use: if element:
        - Use hasattr() for optional properties
        """
        try:
            if transaction_mode not in ("script", "managed"):
                raise ValueError("transaction_mode must be 'script' or 'managed'")
            payload = {"code": code, "description": description}
            if transaction_mode != "script":
                payload["transaction_mode"] = transaction_mode
            if script_name != "<revit-script>":
                payload["script_name"] = script_name

            if ctx:
                await ctx.info("Executing code: {}".format(description))

            response = await revit_post(
                "/execute_code/",
                payload,
                ctx,
                timeout=60.0,
                target=target,
                document=document,
                allow_ui_change=allow_ui_change,
            )
            return format_response(response)

        except (ConnectionError, ValueError, RuntimeError) as e:
            error_msg = "Error during code execution: {}".format(str(e))
            if ctx:
                await ctx.error(error_msg)
            return error_msg
