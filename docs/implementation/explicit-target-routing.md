Explicit synchronous routing
============================

Every public tool directed to an existing process requires `target`. Model work
also requires `document`. `get_revit_status` and `open_document` are process-only;
installation listing, discovery and launch are exceptions. There is no selected
port, default directed endpoint, fallback or execution retry. `REVIT_HOST` and
port scanning configuration belong to discovery. `REVIT_TARGET_STATE` optionally
chooses the client's persistent SQLite directory; otherwise each server process
gets a fresh handle namespace.

Client interface
----------------

`TargetRouter(directory, handshake, request=request_revit)` uses the identity
owner's directory. `await call(method, endpoint, *, target, document=None,
data=None, params=None, timeout=30.0, allow_ui_change=False)` returns the transport
owner's unchanged `RevitTransportResult`. It revalidates metadata and local
process/listener evidence on every call, serializes verification per handle,
then captures that call's exact endpoint and full IDs. Transport occurs outside
the verification lock, so different targets remain independent. POST bodies and
GET query parameters carry full `instance_id`, `runtime_id`, and scoped
`document_id`. Callers cannot override those reserved fields.

Successful responses must confirm the addressed identities in `actual_target`
or top-level full identity fields. A missing/mismatched confirmation preserves
the original response in a failed transport result. Delivery is uncertain for a
potentially mutating POST, never replayed; known read-only POST queries do not
become uncertain mutations. Presentation uses `compatibility_response` and
`format_response`. Image results include the image plus actual identity and the
requested aliases. Local handle rejection has no fabricated HTTP status.

Direct `resolve` converts HTTP, OS and JSON/value handshake failures to chained
`IdentityError("target_unreachable", ...)`, leaving existing typed identity
errors unchanged. `call` returns the underlying failure as structured
`target_revalidation_failed` evidence, retaining any handshake HTTP body/status
and explicitly stating that execution was not sent. MCP tools and the file CLI
render this failure without a raw exception/traceback. Execution transport is
never awaited after failed verification.

The shared policy includes document-scoped POST `/operations/submit/` and
runtime-scoped `/operations/inspect/` and `/operations/cancel/`. Inspection and
cancellation require the original runtime and operation ID, not a live document;
closing the execution document cannot strand a retained receipt. Historical
document identity belongs to that receipt, rather than new live resolution.
All operation endpoints require POST with a nonempty body `operation_id` before
handshake/transport; GET or a missing ID fails with `missing_operation`.
Every successful operation response must confirm that original ID.
This workstream does not register those handlers or an asynchronous runner.

Receiver interface
------------------

`TargetedAPI(api, registry_getter=get_registry, admission_guard=None, safety=None)`
wraps every synchronous handler during registration. Its real `uiapp` argument
forces pyRevit API-context dispatch. It parses the full identities, checks the
registry, freshly resolves the requested document from
`uiapp.Application.Documents`, and replaces the active document supplied by Routes.
The receiver adds `actual_target` to success and failure responses. Missing,
closed, crossed and stale identities do not reach the handler. Database work
uses inactive documents without activation.

Current-view and color-view operations require the specified document to be
active. Opening/closing documents requires `allow_ui_change=true`. Code gets
`uidoc` only with permission and an already active specified document; the
execution foundation's `ScopedRevit` also binds `revit.doc` and `revit.uidoc`.
No route activates implicitly. Direct `Document.Close(save)` closes inactive
documents. Active closure is rejected because a posted Close command cannot
retain the specified document while waiting; no posted command is described as
verified completion.

`get_process_safety()` retains the execution owner's `ExecutionSafety` in the
CLR AppDomain. All synchronous mutation paths share it. Identity validation
precedes its guard. Mutations reject an already modifiable selected document;
observed unsafe cleanup/postconditions latch the guard, and later success cannot
clear it. Queries remain available. This neither scans raw transactions nor
repairs another command's scopes. Untracked other-document/file effects remain
outside this guarantee. Operations must inject the very same retained guard.
The guard's primitive snapshot selects a local `mutation_blocked` rejection,
avoiding exception-class identity across engine reloads. Rejection before
admission returns HTTP 409 and `effects=none` without resetting the guard.

`admission_guard(endpoint, payload, resolved_doc)` runs in API context before the
handler. It cannot provide HTTP-worker exclusion. `DisabledAPI` instead registers
request-only 503 rejection handlers, with no API arguments.
`startup.register_routes(legacy_api_enabled=False)` replaces all legacy context
routes and `/metadata/refresh/` with these rejections, retaining only cached
metadata. It does not register or enable a private execution lane. The default
startup composition remains synchronous. Experimental adoption requires the
operations owner's retained exclusive lease and native acceptance separately.

Before initializing identity, startup reads the operations-owned CLR AppDomain
slot `revit_mcp.execution.owner.v1`. Any retained `runtime` lease rejects startup,
including stopping/pending runtimes; routing never clears that lease or guesses
whether disposal completed. Corrupt/unreadable owner state, a mismatched retained
safety guard, or a busy/unreadable owner lock also rejects startup. For an existing
idle owner, startup holds its lock through registration. An absent owner or a
safely released lease permits default synchronous startup. This check imports no
operations module, allocates no competing owner, and preserves blocked safety
state. Native retention across engines remains unproven without fixture testing.
The successful disabled-mode receipt includes `private_runtime_reload_guard=true`
only after this guard and the complete legacy-route exclusion checks pass. This
is composition evidence for the private factory, not native lifecycle acceptance.
The primitive exclusion receipt is a trusted, honest-caller composition
contract, not an unforgeable proof or security boundary. A caller can fabricate
the fields; production composition must supply the actual guarded startup
receipt. The concrete startup guard and retained factory lease remain the
mechanisms that exclude overlapping execution. No second receipt schema or
authentication mechanism is introduced here.

Validation and pending coverage
-------------------------------

Automated checks exercise real directory/registry/receiver composition, two
interleaved local/remote targets, port reuse after handshake, crossed handles,
missing targets, queued active-document switches, document closure, all mutation
guards, retained unsafe state, HTTP-only exclusion and public required arguments.
These are controlled callbacks, not native API-thread or engine-lifetime proof.
No disposable Revit fixture was supplied. Native callback injection, inactive
document execution/export/closure, real UI permission behavior, AppDomain guard
retention across reload, listener lifecycle and launch handshake remain pending.
Historical integration tests are skipped without
`REVIT_MCP_DISPOSABLE_FIXTURE`; their old lifecycle harness still needs targeted
fixture adaptation before native use. No deployment or open-model mutation was
performed.

Launch verification
-------------------

Launch retains `Popen`, obtains the child's Windows process start timestamp, and
waits for discovery metadata with that exact PID/lifetime/version. It accepts
only a local loopback endpoint, valid UUID metadata, initialized API-context
document snapshots and a final successful revalidation. Unrelated processes,
remote hosts, reused PIDs, generic HTTP errors and superseded generations never
satisfy readiness. Process exit stops the wait. Verified launch returns its own
`target`, `actual_target` and document handles; otherwise it returns
`launched_unverified` with process evidence and no invented handle. A requested
file is reported separately from cached `file_open_verified` evidence. Native
dialogs and actual execution availability still need disposable-host checks.
Local launch verification does not support a child advertised only on a LAN or
other non-loopback endpoint, including `REVIT_MCP_ADVERTISED_HOST` overrides.
It waits only to the configured deadline and returns `launched_unverified` with
the loopback limitation stated in the tool description and result. Matching a
remote PID/start/version is not sufficient evidence of local child ownership.

Local file execution
--------------------

`execute_revit_script_file(target, document, file_path, ...)` reads the script on
the MCP client machine and uses the same targeted `/execute_code/` route as inline
execution. It accepts UTF-8 with an optional BOM, normalizes CRLF, and submits the
code with its basename and SHA-256 of the submitted UTF-8 contents. It never sends
a server-side file path to read. Errors retain basename/line diagnostics and
partial output from the normal executor. Remote targets still use client-local
files. Missing files or invalid UTF-8 fail before transport.

The equivalent CLI is `python -m scripts.execute_revit_file --file edit.py
--target <handle> --document <handle> --state <existing-directory.sqlite>`, with
optional `--transaction-mode managed` and `--allow-ui-change`. It needs the same
persistent directory used by the MCP server (or `REVIT_TARGET_STATE`); it cannot
reuse another process's in-memory namespace. The file adapter performs one
synchronous call and never replays an uncertain mutation.

Application execution uses the separate `/execute_application_code/` route and
`execute_revit_application_code` / `execute_revit_application_script_file` tools.
It requires an explicit target, accepts no document selector, starts with
`doc=None`, and rejects managed transaction mode. The CLI selects it with
`--application` in place of `--document`. See the
[application execution contract](application-scoped-execution.md) for bound
Application/UIApplication access, opening and continuing, registry descriptors,
document-state checks, shared process safety and native proof requirements.
