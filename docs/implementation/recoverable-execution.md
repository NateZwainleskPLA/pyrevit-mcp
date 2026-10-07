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

Final public signatures:
`submit_revit_execution(target, document, operation_id, code, ...)`,
`get_revit_operation(target, operation_id)`, and
`cancel_revit_operation(target, operation_id)`. Submission is document-scoped.
Inspection/cancellation are runtime-scoped: they require full instance/runtime
identity and operation ownership, but can inspect a historical document's
receipt after it closes. Historical `document_id`/`actual_target` provenance
remains in the receipt. Tools validate a successful operation ID as well as
the router's successful full target/runtime identities.

Creating the private event requires a valid API context. Opt-in requires both
`experimental=True` and `exclusive=True`, a complete request-only exclusion
receipt from routing's `startup.register_routes(legacy_api_enabled=False)`,
including `private_runtime_reload_guard=true`,
and the same process-retained owner/safety guard used by all mutation paths.
The factory refuses missing exclusion endpoints, independent guards, or an
existing private lane (even one stopping or awaiting a callback). Disabling
only the legacy execute-code endpoint is insufficient. Arbitrary Python cannot
be guaranteed read-only, so this implementation does not bypass that gate for
scripts claiming to read only. No default adoption is allowed until the listener
lifecycle evidence and native serialization checks pass.

Each callback executes at most one operation. A denied/failed Raise leaves the
operation queued; retrying its original ID/payload can retry the wakeup without
re-admitting it. Diagnostic history is bounded. `stop()` expires the generation
and clears queued payloads without replay; `dispose_in_api_context()` refuses
active/pending callbacks. A pending callback must drain before disposal.

`build_runtime_in_api_context(registry, uiapp, execute_payload, ...)` is the
composition seam; it installs no routes or startup changes itself. The adapter
uses the identity owner's cached/full-ID methods and execution foundations'
`execute_payload(..., cancellation_check=..., output_limit_chars=...)`. It checks
all open documents before and after execution, so a raw transaction leak in
another document also quarantines the exclusive host. The shared
`get_process_safety()` is retained by routing in CLR AppDomain; the private
owner uses a separate retained slot for the same guard and single runtime
lease. Unsafe state is never reset by a successful result or connector reload.
Cross-engine retention is still a native acceptance gate.

Reload must not re-enable synchronous handlers while a retained private lease
exists. The routing startup owner must check the retained owner slot before
legacy registration; unreadable ownership must fail closed. A stopping or
pending runtime continues owning the host until safe disposal succeeds.
Routing's completed `9558164c` startup guard and `04587804` receipt follow-up
are integrated. The factory primes retained ownership and holds the actual
`startup_owner_guard()` through private construction, and requires the receipt
marker. Tests consume the actual guarded startup receipt, create an inert event,
and verify subsequent synchronous reload fails before identity/route changes.

Stream capture has a trusted configurable retained-character limit during
execution. Receipt truncation preserves structured errors, script location,
partial output and provenance within the receipt budget, marking truncation.
Effects and identity remain outside truncated diagnostics. Revit's native
OperationCanceledException maps to `canceled`/`user_canceled`; effects still
follow the transaction evidence, and no dialog or pick is forcibly dismissed.

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
`OperationStore(..., journal=journal)`. The journal does not reconstruct queued
execution payloads for replay. Terminal diagnostics can include echoed script
code from the execution service, so receipt storage must remain private.
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

The Origin publication branch `pr/recoverable-operations` is based on completed
`pr/explicit-target-routing` at `e1fb74b876fafeecff11cae4ac8b6d9c1af29b25`
([routing PR #7](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/7)). It
inherits that branch's canonical transport, status, identity and execution
foundations, including launch/file tools and startup ownership guards. Merge
the routing stack before this workstream. The shared proposal baseline is not
part of the publication branch.

Only the five owned build commits were replayed: `41a5338`
registry/runner/inspection, `d8e82e6` cancellation, `0f6e34e` journaling,
`d70606e` adapters/ownership, and `aa6ef1c` guarded construction. The following
table records historical prerequisite equivalents in the preserved original
build checkout; these patches were not separately replayed for publication:

| Owner commit | Local equivalent |
| --- | --- |
| Transport `6ef7b249`, `2d1d8fa9` | `a9d08ec`, `34578fe` |
| Status `0f1b703` | `ce5e528` |
| Identity `8101dda0`, `5a97fb56` | `f7e71c4`, `1f8e33f` |
| Execution `ae58f06d`, `5831b986`, `2d161784`, `7d63c3b7` | `9645189`, `e5276e7`, `5d97be2`, `d06feea` |
| Routing policy `7a4aaf6`, router `40838db` | `6fe9a01`, `3e973ba` (policy introduced here during dependency-order resolution) |
| Routing cutover `3a26b329`, recovery `f6781d78`, confirmation `25db62f9` | `1d6689b`, `aa778cc`, `c342504` |
| Routing startup guard `9558164c`, marker `04587804` | `e0ef77a`, `216e6e1` |

Verification uses the repository's unit suite only, CPython compile checks,
and Python 2.7 AST parsing of the three native operation modules. The actual
ExternalEvent creation helper follows Autodesk's
[External Events API contract](https://help.autodesk.com/cloudhelp/2025/CHS/Revit-API/files/Revit_API_Developers_Guide/Advanced_Topics/Revit_API_Revit_API_Developers_Guide_Advanced_Topics_External_Events_html.html).
API behavior and IronPython/CLR engine lifetime are not proven by syntax checks.

- Completed identity, routing, transport and execution-foundation commits are
  integrated; tests exercise their real modules with inert Revit doubles.
- Adoption of execution-foundation review fixes is pending the owner's completed
  local contract and commit. Opus PR #3 report `f0bbb53`
  (`docs/reviews/opus-pr-3.md` in `review-opus-pr-3`) reports F1 closed helper
  documents falsely marking settled owned work unsafe/unknown, F2 Python wrapper
  identity misparenting scopes across group rollback, F3 UI facade gating and
  supplied-document binding errors, and F4/F5 stream compatibility failures.
  Operations must reconcile F1 before adopting those fixes: a successfully
  closed non-selected helper document with all owned scopes settled must not
  falsely quarantine the process. Selected-document loss, pending/unresolved
  scopes and unknown raw effects still require conservative handling. Integration
  must also preserve wrapper-equivalent parenting and rollback receipts (F2),
  exact supplied-document/UI binding in the adapter (F3), and the same retained
  process safety instance across every mutation path. Do not reset safety to
  accommodate these fixes. The report's 147 unit and four reproduction tests
  use doubles/source and provide no native workflow proof. No unfinished fix
  branch is imported or runtime behavior changed by this dependency note.
- Startup/private-lease composition and the exclusion receipt are integrated;
  native cross-engine retained-object behavior and accepted-worker draining
  remain unproven. There is no automatic/default private-mode registration.
- Dialog-policy integration remains pending. The shared Opus PR #4 review
  (`cc6a1a9`, `docs/reviews/opus-pr-4.md` on `review-opus-pr-4`) identifies that
  a policy fixed per subscription requires detach/reattach for each operation
  and resets its receipt sequence; sequence ranges alone cannot uniquely
  correlate receipts across operations. Before adding consumer hooks, obtain
  the dialog owner's completed local contract and commit for retained-delegate
  policy swap with finally restoration, monotonic receipt sequence and policy
  generation, or an explicit statement that this gap remains unresolved.
  Future integration still requires explicit per-operation opt-in after full
  target/document validation, a serialized owner scope, receipt correlation
  and a policy-sensitive admission hash. This dependency note enables no
  native dialog registration, supported catalog entries or default integration.
- Demonstrate request-only legacy exclusion, accepted-worker draining and the
  one-owner lease in a fresh disposable native initialization. Do not switch an
  already-serving host by calling register_routes again: queued legacy workers
  and old listeners require lifecycle evidence before a mode cutover is safe.
- In an explicitly supplied disposable Revit 2025 fixture, verify API-thread
  execution, target/document invalidation, native transaction effects/cleanup,
  busy inspection, callback lifetime and startup/reload/restart lifecycle.
- No install, reload, shared configuration change or user model mutation is
  authorized by this implementation task.
