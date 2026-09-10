# MCP Python SDK currentness check — 2026-08-20

## Verdict

The latest stable official Python MCP SDK is **`v2.0.0`**, published **2026-07-28**. No later stable or prerelease appears in the official release feed as of this check. The existing migration baseline's SDK choice remains current. [`v2.0.0` release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0) · [official releases](https://github.com/modelcontextprotocol/python-sdk/releases)

The current repository has **not yet adopted it**: `uv.lock` pins `mcp` `1.9.0`, `requirements.txt` pins `1.28.1`, and `pyproject.toml` declares only `mcp[cli]>=1.9.0`. A later implementation ticket should align all three on an intentional `2.0.0` constraint and regenerate the lock; this research ticket does not change dependencies.

## Exact protocol support

`v2.0.0` enumerates these five released revisions:

- Handshake era: `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`.
- Modern stateless era: `2026-07-28`.

These are the exact values in the tagged SDK's protocol registry, not an inference from marketing language. [`version.py` at `v2.0.0`](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp-types/mcp_types/version.py)

## Dual-era hosting

Yes. One `MCPServer` can serve both eras without a legacy-only process or endpoint. The same `streamable_http_app()` and the same stdio server answer legacy `initialize` traffic and modern `2026-07-28` requests; the SDK documentation says this requires no compatibility flag or separate deployment. [`What's new in v2`](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/whats-new.md#the-protocol-2025-11-25-to-2026-07-28) · [`v2.0.0` release notes](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0#one-sdk-both-protocol-eras)

This confirms the existing design decision: protocol-era compatibility alone does **not** justify a separate Legacy Protocol Adapter. It does not preserve old pyRevit tool schemas or implicit Revit-target behavior; those remain product-level decisions.

One constraint matters for the provisional compatibility plan: `v2.0.0` has no server configuration for a protocol-revision allowlist or for disabling one era. Both eras are enabled. Enforcing a narrower named-client revision policy would require pyRevit-owned request rejection/middleware rather than an SDK setting. [`legacy clients guide`](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/run/legacy-clients.md)

## Tasks support

No. Stable `v2.0.0` does **not** implement the official Tasks extension (SEP-2663), and v2 removed the old experimental Tasks runtime. Legacy Tasks wire types remain, but there is no drop-in Tasks execution facility. The generic extension API could host a project-owned implementation; that is not SDK support. [`v2.0.0` known gaps](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0#known-gaps) · [`v2 migration guide`](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/migration.md#experimental-tasks)

Tasks is now described by its repository as an **official MCP extension**, although its specification and schema still live under `draft` and there is no tagged extension release. [`ext-tasks` README at the checked commit](https://github.com/modelcontextprotocol/ext-tasks/blob/dcc8d2bbecd50397901558dd66f46050c5b21de3/README.md) · [`draft Tasks specification`](https://github.com/modelcontextprotocol/ext-tasks/blob/dcc8d2bbecd50397901558dd66f46050c5b21de3/specification/draft/tasks.md)

## Changes to the 2026-08-10 migration baseline

The SDK conclusions remain valid: `v2.0.0` is still current, supports both protocol eras on one server/endpoint, and still omits Tasks.

The baseline needs four corrections or clarifications before it is used normatively:

1. The extension repository no longer labels Tasks “experimental” or “not official.” It now calls Tasks the official MCP Tasks extension. The wire artifact is nevertheless still located under `draft` and has no tagged release, so pinning an exact commit remains prudent. [`status wording change`](https://github.com/modelcontextprotocol/ext-tasks/commit/8889b9d8b2b0eb41a5ea501f96452b37fcee4b45)
2. The current draft changed the missing-required-client-capability error from **`-32003` to `-32021`** and added an explicit requirement to authenticate and authorize every task-related request. The baseline's `-32003` statement is stale. [`error-code correction`](https://github.com/modelcontextprotocol/ext-tasks/commit/f29ffe5ad3b100efc04b5344ac48ac97f5c66483) · [`auth-binding correction`](https://github.com/modelcontextprotocol/ext-tasks/commit/7b8e2bde214b35fd6f0d4f3899789388d623164d)
3. The provisional idea of pinning an SDK-level supported-revision allowlist is not available as a `v2.0.0` setting. If that policy is retained, pyRevit must enforce it itself. [`MCPServer` implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp/server/mcpserver/server.py)
4. The baseline says multi-worker legacy HTTP could use “sticky routing or shared session infrastructure.” The released SDK documents an in-process session dictionary and supplies no distributed session-store hook. Its built-in choices are sticky routing for stateful legacy sessions or `stateless_http=True`, which sacrifices legacy backchannels. [`legacy clients guide`](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/run/legacy-clients.md#multiple-workers)

No other SDK fact checked here materially invalidates the existing migration note.
