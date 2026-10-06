"""Opt-in recoverable tools using the routing owner's TargetRouter interface."""
from mcp.server.fastmcp import Context


def register_execution_tools(mcp, router):
    """Explicit registration only; this does not enable the native runtime."""
    async def call(endpoint, target, document, operation_id, data, ctx):
        if not target or not document or not operation_id:
            raise ValueError("target, document and stable operation_id are required")
        result = await router.call("POST", endpoint, target=target, document=document,
                                   data=dict(data, operation_id=operation_id,
                                             target=target, document=document),
                                   timeout=10.0,
                                   allow_ui_change=data.get("allow_ui_change", False))
        # Preserve the body and delivery classification. Never automatically retry.
        return {"operation_id": operation_id, "target": target, "document": document,
                "http_status": result.status_code, "response": result.body,
                "failure_kind": result.failure_kind, "error": result.error,
                "mutation_outcome_unknown": result.mutation_outcome_unknown}

    @mcp.tool()
    async def submit_revit_execution(target: str, document: str, operation_id: str,
                                     code: str, description: str = "Code execution",
                                     transaction_mode: str = "script",
                                     allow_ui_change: bool = False,
                                     script_name: str = "<revit-script>",
                                     ctx: Context = None) -> dict:
        """Submit once. After timeout inspect this ID; changed payload conflicts."""
        if transaction_mode not in ("script", "managed"):
            raise ValueError("transaction_mode must be script or managed")
        return await call("/operations/submit/", target, document, operation_id,
                          dict(code=code, description=description,
                               transaction_mode=transaction_mode,
                               allow_ui_change=allow_ui_change, script_name=script_name), ctx)

    @mcp.tool()
    async def get_revit_operation(target: str, document: str, operation_id: str,
                                  ctx: Context = None) -> dict:
        """Inspect retained primitive receipts without waiting for Revit UI."""
        return await call("/operations/inspect/", target, document, operation_id, {}, ctx)
