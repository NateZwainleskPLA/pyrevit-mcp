# -*- coding: utf-8 -*-
import os
import sys
import anyio
from mcp.server.fastmcp import FastMCP, Image, Context
import base64
from typing import Optional, Dict, Any, Union
from tools.revit_transport import RevitTransportResult, request_revit
from tools.utils import compatibility_response, format_response

# Create a generic MCP server for interacting with Revit
# Use stateless_http=True and json_response=True for better compatibility
mcp = FastMCP(
    "Revit MCP Server", 
    host="127.0.0.1", 
    port=8000,
    stateless_http=True,
    json_response=True
)

# Configuration
# Revit runs on Windows; when it lives in a VM the routes server is not on the
# host loopback, so allow overriding the target via the environment.
REVIT_HOST = os.environ.get("REVIT_HOST", "127.0.0.1")
REVIT_PORT = int(os.environ.get("REVIT_PORT", "48884"))
BASE_URL = f"http://{REVIT_HOST}:{REVIT_PORT}/revit_mcp"


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return compatibility_response(await _revit_call("GET", endpoint, ctx=ctx, **kwargs))


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return compatibility_response(await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs))


async def revit_image(endpoint: str, ctx: Context = None) -> Union[Image, str]:
    """GET request that returns an Image object"""
    result = await _revit_call("GET", endpoint, ctx=ctx, timeout=60.0)
    if (result.failure_kind or not result.http_success or result.revit_error or
            not isinstance(result.body, dict) or "image_data" not in result.body):
        return format_response(result)
    try:
        image_bytes = base64.b64decode(result.body["image_data"], validate=True)
        return Image(data=image_bytes, format="png")
    except (ValueError, TypeError) as e:
        return f"Error: Invalid image data: {str(e) or type(e).__name__}"


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                     timeout: float = 30.0, params: Dict = None) -> RevitTransportResult:
    """Internal structured response; presentation belongs at the tool boundary."""
    return await request_revit(method, f"{BASE_URL}{endpoint}", data=data,
                               params=params, timeout=timeout)


# Register all tools BEFORE the main block
from tools import register_tools
register_tools(mcp, revit_get, revit_post, revit_image)


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
