"""Read-only discovery tools, injected into the MCP server by its composition root."""
from mcp.server.fastmcp import Context
from revit_mcp.identity import IdentityError


def register_target_tools(mcp, directory, discovery):
    @mcp.tool()
    async def list_revit_targets(ctx: Context) -> dict:
        """Discover Revit runtimes and immutable target/document handles with freshness."""
        return await discovery.discover()

    @mcp.tool()
    async def get_revit_target_metadata(target: str, ctx: Context) -> dict:
        """Read cached document metadata for one explicit target after a live handshake."""
        await discovery.revalidate(target)
        result = next((item for item in directory.targets() if item["target"] == target), None)
        if result is None:
            raise IdentityError("expired_target", "Target retired while reading metadata")
        return result
