# MCP 2026-07-28 migration baseline

> **Research status:** complete as of 2026-08-10. This note is a migration input, not an implementation design. Normative claims come from the released MCP specification and final SEPs. SDK claims are pinned to the official Python SDK `v2.0.0` release. The Tasks discussion distinguishes the final extension SEP from the still-draft extension artifact.

## Executive answer

MCP 2026-07-28 makes each request self-describing and removes protocol-level sessions from the modern protocol. A server cannot infer protocol version, capabilities, client identity, selected Revit instance, selected document, or any other request context from a connection or an earlier request. Anything that must survive across calls needs an explicit identifier carried by every relevant call. This fits a workstation-local, multi-Revit architecture: publish one deterministic tool catalog and make the Revit instance and document explicit tool inputs rather than hidden connection state.

The released Python SDK `v2.0.0` implements the 2026-07-28 core alongside earlier MCP revisions in the same server process and endpoint. It supplies discovery, request metadata validation, HTTP header mirroring, cache hints, dual-era compatibility, and MRTR support. It does **not** implement the Tasks extension. Tasks therefore cannot be treated as part of the initial SDK migration: the implementation plan must either pin and implement the extension through the SDK's extension surface, defer it until an official SDK release supports it, or choose another implementation. Any Tasks plan also needs a non-Tasks fallback.

The protocol does not require a daemon, broker, database, installer, or globally installed Python tool. A disposable adapter launched by the MCP client can remain within the footprint of a pyRevit extension. The modern core is stateless even when the adapter process remains alive; process lifetime is not a protocol session.

## Normative core contract

### Requests are self-describing

Every request must include these namespaced fields in `params._meta`:

- `io.modelcontextprotocol/protocolVersion`: the protocol revision used by that request.
- `io.modelcontextprotocol/clientCapabilities`: the capabilities the server may rely on for that request. The object may be empty.
- `io.modelcontextprotocol/clientInfo`: optional, but clients should include it on every request.

Missing required metadata is invalid parameters (`-32602`; HTTP 400). A server must not use a client capability that was not declared on the current request. When a method needs a missing capability, the modern error is `MissingRequiredClientCapabilityError` (`-32021`; HTTP 400). Servers should include `io.modelcontextprotocol/serverInfo` in every result's `_meta`, but self-reported client/server identity is descriptive metadata, not an authentication primitive. Complete and input-required results are distinguished by `resultType`; clients speaking an older revision treat a result without that field as complete. [Basic protocol: statelessness and metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#statelessness)

The statelessness rule is stronger than “do not use cookies.” A server must not infer protocol version, capabilities, identity, or other context from the connection or a prior call. A reused stdio process is not a conversation boundary. Cross-request state is allowed only when the caller sends an explicit identifier on each relevant request. [Basic protocol: statelessness](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#statelessness)

**Migration consequence:** `revit_target`, `document_target`, job/task handles, and any other routing context belong in request arguments. A hidden “currently selected Revit” value, keyed by client connection or adapter process, would violate the modern model. The target identifiers also need authorization and expiry checks on every use; connection possession must not be treated as proof of authority.

### Discovery replaces initialization for modern peers

Modern servers must implement `server/discover`. Its complete result reports supported protocol versions and server capabilities, may include instructions, and should carry `serverInfo` in result metadata. Clients may call discovery before other methods, but they are also allowed to send any method directly. A server that cannot serve the requested revision returns `UnsupportedProtocolVersionError` (`-32022`) with the requested and supported revisions. [Server discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)

There is no modern negotiation handshake and no modern protocol session. The 2026-07-28 protocol removes `initialize`, `notifications/initialized`, and the lifecycle state they created. Each request independently declares a revision and is accepted or rejected on that basis. [Protocol versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)

A dual-era server may serve modern stateless requests and legacy initialized requests from the same process and endpoint. A dual-era stdio client should probe `server/discover`, then fall back only when the response demonstrates a non-modern peer. A dual-era HTTP client sends a modern request first and inspects the 4xx JSON-RPC response before deciding whether the endpoint is legacy. Clients should cache era detection for the lifetime of the process or HTTP origin. Modern-only and legacy-only peers do not interoperate without such compatibility behavior. [Protocol versioning and compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)

**Migration consequence:** do not build a second initialization mechanism for 2026-07-28. If Codex or another primary client is still legacy, compatibility is an adapter concern, not a reason to make the modern path stateful. Python SDK v2 can host both eras in one adapter.

### Streamable HTTP is request-scoped

The modern Streamable HTTP transport uses one MCP endpoint accepting one POST per JSON-RPC request or notification. A request receives either a JSON response or a request-scoped SSE stream; an accepted notification receives HTTP 202 with no body. The modern transport has no GET event-stream endpoint, `Mcp-Session-Id`, DELETE session termination, or resumable SSE/`Last-Event-ID` mechanism. [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

Every modern POST must carry:

- `MCP-Protocol-Version`, matching the protocol version in the body metadata.
- `Mcp-Method`, matching the JSON-RPC method.
- `Mcp-Name` for `tools/call`, `resources/read`, and `prompts/get`, derived from the body's name or URI.

The body remains the source of truth. Missing, malformed, or mismatched standard metadata produces HTTP 400 with `HeaderMismatch` (`-32020`). Unsupported protocol versions produce HTTP 400 with `-32022`; unknown methods produce HTTP 404 with `-32601`. Header names are case-insensitive, but values are case-sensitive. [Streamable HTTP: request metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

A server may mark statically reachable primitive tool properties (`string`, `integer`, or `boolean`) with `x-mcp-header`. A conforming HTTP client must then mirror each annotated argument to `Mcp-Param-{name}`. The server validates the header against the body, while the body remains authoritative. The specification defines a base64 sentinel encoding for values that cannot safely appear verbatim in a header and warns against annotating secrets. [Streamable HTTP: custom tool-parameter headers](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

**Migration consequence:** `revit_target` and perhaps `document_target` can remain normal tool arguments and optionally be annotated with `x-mcp-header`. That makes them visible to an HTTP router or gateway without changing the tool contract or the stdio implementation. This is an optimization and extension point, not a requirement for the first local adapter.

For security, an HTTP server must validate a present `Origin` and return 403 for an invalid origin. Local servers should bind only to `127.0.0.1`, and servers should authenticate connections. Therefore loopback binding plus strict Origin checking but no local secret is a documented deviation from a protocol **SHOULD**, not a violation of a **MUST**. [Streamable HTTP: security warning](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

### Catalogs and discovery are explicitly cacheable

Every complete result from `server/discover`, `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, and `resources/read` must include `ttlMs` (a non-negative integer) and `cacheScope` (`public` or `private`). A zero TTL is conforming and means immediately stale. `public` permits reuse across authorization contexts; `private` restricts reuse to the same context. Cache keys include method and parameters. Paginated pages are cached independently and must use a consistent scope. Notifications invalidate the corresponding cached data. MRTR interim results and retry requests carrying `inputResponses` or `requestState` are not cacheable. [Server caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)

The tool catalog must not vary by connection or because of side effects from earlier calls on that connection. It may vary by the authorization attached to the current request. Tool ordering should be deterministic to support catalog and prompt caching. [Tools: server capabilities](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#capabilities)

**Migration consequence:** expose one stable catalog regardless of which Revit instances happen to be open. Instance availability belongs in discovery resources or tool results, while instance/document selection remains explicit arguments. Start with deliberate cache hints, even if `ttlMs: 0` and `private`, and only increase TTLs when invalidation and determinism are tested.

### Explicit handles are the permitted state seam

The specification's stateless design pattern is to create state with one operation, return an opaque handle, and require that handle on all later operations. Handles should be authorized on each use, have enough entropy if possession grants access, have a bounded lifetime, and produce recoverable expiry errors. [Basic protocol: statelessness](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#statelessness)

**Migration consequence:** an instance registration identifier, document identifier, or durable job identifier is compatible with stateless MCP. The state behind it may live in Revit, the pyRevit extension, a file, or another component; what matters to MCP is that the adapter does not recover the context from connection history.

### MRTR asks for input; it is not a job system

Multi-round-trip requests (MRTR) replace the old server-initiated `roots/list`, `sampling/createMessage`, and `elicitation/create` flow. Only `prompts/get`, `resources/read`, and `tools/call` may return an input-required result. The result has `resultType: "input_required"`, `inputRequests`, and optionally opaque `requestState`. A client obtains the requested input and retries the original method and arguments with a new JSON-RPC request id, `inputResponses`, and the exact `requestState`. Each attempt is an independent request. [Multi-round-trip requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)

Because `requestState` is echoed by the client, the server must treat it as attacker-controlled. If it affects authorization, resource selection, or business logic, it needs integrity protection. The specification recommends binding it to the principal, expiry, and originating request; strict single-use replay prevention requires server-side storage. [MRTR: security](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)

**Migration consequence:** use MRTR when a Revit operation needs clarification, consent, a choice, or client-provided context. Do not use it to represent a durable long-running Revit operation. Adapter restart may invalidate an integrity-protected MRTR continuation if its signing key is process-local; that is acceptable only if the product explicitly treats the clarification flow as restartable rather than durable.

## Tasks is an official, separate extension

SEP-2663 is final and moved Tasks out of the core specification into an official extension so it can evolve independently. The extension remains outside the core protocol and must be advertised as `io.modelcontextprotocol/tasks` by the client on each request and by the server through discovery. A server must not return a task to a request whose client did not opt in. [SEP-2663: Tasks extension](https://modelcontextprotocol.io/seps/2663-tasks-extension)

The capability exchange is structural rather than a second handshake. The client puts `{"extensions": {"io.modelcontextprotocol/tasks": {}}}` inside the current request's `io.modelcontextprotocol/clientCapabilities`; the server publishes the same empty extension object inside `server/discover.result.capabilities`. There are no extension-specific settings at the pinned revision. If a request can only be serviced as a task and the current request did not declare support, the extension specifies `-32003` with the required extension in error data. This differs from the modern core's general missing-capability code `-32021`, another reason to pin the extension revision. [Pinned draft: capability negotiation](https://github.com/modelcontextprotocol/ext-tasks/blob/2c1425d9a288b9b1f489430fe1e00bb392b47e48/specification/draft/tasks.md#capability-negotiation)

The current extension repository nevertheless labels Tasks **Experimental**, stores its specification and schema under `draft`, and warns that it is under active development. The migration must therefore pin a concrete extension schema/revision rather than referring only to “latest Tasks.” This baseline uses repository commit `2c1425d9a288b9b1f489430fe1e00bb392b47e48`. [Tasks extension repository](https://github.com/modelcontextprotocol/ext-tasks) [Pinned draft Tasks specification](https://github.com/modelcontextprotocol/ext-tasks/blob/2c1425d9a288b9b1f489430fe1e00bb392b47e48/specification/draft/tasks.md)

At that revision:

- Only `tools/call` is augmented. A supporting client must accept either a normal `CallToolResult` or a `CreateTaskResult`; the server decides per invocation.
- `CreateTaskResult` uses `resultType: "task"` and includes a unique `taskId`, status, creation/update timestamps, nullable TTL, and optional polling interval and status message. The task must be durably created before the response so an immediate `tasks/get` succeeds.
- Status is one of `working`, `input_required`, `completed`, `failed`, or `cancelled`. The terminal states are completed, failed, and cancelled.
- `tasks/get` is the default polling mechanism and returns full task state; terminal results or JSON-RPC errors are returned inline. An `input_required` task exposes input requests, answered through `tasks/update`.
- `tasks/cancel` requests cooperative cancellation. Optional `notifications/tasks` can reduce polling, but polling remains the baseline. There is no global `tasks/list`; clients must retain their task identifiers.
- Over Streamable HTTP, `tasks/get`, `tasks/update`, and `tasks/cancel` must carry `Mcp-Name` equal to `params.taskId`, enabling an intermediary to route all operations for one task to the state owner.
- A failed task represents execution failure. A successful tool execution whose normal content has `isError: true` is a completed task containing that tool result, not a failed task.
- Task identifiers need sufficient entropy when possession functions as authority, and retention is bounded by TTL.

The extension requires durable creation but does not prescribe whether durability belongs to the adapter, the pyRevit extension, Revit, a local file, or a daemon. That is an architecture decision. It also does not make a short-lived adapter magically durable across process or workstation failure.

**Required migration decision:** define synchronous/non-Tasks behavior before adopting Tasks. A client that does not advertise the extension must receive an ordinary synchronous result or a documented error/fallback; it must never receive `resultType: "task"`. Also pin the wire revision, including `notifications/tasks`; older experimental material used a different notification name.

## Released Python SDK surface

The official Python SDK `v2.0.0`, released with MCP 2026-07-28, is the first stable v2 release and requires Python 3.10 or newer. It serves the modern revision and previous revisions from the same MCP server, endpoint, or stdio process. The release explicitly lists the Tasks extension as not yet supported. [Python SDK v2.0.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0) [What's new in v2](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/whats-new.md)

### API changes the project must account for

| Concern | Current project / v1-era shape | Released v2 shape | Migration consequence |
|---|---|---|---|
| High-level server | `from mcp.server.fastmcp import FastMCP, Image, Context` | `from mcp.server.mcpserver import MCPServer, Context, Image` (with `MCPServer` and `CacheHint` also re-exported from `mcp.server`) | Rename imports and construction; decorators remain broadly familiar. |
| Transport configuration | Host, port, `stateless_http`, and `json_response` passed to the constructor | Transport-specific settings passed to `run(...)` or the ASGI app builder | Move configuration out of server construction. |
| HTTP run | v1-era `run(transport="streamable-http")` with constructor settings | `run("streamable-http", host=..., port=..., streamable_http_path="/mcp", json_response=..., stateless_http=...)` | Update CLI/transport branches and tests. |
| Modern statelessness | Often associated with `stateless_http=True` | Modern 2026 requests are always sessionless; `stateless_http` controls only the legacy HTTP compatibility leg | Do not use this flag as the feature switch for the modern protocol. |
| Cache metadata | Application-specific or absent | `MCPServer(..., cache_hints={method: CacheHint(ttl_ms=..., scope=...)})`; safe defaults are zero/private and low-level results may override | Choose explicit policies for discovery/catalogs; SDK defaults are conforming but intentionally non-reusable. |
| MRTR | Legacy live-session backchannels | High-level resolve/elicit dependencies select modern MRTR or legacy backchannel automatically; low-level handlers may return `InputRequiredResult` | Prefer the SDK abstraction when the same tool must support both eras. |
| MRTR continuation security | Application concern | `RequestStateSecurity` seals state; the default key is process-local | A restarted disposable adapter invalidates outstanding MRTR unless a stable key is intentionally supplied. |
| Standard HTTP headers | Application plumbing | Server validates/emits standard metadata; client mirrors `x-mcp-header` fields after tool discovery | Do not duplicate SDK header plumbing. Test the target annotations instead. |
| Dual-era support | Separate assumptions around initialization/session mode | One server automatically supports modern and legacy peers | A second adapter is not required merely for protocol compatibility. |
| Tasks | Experimental/core-era material sometimes suggested SDK support | Not implemented in `v2.0.0` | Gate Tasks as a later/manual extension decision and retain fallback behavior. |

The authoritative v2 constructor and run interfaces are in the released server implementation. [MCPServer implementation at v2.0.0](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp/server/mcpserver/server.py) The SDK's caching helpers define the high-level cache configuration and defaults. [Python SDK caching implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp/server/caching.py) The official migration guide covers renamed modules, transport arguments, and other breaking changes. [Python SDK v2 migration guide](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/migration.md)

For MRTR, the high-level dependencies expose returned inputs through the request context, and the official client defaults to completing up to ten input-required rounds unless configured otherwise. Low-level callers can opt to observe `InputRequiredResult` directly. [Python SDK MRTR guide](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/handlers/multi-round-trip.md)

Legacy behavior still matters operationally. The v2 server can keep legacy sessions in memory; a legacy stateless option removes capabilities that need a backchannel, while multiple workers serving stateful legacy HTTP require sticky routing or shared session infrastructure. A single on-demand workstation adapter avoids that multi-worker problem. None of these legacy choices alter the modern protocol's statelessness. [Python SDK legacy clients guide](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/run/legacy-clients.md)

### Project dependency baseline

The repository currently declares `mcp[cli]>=1.9.0` without an upper bound, while its lock and requirements snapshots identify different 1.x releases. The server code imports the v1 `FastMCP` API and passes transport settings in the v1 location. Consequently, a fresh unconstrained install can resolve to v2 while the source still expects v1. [Project dependency declaration](../../pyproject.toml) [Current server entry point](../../main.py) [uv lock snapshot](../../uv.lock) [requirements snapshot](../../requirements.txt)

The migration should select one canonical dependency workflow and deliberately pin the major (for example, `mcp>=2.0,<3`, with an exact lock). It must regenerate the lock from that declaration. The project also imports `httpx` directly; v2 no longer guarantees it as a transitive dependency, so `httpx` should be an explicit project dependency if those imports remain. This avoids making the install accidentally dependent on unrelated SDK internals.

## Recommended specification baseline for this project

1. **Adopt Python SDK v2 as the core migration target.** Pin a deliberate v2 range or exact initial release, migrate `FastMCP` to `MCPServer`, relocate transport configuration, and regenerate one canonical lock. Do not equate `stateless_http=True` with modern statelessness.
2. **Keep the adapter disposable.** Let the MCP client launch a bundled adapter over stdio by default. The adapter owns protocol translation and discovery, while the pyRevit extension and explicit handles expose live Revit-instance state. MCP 2026-07-28 does not require a permanently installed service.
3. **Use one stable catalog.** Every tool accepting a model-dependent operation takes an explicit `revit_target`; operations needing a specific document also take `document_target`. Catalog contents and ordering do not depend on connection history or whichever Revit window was last active.
4. **Use discovery and cache hints deliberately.** Publish supported revisions and capabilities with `server/discover`. Begin with zero/private hints where validity is uncertain; define TTL and invalidation before enabling reusable catalogs or resource reads.
5. **Retain SDK-provided dual-era behavior.** Allow current clients to use the legacy leg while modern requests remain independently self-describing. A physically separate legacy endpoint is optional topology, not a spec requirement.
6. **Use MRTR only for interactive completion.** Seal request state, bind it to the originating call and principal when material, and allow a clarification flow to restart if a disposable adapter exits unless persistent signing keys are explicitly justified.
7. **Treat Tasks as a gated phase.** Pin an extension commit/schema, decide the durability owner and TTL/restart contract, choose an implementation path despite the Python SDK gap, and specify synchronous behavior for clients without Tasks before advertising the capability.
8. **Keep local HTTP security proportional and explicit.** If HTTP is enabled, bind loopback and enforce Origin validation. Record the decision not to require a local bearer secret as acceptance of a specification SHOULD-level risk, and revisit authentication before any non-loopback or multi-workstation exposure.
9. **Test conformance at the protocol boundary.** Add request fixtures for required metadata, discovery/version errors, header/body mismatches, deterministic cacheable catalogs, MRTR retry integrity, and capability-gated Tasks. The MCP project publishes an official conformance suite that should be included when the implementation begins. [Official MCP conformance repository](https://github.com/modelcontextprotocol/conformance)

## Decisions the migration specification must still make

- Which Codex MCP revisions and transports are available at implementation time. That requires separate OpenAI/Codex research; MCP-owned sources cannot establish Codex support.
- Whether initial local operation is stdio-only or also exposes a loopback Streamable HTTP endpoint.
- The exact `revit_target` and `document_target` handle format, discovery mechanism, lifetime, and recoverable expiry behavior.
- Whether HTTP target fields receive `x-mcp-header` annotations now or only when a router exists.
- Catalog/resource TTL values and invalidation signals beyond the conforming zero/private baseline.
- Whether Tasks waits for SDK support, is implemented against a pinned extension through the SDK extension surface, or uses another SDK; plus where task state is durable and what survives adapter/Revit/workstation restart.
- The non-Tasks behavior for operations that may exceed a client's synchronous timeout.
- The canonical package/lock workflow and how the adapter is bundled so a typical Revit user does not need to understand or install `uv`.

## Primary sources

- [MCP 2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [MCP 2026-07-28 release announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/) (official but non-normative)
- [SEP-2663: Tasks extension](https://modelcontextprotocol.io/seps/2663-tasks-extension)
- [Tasks extension repository](https://github.com/modelcontextprotocol/ext-tasks)
- [Python SDK v2.0.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)
- [Python SDK v2.0.0 source and documentation](https://github.com/modelcontextprotocol/python-sdk/tree/v2.0.0)
