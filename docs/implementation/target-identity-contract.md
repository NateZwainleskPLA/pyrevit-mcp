Target identity foundation
==========================

Wire metadata is a raw JSON object at `GET /revit_mcp/metadata/`. It contains
`instance_id`, `runtime_id`, `process_id`, `process_started_at` (UTC ISO-8601),
`revit_version`, `endpoint` (absolute API-root URL, including explicit port),
`documents`, `documents_known`, `snapshot_at` (UTC epoch seconds or null), and
`snapshot_age_seconds` (seconds or null). Document descriptors contain exactly
`document_id`, `title`, `path`, `is_active`. Optional primitive provenance fields
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

Validation and limits
---------------------

Unit coverage includes duplicate titles, active-document switches, close/reopen,
invalid-wrapper comparison, stale runtime, process/PID/port reuse, conflicting
registration, concurrent allocation across threads/processes, persistent restart
revalidation, state loss/non-reuse, and out-of-order snapshots. These tests do
not establish native Revit API context, wrapper lifetime across pyRevit engines,
or listener/event reload behavior. No disposable native fixture was supplied.
The foundation does not make the legacy mutation tools explicitly targeted;
that receiver/tool cutover belongs to the routing workstream.
