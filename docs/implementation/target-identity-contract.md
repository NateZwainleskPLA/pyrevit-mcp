Target identity foundation
==========================

Wire metadata is a raw JSON object at `GET /revit_mcp/metadata/`. It contains
`instance_id`, `runtime_id`, `process_id`, `process_started_at` (UTC ISO-8601),
`revit_version`, `endpoint` (absolute API-root URL, including explicit port),
`documents`, `documents_known`, `snapshot_at` (UTC epoch seconds or null), and
`snapshot_age_seconds` (seconds or null). Document descriptors contain exactly
`document_id`, `title`, `path`, `is_active`, `is_family_document`. Linked documents
are excluded from snapshots and fresh receiver resolution. Editable family
documents remain targets, classified by `is_family_document=true`. The validator
defaults that field to false on older descriptors; it is descriptive only and
cannot authorize per-tool eligibility. Tool restrictions must examine the freshly
resolved native document's properties. Optional primitive provenance fields
are `revit_build`, `engine_version`, `connector_version`, `snapshot_error`.
`runtime_available=false` rejects discovery of an expired runtime.

Before the first successful API-context collection, `documents_known=false`,
`documents=[]`, and the timestamp/age are null. A failed collection preserves
the previous snapshot and timestamp and adds an error. An empty known list is
different from an unknown list. Cached freshness is evidence, not proof that a
document remains open. Every document execution re-enumerates live documents.

Receiver interface (IronPython 2.7 compatible)
--------------------------------------------

`revit_mcp.target_registry.get_registry()` returns the runtime registry or raises
`IdentityError('runtime_unavailable', ...)`. The native startup adapter installs
it via `set_registry(registry)`. Reload expires the previous registry.

- `registry.snapshot()` copies primitives under a lock, without reading wrappers.
- `registry.validate_target(instance_id, runtime_id)` validates canonical full
  UUIDs and exact equality with the current runtime. Safe on HTTP workers.
  Returns `{instance_id, runtime_id}`.
- `registry.refresh_documents(documents, active_document=None)` collects live
  descriptors atomically. **API context only.**
- `registry.resolve_document(instance_id, runtime_id, document_id, documents,
  active_document=None)` freshly collects and resolves an open token to a live
  `DB.Document`. **API context only.** Pass `uiapp.Application.Documents` and
  `uiapp.ActiveUIDocument.Document` if present. Neither title nor path resolves
  a document. Inactive documents may be resolved without activation.
- `registry.expire()` retires this runtime without dereferencing wrappers.

For directed routes send top-level `instance_id`, `runtime_id`, and (when scoped)
`document_id` in the POST JSON body or GET query parameters. Aliases are client
directory keys, never receiver identity. Routing owns request parsing, route
guards and response wrapping; suggested actual identity field is
`actual_target: {instance_id, runtime_id, document_id?}`. Discovery metadata is
the intentionally untargeted exception. The explicit refresh route
`GET /metadata/refresh/` accepts instance/runtime UUID query parameters and
requests `uiapp` API-context injection. It is read-only, but can wait behind
busy or modal Revit work.
Query-parameter injection into handler keyword arguments is required. The
supported source baseline for that feature is pyRevit 7.0.0.26254; older builds
need equivalent injection support and have not been established compatible.

Client directory interface (CPython)
-----------------------------------

`tools.target_directory.TargetDirectory(state_path=None)` creates a fresh
in-memory namespace or opens a durable SQLite namespace. `close()` releases it.

- `observe(snapshot, expected_endpoint=None, registration=None)` validates a
  successful metadata handshake, checks optional discovery evidence, records
  it, and returns metadata decorated with a `target` handle and a `document`
  handle per descriptor. Repeated identities retain the same handles.
- `targets()` returns cached decorated metadata including `verified`. Persisted
  targets initially show `verified=false` in every new directory object.
- `await revalidate(target, handshake)` calls the injected async
  `handshake(endpoint) -> raw metadata`, verifies full UUIDs and process lifetime,
  then marks that target verified. A transport error leaves it unverified; a
  different endpoint owner permanently retires it. No fallback occurs.
- `resolve(target, document=None)` returns `{target, endpoint, instance_id,
  runtime_id, process_id, process_started_at, document?, document_id?}` or raises
  `IdentityError`. Unknown, expired, unverified, missing and cross-target handles
  fail distinctly. Routing should revalidate before each directed transport call
  and still validate full IDs at the receiver.

Handles have opaque form `r<namespace-base64url>.<counter>` and
`d<namespace-base64url>.<counter>`. The 22-character namespace is the full 128-bit
UUID encoded compactly. The namespace must be carried in the handle because a
bare `r17` cannot distinguish fresh state from a previously lost directory.
No alias is ever remapped or reused. SQLite `BEGIN IMMEDIATE` serializes counter
allocation, including across MCP processes. Retired records persist. Corrupt
or unsupported state fails closed; deleted/lost state creates a fresh namespace.
Persisted snapshots never bypass restart revalidation. The state path belongs
to the client deployment; no shared pyRevit/add-in settings are modified.

Native registration is endpoint/PID discovery evidence, not identity. JSON
records and native registration must agree with a successful `/metadata/`
handshake. Do not load native pyRevit pickle records in the MCP process: they
are trusted only through pyRevit's registration API inside its host. Configured
remote endpoint discovery uses the same handshake contract.

Native startup and discovery composition
----------------------------------------

`revit_mcp.target_runtime.initialize_identity(api)` runs at extension startup,
using pyRevit `serverinfo.register()` for this process's endpoint. It retains only
the process UUID as JSON in CLR AppDomain process storage; every initialization
creates a new runtime UUID. Owned CLR event delegates are retained separately
and disabled and removed before replacement. Each exact detachment is attempted
before expiring the old registry. An expiration error is diagnostic; a detach
error retains the disabled slot and exact remaining delegates and rejects a
replacement. Partial subscription failures use the same retained cleanup.
Process timestamps use the invariant Gregorian culture, independent of the
Windows locale. Startup does not activate or change the Routes
listener. It collects once when startup has API context, then collects on
document open/close, view activation, and throttled Idling API callbacks.

`initialize_identity(api)` remains strict. Targeted/disabled composition must
invoke its startup ownership guard before calling it, and must propagate failure
without exposing legacy fallback routes. This PR's legacy-only startup instead
uses `initialize_legacy_identity(api)`: identity errors expire/clear the installed
registry and replace both metadata routes with request-only HTTP 503 responses
`{api_name: "revit_mcp", runtime_available: false, error_code: "runtime_unavailable",
error: <cached diagnostic>}`. These responses have no UUIDs or document list and
never establish discovery or readiness. Even a failure after normal metadata
registration replaces those handlers. Independent legacy route/liveness
registration remains available. This wrapper is forbidden in targeted or disabled
composition; `/health/` must never be routed through `TargetedAPI`.

Empty/default and wildcard bind hosts (`""`, `0.0.0.0`, `::`) advertise
`127.0.0.1`, matching the default IPv4 discovery/listener. An explicitly
IPv6-only listener must advertise `::1` via `REVIT_MCP_ADVERTISED_HOST` and use
`REVIT_HOST=::1` for probing. Explicit advertised overrides are preserved. Bind
normalization does not configure, start, or establish readiness of a listener.

Registration evidence is written atomically to
`%APPDATA%/pyRevit/RevitMCP/registrations/<pid>.json`, or
`REVIT_MCP_REGISTRATION_DIR`. It is derived from native pyRevit registration.
It does not contain live document wrappers or substitute for a metadata handshake.
Native publishers serialize record replacement/pruning with an exclusive
Windows file lease in that connector directory; contention does not block the
API thread. Under the lease, only dead-PID or mismatched-process-start records
are pruned. Inaccessible, invalid, or unrelated files are retained. Stale temporary
files belonging to this process are removed. No recursive deletion occurs.
Failure to publish logs a diagnostic; configured endpoint discovery still works.

`tools.target_discovery.TargetDiscovery(directory, candidates=configured_candidates,
handshake=metadata_handshake, local_validator=validate_local_ownership)` provides
`await discover() -> {namespace, targets, errors}` and `await revalidate(target)`.
Candidates are injected records `{endpoint, registration?, source?}`. Registration
records are ordered newest first before the 256-record cap. All records for a
probed endpoint are compared against one verified handshake. A matching live
record takes precedence; stale records produce diagnostics and never veto an
independently verified endpoint. Default discovery reads only
connector JSON records and probes a bounded configured range; it never unpickles
pyRevit records. Environment variables are `REVIT_HOST`, `REVIT_PORT_SCAN_START`
(or `REVIT_PORT`), and `REVIT_PORT_SCAN_COUNT` (default 6, maximum 256).
For a remotely accessed connector, `REVIT_MCP_ADVERTISED_HOST` can explicitly
advertise its reachable host name while keeping pyRevit's listening host setting.
The client must probe that advertised API-root address; no address guessing occurs.

Only a successful HTTP 200 `/metadata/` JSON response qualifies, with redirects
disabled. Metadata must agree with the probed endpoint; accepted registration
evidence must agree with its full identities and process lifetime. Windows
loopback discovery additionally checks process creation time
and listener port ownership using the Windows process/TCP APIs. Remote targets
use the full metadata handshake; it does not establish authentication. A local
ownership inspector can be injected for another platform; absence of local proof
fails closed. A rejected probe does not select or substitute another process.
`await discovery.verified_handshake(endpoint)` is the public injection seam for
the routing transport: it returns raw metadata after the same ownership checks.
`tools.windows_target_evidence.process_started_at(pid)` returns an exact UTC
ISO-8601 creation timestamp (six fractional digits) for launch verification.

`tools.target_tools.register_target_tools(mcp, directory, discovery)` registers
`list_revit_targets(ctx)` and `get_revit_target_metadata(target, ctx)`. Both return
structured dictionaries. The composition root injects a shared directory and
discovery object. Registration in `main.py` and the existing `tools/__init__.py`
belongs to the routing workstream, together with its public target cutover.

Validation and limits
---------------------

Unit coverage includes duplicate titles, active-document switches, close/reopen,
invalid-wrapper comparison, stale runtime, process/PID/port reuse, conflicting
registration, concurrent allocation across threads/processes, persistent restart
revalidation, state loss/non-reuse, and out-of-order snapshots. These tests do
not establish native Revit API context, wrapper lifetime across pyRevit engines,
or listener/event reload behavior. The Windows ownership adapter was tested
against the test process and its own disposable TCP socket; it contacted no
Revit process. Mock lifecycle tests establish owned-delegate replacement only
within the controlled host double. No disposable native fixture was supplied.
The foundation does not make the legacy mutation tools explicitly targeted;
that receiver/tool cutover belongs to the routing workstream.
