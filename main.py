# -*- coding: utf-8 -*-
import os
import sys
import json
import anyio
from mcp.server.fastmcp import FastMCP, Image, Context
import base64
from typing import Optional, Dict, Any, Union
from tools.revit_transport import RevitTransportResult, request_revit
from tools.utils import compatibility_response, format_response
from tools.target_directory import TargetDirectory
from tools.target_router import TargetRouter
from tools.target_discovery import TargetDiscovery
from revit_mcp.identity import IdentityError
from revit_mcp.routing_policy import RoutingPolicyError

# Create a generic MCP server for interacting with Revit
# Use stateless_http=True and json_response=True for better compatibility
mcp = FastMCP(
    "Revit MCP Server", 
    host="127.0.0.1", 
    port=8000,
    stateless_http=True,
    json_response=True
)

target_directory = TargetDirectory(os.environ.get("REVIT_TARGET_STATE"))
target_discovery = TargetDiscovery(target_directory)
target_router = TargetRouter(target_directory, target_discovery.verified_handshake)


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return compatibility_response(await _revit_call("GET", endpoint, ctx=ctx, **kwargs))


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return compatibility_response(await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs))


async def revit_image(endpoint: str, ctx: Context = None, *, target: str,
                      document: str):
    """GET request that returns an Image object"""
    result = await _revit_call("GET", endpoint, ctx=ctx, timeout=60.0,
                               target=target, document=document)
    if (result.failure_kind or not result.http_success or result.revit_error or
            not isinstance(result.body, dict) or "image_data" not in result.body):
        return format_response(result)
    try:
        image_bytes = base64.b64decode(result.body["image_data"], validate=True)
        metadata = {key: result.body[key] for key in ("actual_target",) if key in result.body}
        return [Image(data=image_bytes, format="png"),
                json.dumps(dict(metadata, target=target, document=document))]
    except (ValueError, TypeError) as e:
        return f"Error: Invalid image data: {str(e) or type(e).__name__}"


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                     timeout: float = 30.0, params: Dict = None, *, target: str,
                     document: str = None, allow_ui_change: bool = False) -> RevitTransportResult:
    """Internal structured response; presentation belongs at the tool boundary."""
    try:
        return await target_router.call(method, endpoint, target=target, document=document,
                                        data=data, params=params, timeout=timeout,
                                        allow_ui_change=allow_ui_change)
    except (IdentityError, RoutingPolicyError) as error:
        return RevitTransportResult(method=method, url="", json_received=True,
                                    body={"status": "error", "error": str(error),
                                          "error_code": error.code, "target": target,
                                          "document": document, "effects": "none"})


# Register all tools BEFORE the main block
from tools import register_tools
register_tools(mcp, revit_get, revit_post, revit_image,
               target_directory=target_directory, target_discovery=target_discovery)


async def run_combined_async():
    """Run server with both SSE and streamable-http endpoints.

    This allows clients to connect via either:
    - SSE: GET /sse, POST /messages/
    - Streamable-HTTP: POST/GET /mcp
    """
    import uvicorn

    # Get the streamable-http app first - it has the proper lifespan
    # that initializes the session manager's task group
    http_app = mcp.streamable_http_app()

    # Get SSE routes (SSE doesn't need special lifespan - it creates
    # task groups per-request in connect_sse())
    sse_app = mcp.sse_app()

    # Add SSE routes to the http app (preserving its lifespan)
    for route in sse_app.routes:
        http_app.routes.append(route)

    config = uvicorn.Config(
        http_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    transport = "stdio"

    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv or "--streamable-http" in sys.argv:
        transport = "streamable-http"
    elif "--combined" in sys.argv:
        # Run both SSE and streamable-http transports simultaneously
        print("Starting combined server with SSE (/sse, /messages/) and streamable-http (/mcp) endpoints...")
        anyio.run(run_combined_async)
        sys.exit(0)

    mcp.run(transport=transport)
