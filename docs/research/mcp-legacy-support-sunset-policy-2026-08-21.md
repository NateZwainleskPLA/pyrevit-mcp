# MCP legacy support and sunset policy — 2026-08-21

## Verdict

MCP does **not** impose a one-year sunset on past protocol revisions. The twelve-month rule in the current specification is a minimum deprecation period for an individual **feature**, expressly separate from the lifecycle of whole specification revisions. How long Tier 1 SDKs must support older revisions remains an open policy question. Therefore pyRevit MCP should not invent a one-year retirement date for handshake-era revisions.

The current official Python SDK gives a simpler operational policy: stable `mcp==2.0.0` serves `2026-07-28` and every earlier released revision from one server, with no switch to disable an era. pyRevit should support the revisions built into its pinned SDK and review that support deliberately whenever it upgrades the SDK. It should not promise indefinite support beyond the SDK, but there is no official date requiring a sunset now.

## What the normative specification says

### Revision support is optional and has no fixed window

The `2026-07-28` Versioning and Compatibility specification defines modern, legacy, and dual-era implementations. A server **MAY** implement both modern and legacy behavior, and a dual-era server **MAY** serve both eras concurrently on one endpoint or process. Conversely, a server may choose not to support a known revision; it must return `UnsupportedProtocolVersionError` and list the versions it does support. No minimum duration is attached to supporting an older revision. [Protocol Version Negotiation](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning#protocol-version-negotiation) · [Backward Compatibility with Initialization-Based Versions](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning#backward-compatibility-with-initialization-based-versions)

The general versioning guide classifies whole revisions as Draft, Current, or Final. A superseded revision becoming Final means its text stops changing; it does not create a server or SDK support deadline. The same guide says implementations **MAY** support multiple revisions simultaneously. [Revisions](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning#revisions) · [Negotiation](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning#negotiation)

### The twelve-month floor applies to features, not revisions

SEP-2596 explicitly scopes its lifecycle policy to individual protocol features and excludes both the lifecycle of whole specification revisions and SDK-specific API lifecycles. A newly deprecated feature must remain Deprecated for at least twelve months before it is merely **eligible** for removal; removal is a later Core Maintainer decision and is not automatic when the clock expires. A security exception can shorten the floor, but still requires at least ninety days. [SEP-2596: Scope and feature states](https://modelcontextprotocol.io/seps/2596-spec-feature-lifecycle-and-deprecation#scope) · [Deprecating a feature](https://modelcontextprotocol.io/seps/2596-spec-feature-lifecycle-and-deprecation#deprecating-a-feature) · [Removing a feature](https://modelcontextprotocol.io/seps/2596-spec-feature-lifecycle-and-deprecation#removing-a-feature)

Most decisively, SEP-2596 leaves the **specification revision support window** as an open question for a future amendment to the SDK Tiering policy. Its rationale records that maintainers had floated a “one year supported plus one year deprecation” model, but the adopted twelve-month rule is the feature-level policy—not adoption of that revision-level proposal. [SEP-2596: Why twelve months?](https://modelcontextprotocol.io/seps/2596-spec-feature-lifecycle-and-deprecation#why-twelve-months) · [SEP-2596: Open Questions](https://modelcontextprotocol.io/seps/2596-spec-feature-lifecycle-and-deprecation#open-questions)

That distinction also appears in SEP-1730: Tier 1 SDKs must support new protocol features by release and meet maintenance/conformance expectations, but the accepted text contains no trailing one-year obligation for old revisions. [SEP-1730: Tier 1 requirements](https://modelcontextprotocol.io/seps/1730-sdks-tiering-system#tier-1-fully-supported)

### The one-year memory likely came from feature deprecations

The `2026-07-28` deprecated-feature registry gives Roots, Sampling, Logging, and Dynamic Client Registration an earliest removal in the first revision released on or after `2027-07-28`. Those are feature sunsets, not a deadline for accepting `2025-*` protocol requests. The registry also identifies HTTP+SSE as a separately deprecated **transport** with Streamable HTTP as its migration path. A legacy handshake revision can still run over Streamable HTTP, so retiring HTTP+SSE does not require retiring legacy protocol negotiation. [Deprecated Features registry](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)

The release blog describes deprecated features as receiving at least twelve months and calls the HTTP+SSE migration a year-long offramp. The normative registry is more precise: HTTP+SSE was grandfathered because it had already been publicly deprecated for over twelve months and becomes eligible for removal three months after SEP-2596 reaches Final. Neither statement creates a sunset for all pre-2026 revisions. [Official `2026-07-28` release announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/#deprecations) · [SEP-2596 transition provisions](https://modelcontextprotocol.io/seps/2596-spec-feature-lifecycle-and-deprecation#transition)

## What the official Python SDK promises today

Stable Python SDK `v2.0.0` says that one `MCPServer` serves `2026-07-28` and every earlier revision. Its tagged protocol registry enumerates `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, and `2026-07-28`. This is a current implementation commitment, not a normative MCP guarantee or a time-based maintenance promise. [`v2.0.0` release notes](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0#one-sdk-both-protocol-eras) · [tagged protocol registry](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/src/mcp-types/mcp_types/version.py)

The tagged legacy-client guide says both eras are always enabled on `MCPServer`: there is no legacy flag, version allowlist, or rejection setting. The SDK owns handshake/session compatibility, while pyRevit's handlers can remain shared. Again, the guide gives no retirement date. [`v2.0.0` legacy-client guide](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/docs/run/legacy-clients.md)

The SDK's separate statement that `v1.x` receives critical and security fixes describes maintenance of the old **SDK major line**, not a deadline for protocol revisions served by `v2`. [`v2.0.0` release notes: v1 maintenance mode](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0#v1-maintenance-mode)

## Recommended correction to provisional Q12

**Q12R — Legacy revision retirement:** Is dual-era support subject to a fixed sunset?

**Decision:** No fixed pyRevit sunset is scheduled. pyRevit MCP supports every protocol revision implemented by its deliberately pinned official Python SDK release, using the SDK's one-server dual-era behavior. This is not a promise of indefinite compatibility: every SDK upgrade must review the tagged supported-version registry, release notes, the MCP deprecated-feature registry, and any future revision-support amendment to SEP-1730. Dropping a revision is an explicit compatibility decision with release-note and migration guidance, unless an official security requirement demands faster action. Do not apply SEP-2596's twelve-month feature-deprecation clock to whole protocol revisions.

This replaces the provisional rationale that legacy support is permanent or “negligible.” The outcome remains **no invented sunset today**, but for the evidence-backed reason that the specification has not adopted a revision-support window and the pinned SDK currently carries the compatibility.
