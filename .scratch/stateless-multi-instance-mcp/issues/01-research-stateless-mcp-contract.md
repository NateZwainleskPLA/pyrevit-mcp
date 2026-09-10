# Research the released stateless MCP contract and SDK surface

Type: research
Status: resolved
Blocked by: none

## Question

What exact requirements, extension mechanics, compatibility rules, and currently released Python SDK interfaces must the migration specification account for when implementing the MCP `2026-07-28` stateless core, self-describing requests, discovery, header routing, cacheable catalogs, Multi Round-Trip Requests, and the Tasks extension?

## Answer

[MCP 2026-07-28 migration baseline](../../../docs/research/mcp-2026-07-28-migration-baseline.md) records the primary-source findings, originally captured on branch `research/mcp-2026-07-28-contract` at commit `0ad8fdf86571b5639018870e25589bfdc4482795` and cherry-picked unchanged onto `master` as `ea053a6`.

The released core supports the intended disposable, self-describing adapter: explicit targets and handles carry cross-request context, catalogs are deterministic and cacheable, and `server/discover` replaces modern initialization. Python SDK `2.0.0` requires migrating `FastMCP` to `MCPServer` and can serve modern and legacy peers together. Tasks is a final extension decision but its current artifact is still draft/experimental and unsupported by Python SDK `2.0.0`, so the specification must pin a schema revision, capability-gate it, and define a non-Tasks fallback.
