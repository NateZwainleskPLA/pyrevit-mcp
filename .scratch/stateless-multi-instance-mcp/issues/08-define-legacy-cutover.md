# Define the legacy compatibility and cutover contract

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: 01, 05, 06

## Question

How are the MCP `2026-07-28` stateless endpoint and the temporary pre-`2026-07-28` compatibility path isolated, packaged, tested, selected by clients, observed, and eventually retired without letting legacy session assumptions leak into the target architecture?

## Comments

- 2026-08-20 SDK currentness verification: [MCP Python SDK currentness check](../../../docs/research/mcp-python-sdk-currentness-2026-08-20.md).
- 2026-08-21 lifecycle verification: [MCP legacy support and sunset policy](../../../docs/research/mcp-legacy-support-sunset-policy-2026-08-21.md).

## Answer

### One dual-era protocol implementation

- Pin the official Python MCP SDK and use one `MCPServer` implementation for every supported protocol revision. SDK `v2.0.0` is the current stable baseline and serves modern `2026-07-28` requests plus legacy handshake revisions `2024-11-05`, `2025-03-26`, `2025-06-18`, and `2025-11-25` from the same Streamable HTTP endpoint or stdio process.
- Do not build a Legacy Protocol Adapter, alternate endpoint, legacy-only executable, protocol flag, historical tool catalog, or targetless execution path. Protocol-era negotiation and framing belong to the SDK.
- Every era receives the same deterministic modern tool catalog. Revit-scoped and Document-scoped calls carry the explicit targets required by the canonical tool interface and submit through the same Target Runtime and target-owned Execution Queue. Legacy protocol sessions never store selected Revit Targets, Document Targets, or Revit Operations.

### Transport, sessions, and client selection

- Package one signed, self-contained helper. The same server implementation runs as the per-user loopback Streamable HTTP Adapter and as the optional client-spawned stdio form; no user-managed Python runtime is required for the packaged path.
- Both forms retain workstation installation discovery and permission-gated Revit launch, including explicit startup with zero Revit Hosts, under [Decide the fate of the Revit launch and installation-discovery tools](12-decide-launch-tools-fate.md). This uses the common modern catalog and helper; it is not a retained legacy bootstrap or targetless Revit execution path.
- Client configuration selects only the HTTP endpoint or stdio command. The client and SDK determine the protocol era automatically: modern peers use `server/discover` and self-describing requests, while handshake-era peers use `initialize`. There is no user-facing legacy selector.
- Retain the SDK's normal in-memory legacy HTTP sessions and backchannels in the single per-user Adapter process. Do not use the reduced legacy `stateless_http` mode merely to imitate modern statelessness. Adapter restart discards those protocol sessions and clients reinitialize; modern requests remain stateless and target-owned Revit Operations remain unaffected.

### Installation, migration, and rollback

- Configuration compatibility is not promised. Existing clients may require a one-time explicit migration to the Connection Descriptor's HTTP URL or the packaged stdio command. The Revit MCP Status surface and documentation provide copyable examples, but the product never discovers or edits client-owned configuration.
- Do not preserve old `main.py` paths, ports, SSE/combined modes, error wording, timing quirks, or the former single-Revit active-document tool semantics solely for compatibility.
- Update and rollback replace the complete extension package while Revit is closed, following the installation contract. There is no independently switchable legacy artifact or rollback mode.

### Supported revisions and retirement

- Accept the five revisions implemented by pinned SDK `v2.0.0` and add no pyRevit-owned revision allowlist. An SDK upgrade must deliberately review the tagged supported-version registry, SDK release and migration notes, MCP's deprecated-feature registry, and any future revision-support amendment to the SDK tiering policy.
- Schedule no pyRevit-specific revision sunset. MCP's twelve-month deprecation floor governs individual protocol features, not whole specification revisions; revision-support duration remains an open MCP policy question. Dropping a revision is a future explicit compatibility decision with release notes and migration guidance, unless an official security requirement demands faster action.

### Observation

- Record the negotiated revision and era, transport, self-reported `clientInfo`, legacy HTTP session creation and termination, negotiation failures, unsupported-version errors, Adapter version, and SDK version through the Forensic Record contract.
- Show aggregate current or last-seen legacy usage in the Revit MCP Status surface. Send no external telemetry, persist no request bodies for compatibility monitoring, and emit no pyRevit-authored warning merely because a supported legacy revision is used. Surface official SDK or specification deprecations when they exist.

### Focused compatibility acceptance

Test only the seams pyRevit MCP owns rather than duplicating the Tier 1 SDK's protocol suite:

1. Connect one in-memory modern client and one latest-legacy client to the same `MCPServer`, assert identical tool schemas, and execute one command through a fake Target Runtime.
2. Run one live mixed-era scenario proving modern and legacy commands enter one Revit Target's FIFO Execution Queue in order.
3. Run two installed-package smokes: modern HTTP and legacy stdio each connect and call target discovery.
4. Assert the packaged SDK version and confirm negotiated protocol era and revision reach the Forensic Record.

The broader acceptance contract owns the official modern MCP conformance run. pyRevit MCP does not separately retest every historical revision, SDK session behavior, or SDK-owned protocol error path.
