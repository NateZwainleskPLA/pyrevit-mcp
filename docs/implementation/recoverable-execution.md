Recoverable execution implementation
===================================

This workstream is experimental and has no default startup/tool registration.
No native fixture has been supplied. Mock tests do not establish API-thread,
transaction, engine retention, or listener reload acceptance.

Stage 1 introduces `OperationStore(runtime_id, ...)`, `ExecutionRuntime`,
`register_execution_routes(api, runtime)`, and
`register_execution_tools(mcp, router)`. The routing owner's `TargetRouter.call`
must resolve public handles and attach its full identity envelope. The runtime
uses injected `validate_cached(payload)` and `validate_api(payload, uiapp)`;
only the second may resolve live document objects. An adapter must revalidate
the full identities and a still-valid document immediately before execution.
No alternative identity schema is defined here.

The runner's `execute(payload, context, cancellation_check)` adapter returns
`{state, effects, result, unsafe?, cleanup_errors?}`. Pending transactions and
cleanup errors cannot publish success or rollback. Adapter failure after entry
conservatively records unknown effects and quarantines the host. No scanning
or rollback of another command's transactions is permitted.

Admission and inspection are request-only HTTP handlers at POST
`/operations/submit/` and `/operations/inspect/`. POST inspection uses the same
explicit identity body path as submission. Receipts copy primitive routing
data; no HTTP handler accepts `doc`, `uidoc`, or `uiapp`. Output and payload size,
queue depth, and generation receipt count are bounded. Terminal results expire
after four hours by default, but ID/hash tombstones remain until generation
expiry. When tombstone capacity is reached admission stops rather than silently
reusing an ID. Deduplication covers every submitted payload field and occurs
before queue capacity checks. There is no durable guarantee in stage 1.

Creating the private event requires a valid API context. Opt-in requires both
`experimental=True` and `exclusive=True`; exclusive asserts that every legacy
API-context route is disabled or shares one exclusion mechanism. Disabling
only the legacy execute-code endpoint is insufficient. Arbitrary Python cannot
be guaranteed read-only, so this implementation does not bypass that gate for
scripts claiming to read only. No default adoption is allowed until the listener
lifecycle evidence and native serialization checks pass.

Each callback executes at most one operation. A denied/failed Raise leaves the
operation queued; retrying its original ID/payload can retry the wakeup without
re-admitting it. Diagnostic history is bounded. `stop()` expires the generation
and clears queued payloads without replay; `dispose_in_api_context()` refuses
active/pending callbacks. A pending callback must drain before disposal.

Stage 2 adds POST `/operations/cancel/`, `cancel_revit_operation`, atomic queued
removal and a primitive running cancellation flag. The zero-argument
`cancellation_check()` is passed to the execution-foundations adapter. Running
work remains running until a checkpoint observes the flag; it may still succeed
if it never checkpoints. Effects are independent: cancellation after a prior
commit does not erase that commit. `store.interaction(id, active, description)`
is reserved for an adapter with evidence of an active native interaction; elapsed
time does not imply waiting for a dialog. Nothing forcibly interrupts Python,
closes dialogs or picks, or rolls back another command's transactions.

Stage 3 adds `ReceiptJournal(private_directory, ...)` and optional
`OperationStore(..., journal=journal)`. Receipts contain no executable payload.
Admission is atomically replaced and file-flushed before queue publication;
start is recorded before executor entry; completion follows recorded effects.
POSIX directory metadata is also flushed. IronPython/Windows uses
`System.IO.File.Replace` when `os.replace` is unavailable, without deleting the
previous receipt first. Native Windows/IronPython replacement and controller
crash durability still require testing; this is a local receipt guarantee, not
an exactly-once execution guarantee or protection from storage loss.

Failed admission writes reject execution. Failed start writes prevent executor
entry. Failures after work begins retain in-memory effects/results with
`durability=uncertain`, and the store blocks new/queued work. A duplicate can
still inspect its existing receipt. A successful HTTP response does not remove
the durability uncertainty. Corrupt journals fail closed.

All unfinished receipts loaded on restart become `unknown_after_restart` with
unknown effects, including queued admissions. Nothing is replayed. A store can
load retained receipts for its own generation; archived generation receipts
can be inspected locally with `journal.load(old_runtime_id)`. The current
target endpoint cannot pretend an expired runtime is live. Archive access is
local-only in this delivery; a future explicitly authorized recovery endpoint
would need an independent archive identity contract. Terminal output retention
prunes to hash tombstones; bounded archive capacity rejects admission rather
than deleting uncertain work or permitting ID reuse. Provision a private
extension-owned directory and one journal writer; concurrent processes must
not share its ownership.

Outstanding integration/native checks
-------------------------------------

- Integrate only completed identity, routing and execution-foundation commits.
  Wire their final validation, transaction effects and transport interfaces.
- Demonstrate exclusion of all legacy API-context work against the private lane.
- In an explicitly supplied disposable Revit 2025 fixture, verify API-thread
  execution, target/document invalidation, native transaction effects/cleanup,
  busy inspection, callback lifetime and startup/reload/restart lifecycle.
- No install, reload, shared configuration change or user model mutation is
  authorized by this implementation task.
