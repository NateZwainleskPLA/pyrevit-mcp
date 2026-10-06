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

The runner's `execute(payload, context)` adapter returns
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
