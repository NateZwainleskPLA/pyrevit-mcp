"""Opt-in recoverable tools using the routing owner's TargetRouter interface."""
from mcp.server.fastmcp import Context


def register_execution_tools(mcp, router):
    """Explicit registration only; this does not enable the native runtime."""
    async def call(endpoint, target, document, operation_id, data, ctx):
        if not target or not operation_id or (endpoint == "/operations/submit/" and not document):
            raise ValueError("target and stable operation_id are required; submission also requires document")
        result = await router.call("POST", endpoint, target=target, document=document,
                                   data=dict((key, value) for key, value in
                                             dict(data, operation_id=operation_id).items()
                                             if key != "allow_ui_change"),
                                   timeout=10.0,
                                   allow_ui_change=data.get("allow_ui_change", False))
        # Preserve the body and delivery classification. Never automatically retry.
        envelope = {"operation_id": operation_id, "target": target, "document": document,
                "http_status": result.status_code, "response": result.body,
                "failure_kind": result.failure_kind, "error": result.error,
                "mutation_outcome_unknown": result.mutation_outcome_unknown}
        if result.http_success and result.failure_kind is None:
            if not isinstance(result.body, dict) or result.body.get("operation_id") != operation_id:
                envelope.update(failure_kind="invalid_operation_response",
                                error="Successful receipt did not confirm the requested operation ID",
                                mutation_outcome_unknown=endpoint != "/operations/inspect/")
        return envelope

    @mcp.tool()
    async def submit_revit_execution(target: str, document: str, operation_id: str,
                                     code: str, description: str = "Code execution",
                                     transaction_mode: str = "script",
                                     allow_ui_change: bool = False,
                                     script_name: str = "<revit-script>",
                                     expected_revit_version: str | None = None,
                                     ctx: Context = None) -> dict:
        """Submit once. After timeout inspect this ID; changed payload conflicts."""
        if transaction_mode not in ("script", "managed"):
            raise ValueError("transaction_mode must be script or managed")
        data = dict(code=code, description=description, transaction_mode=transaction_mode,
                    allow_ui_change=allow_ui_change, script_name=script_name)
        if expected_revit_version is not None:
            data["expected_revit_version"] = expected_revit_version
        return await call("/operations/submit/", target, document, operation_id, data, ctx)

    @mcp.tool()
    async def get_revit_operation(target: str, operation_id: str,
                                  ctx: Context = None) -> dict:
        """Inspect retained primitive receipts without waiting for Revit UI."""
        return await call("/operations/inspect/", target, None, operation_id, {}, ctx)

    @mcp.tool()
    async def cancel_revit_operation(target: str, operation_id: str,
                                     ctx: Context = None) -> dict:
        """Cancel queued work or request a checkpoint; cannot force native dialogs."""
        return await call("/operations/cancel/", target, None, operation_id, {}, ctx)
