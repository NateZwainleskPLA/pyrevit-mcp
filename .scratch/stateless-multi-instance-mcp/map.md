# Specify a stateless, multi-instance Revit MCP architecture

Label: wayfinder:map

## Destination

An implementation-ready migration specification for moving this project to the MCP `2026-07-28` stateless core while supporting multiple Revit instances and documents on one workstation, retaining SDK-provided dual-era protocol interoperability, and keeping the installed product within one pyRevit extension footprint.

## Notes

- Planning only: this map resolves decisions and produces no migration implementation.
- Tracker: use the version-controlled local Markdown map and child tickets in `.scratch/stateless-multi-instance-mcp/`. Ticket metadata records type, status, assignee, and blocking; take the first open, unblocked, unclaimed ticket by filename order. Claim before work and resolve with an `## Answer` plus a pointer here. Research evidence lives in `docs/research/`.
- Apply the upstream contribution and development-build policy in [Decide product ownership, signing identity, and upstream relationship](issues/18-decide-ownership-and-signing.md#answer).
- Consult `CONTEXT.md` for the canonical distinction between Protocol Statelessness, Revit Runtime State, Revit Hosts, Revit Targets, Document Targets, Revit Operations, the Workstation Trust Boundary, and the Extension Footprint.
- Use the `research`, `grilling`, `domain-modeling`, and `codebase-design` skills as appropriate when resolving tickets.
- Codex is the primary eventual client, but native Codex support for MCP `2026-07-28` does not gate the target architecture. The endpoint is gated by a protocol-conformance harness and uses the pinned SDK's dual-era behavior for clients that still negotiate an earlier revision.
- Prefer no user-managed Python, `uv`, or package prerequisites, but treat this as a soft preference when avoiding them would impose disproportionate packaging or maintenance cost.
- An on-demand helper launched from files bundled in the pyRevit extension is within the allowed footprint. A persistent daemon, Windows service, or external database is not.
- Trust processes running as the current Windows user. Require loopback exposure and baseline Origin validation, but do not expand this effort into strong same-user isolation.

## Decisions so far

<!-- Resolved ticket pointers are appended here. -->

- [Research the released stateless MCP contract and SDK surface](issues/01-research-stateless-mcp-contract.md) — MCP `2026-07-28` supports explicit-handle statelessness and dual-era SDK serving, while Tasks must be pinned and separately implemented or deferred because Python SDK `2.0.0` does not yet support it.
- [Research packaging an on-demand MCP helper within a pyRevit extension](issues/02-research-helper-packaging.md) — A signed Windows-x64 PyInstaller helper is the preferred no-prerequisite artifact, embeddable CPython is the larger fallback, and bundled `uv` is best kept as a support/developer escape hatch.
- [Define Revit Target and Document Target identity semantics](issues/03-define-target-identity.md) — Opaque exposure-generation and document-incarnation handles, one nested Target Snapshot, explicit request scopes across protocol eras, and fail-with-rediscovery validation prevent silent routing to the wrong Revit process or document.
- [Choose MCP adapter topology and durable state ownership](issues/04-choose-runtime-topology.md) — A disposable per-user Streamable HTTP adapter discovers native pyRevit registrations and routes through a replaceable Target Runtime interface, while each Revit Target owns its queue and in-memory operations for that target's lifetime.
- [Choose the installation and runtime packaging contract](issues/05-choose-installation-contract.md) — One no-prerequisite extension package carries independently versioned compatible artifacts, starts a client-agnostic adapter with per-host opt-in target exposure, and provides descriptor-based connection discovery plus explicit status and cleanup controls.
- [Define the Revit Operation lifecycle and task fallback](issues/06-define-operation-lifecycle.md) — Every target-bound command uses one target-owned operation with a five-state lifecycle, a five-second inline handoff, four-hour result retention, cooperative cancellation, protocol-neutral polling, and a deferred Tasks projection.
- [Define concurrency, retry, and stale-target safety](issues/07-define-execution-safety.md) — Each Revit Target gets one bounded FIFO execution lane with atomic idempotent admission, explicit validation and effect guarantees, exact-payload retry recovery, cross-target parallelism, draining, and quarantine containment.
- [Define the legacy compatibility and cutover contract](issues/08-define-legacy-cutover.md) — One pinned SDK v2 server owns dual-era protocol interoperability while every client uses the same explicit-target tools, shared execution path, package, local diagnostics, and SDK-governed revision support.
- [Define the Forensic Record contract](issues/10-define-diagnostic-journal.md) — A bounded per-user evidence record uses isolated correlated streams and exact-code artifacts, strict non-code minimization, coherent support export, configurable retention, and non-authoritative degraded-write behavior.
- [Define the conformance and acceptance contract](issues/09-define-acceptance-contract.md) — Separate specification and implementation gates require traceable decisions, layered automated and live-Revit evidence, declared support coverage, failure injection, bounded performance, signed packaging, and verified operator/developer documentation.

- [Decide the fate of the Revit launch and installation-discovery tools](issues/12-decide-launch-tools-fate.md) — Installation discovery remains available, every agent launch requires a default-off user setting independent of exposure, and the same helper supports client startup before Revit with a bounded HTTP startup window or client-lived stdio.

- [Reconcile the per-user storage root across topology, installation, and Forensic Record decisions](issues/13-reconcile-storage-root.md) — One fixed Local AppData product root holds the descriptor, settings, and evidence; independent Windows resolution and a compatibility check isolate mismatched hosts while preserving existing operation controls.

- [Retire the temporary legacy execution path from the target-identity decision](issues/14-retire-legacy-execution-path.md) — The cutover contract supersedes targetless execution across protocol eras; privileged scoped code remains, and old tool-specific Routes scaffolding must be removed before the first accepted signed release.

- [Define the explicit-target tool catalog and per-command declarations](issues/15-define-tool-catalog.md) — A deterministic 23-tool catalog binds commands to explicit targets, makes UI changes and broad-view coloring opt-in, requires explicit reset-all clearing, and defines per-command execution declarations plus bounded process-correlated launch behavior.

- [Choose the pyRevit engine for host-side runtime code](issues/16-choose-host-engine.md) — IronPython 2.7.12 runs host-side code; the release-time newest stable pyRevit sets the shipped minimum, 6.5.4 remains the development baseline, and incompatible hosts stay unexposed with local diagnostics.

- [Prototype the in-Revit execution lane and control plane over pyRevit Routes](issues/17-prototype-host-execution-lane.md) — A private ExternalEvent and synchronized control registry passed live queue, pick, document, and rollback probes; intermittent Routes failure around reload leaves listener lifecycle as a separate decision.

- [Decide product ownership, signing identity, and upstream relationship](issues/18-decide-ownership-and-signing.md) — Upstream contribution with optional maintenance participation, explicit unsigned developer builds, and upstream-owned signed production releases subject to actual upstream agreement.

## Not yet specified

<!-- No remaining un-ticketed fog is currently identified. Open child tickets still remain. -->

## Out of scope

- Implementing the migration described by the destination specification.
- Purchasing or provisioning signing credentials and implementing release automation; this map establishes the responsible parties and release contract for the implementation handoff.
- An independently maintained fork distribution, under [Decide product ownership, signing identity, and upstream relationship](issues/18-decide-ownership-and-signing.md#answer).
- Remote multi-workstation discovery, routing, authentication, and authorization; the local target model should leave a clean extension path without designing that system now.
- A broad redesign of tool names, descriptions, or capabilities unless a concrete MCP `2026-07-28` incompatibility requires it.
- Strong isolation from processes running as the same Windows user.
- Establishing or implementing native Codex support for MCP `2026-07-28`.
