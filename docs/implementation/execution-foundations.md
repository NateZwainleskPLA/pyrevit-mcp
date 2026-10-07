Execution foundations
====================

`execute_payload(data, doc, uidoc)` in `revit_mcp/code_execution.py` returns
`(result, http_status)` for synchronous API-context execution. Routing owns
required target/document handles and full receiver identity validation. This
foundation does not claim the legacy route already meets the targeting contract.

`execute_script(code, namespace, script_name)` in `execution_output.py` restores
stdout and stderr in an outer finally, including SystemExit/KeyboardInterrupt.
Output remains separate from stderr. Failures preserve `partial_output`,
`error_type`, `traceback`, and `script_location` (filename/line/column). A supplied
`script_name` contributes only its basename; it never reads a host file. Empty
output remains an empty string. Capture read/close failures appear separately
in `cleanup_errors` and do not mask the script exception. Execution must be
serialized because Python streams belong to the engine.

Upstream #12 at `43cd36e6e3dceb925bc7868e4277b07b5742f1a3` was inspected.
Its finally references uninitialized output variables for parsing/no-code paths;
this implementation initializes resources before entering capture and closes
only created buffers. Command execution/log scraping is outside this change.

Host-independent tests cover diagnostics and stream/resource errors. Native
IronPython stdout/stderr restoration still needs an explicitly supplied
disposable Revit fixture. No live model or installed extension was changed.

Reusable namespace helpers
--------------------------

`RevitHelpers(DB, System)` in `execution_helpers.py` binds `eid`, `id_of`,
`name_of`, `to_json`, and a local `json` adapter. `namespace()` supplies the
script bindings. Element-ID construction explicitly selects Int64 for numeric
values, while category/parameter enums retain their overload. ID extraction
supports Value and the older IntegerValue property. Name lookup handles the
hidden Element.Name descriptor and preserves Unicode without stripping text.

JSON handles supported .NET numeric/boolean types, ElementId and XYZ. Unknown
objects raise TypeError rather than silently turning into strings. A custom
`default` callback is honored. The process-wide json module is unchanged; a
script's `import json` shadows the adapter, so `to_json` is the explicit helper.

The helper approach came from upstream #63 at
`9a0ebe828d71b8bc259ee58f4419a0d0c58f311a`. Dialog suppression and unrelated
startup changes were not imported. Revit 2025 overload/descriptor behavior and
actual CLR JSON values still require the disposable native fixture.

Owned scopes and execution modes
--------------------------------

`execute_payload(data, doc, uidoc, cancellation_check=None, revit_context=None)`
accepts `transaction_mode` (`script` default or `managed`), `script_name`, and
`allow_ui_change` (false default). It returns `(result, http_status)`; validation
errors are 400, script/cancellation/cleanup errors 500. Operation owners map
`ExecutionCanceled` to their own canceled state. No operation registry is defined
here. The injected `revit.doc` follows the supplied document, and both `uidoc`
and `revit.uidoc` are withheld unless UI changes are enabled. Routing must pass
no UIDocument for inactive database work and validate UI changes against the
specified active document. A custom `revit_context` may supply a stricter facade.
`revit.docs` contains only the supplied document. `active_view` reads and writes
the supplied UIDocument, and `active_ui_view` matches that document's open UI
views. Both getters return None when UI access is withheld; the active_view
setter raises with an opt-in hint. All other public facade assignments are
rejected rather than silently shadowing a host property. `revit.Transaction`
and `revit.TransactionGroup` default to the supplied document and preserve an
explicit document and additional positional/keyword arguments. These pyRevit
helpers remain untracked; use execution helpers for owned cleanup. Other delegated
pyRevit helpers can use implicit host context: scripts must pass the document
explicitly. Arbitrary host APIs remain available; this is no sandbox.

`ExecutionContext(DB, doc, transaction_mode='script', cancellation_check=None)`
in `execution_context.py` provides:

- `transaction(document, name)`: a connector-owned native Transaction. Success
  commits; exceptions roll back. Native transactions cannot nest.
- `rollback_scope(document, name)`: an owned TransactionGroup, always rolled back
  on exit. It can contain owned transactions and nested rollback groups and
  undoes their committed changes. It cannot start inside a modifiable document.
- `checkpoint()`: calls a zero-argument boolean cancellation hook and raises
  `ExecutionCanceled` when requested. The context also checks before start and
  after script execution, before managed commit. There is no forced interruption.
- `check(name, expected, actual)`: records a named check and raises AssertionError
  on mismatch. Primitive check values are suitable for JSON receipts.
- `run(compiled, namespace)`: callback for `execute_script(..., runner=...)`.
- `close()`: idempotently unwinds owned scopes in reverse order and checks the
  selected and helper-owned documents. It never searches for raw transactions.
- `summary()`: primitive `effects`, `owned_effects`, `unsafe`,
  `transaction_receipts`, `checks`, and `cleanup_errors`.

Managed mode opens one owned transaction on the supplied document. Additional
helper scopes are rejected. Compile/capture failure or cancellation before Start
has no effects. An exception after Start unwinds even when __enter__ raised.
Leaked helper scopes are rolled back and fail execution rather than being silently
committed. Commit returning RolledBack is a failed edit with confirmed rollback.
Returned and observed statuses must agree; Pending is never successful commit or
rollback. Pending/unknown scopes are not disposed and remain strongly referenced
by `retained_contexts()` for explicit recovery. Cleanup errors preserve the primary
script exception, leave effects unverified, and set unsafe when necessary.

`owned_effects` describes only tracked scopes. Group rollback updates contained
scope effects. A surviving earlier owned commit remains committed after a later
exception. Script-mode `effects` remains unknown if there is no surviving owned
commit: a successful owned rollback cannot prove the script made no prior raw
commits. Managed effects describe its selected-document transaction. Filesystem,
saved documents, posted commands and untracked other-document changes require
separate evidence/receipts from the execution owner.

Safety integration
-------------------

`ExecutionSafety` in `execution_safety.py` is an optional guard primitive:
`observe(result, document_id=None, operation_id=None)` latches `unsafe`,
`require_safe()` rejects mutations with MutationBlockedError, and `snapshot()`
copies diagnostics. Success never resets it. Share one process-retained instance
across synchronous routing and queued execution, including runtime reloads.
Caller identity validation precedes guard checks, and guards run at admission
and again in API context immediately before mutation. Routing must guard every
place/color/clear/open/close/save/sync/execute path before claiming host quarantine;
query paths remain inspectable. This foundation registers no global quarantine.

Execution refuses to enter an already modifiable document. A closed selected
document, invalid document with unresolved owned scopes, or observed modifiable
postcondition is unsafe. A known closed non-selected helper document with all
owned scopes settled adds an informational `document_notes` entry with stage
`document_closed`, preserving commit/rollback receipts without cleanup errors.
Parenting and document deduplication compare wrapper identity first and then
guarded native Equals calls, so equivalent wrappers share a rollback-group tree.
Transaction
cleanup failures and unresolved children are unsafe. Capture-only errors do not
make the model unsafe. Inspect other affected documents in valid API context,
where known, and preserve document/operation identity in safety diagnostics. Raw
transaction groups and effects on untracked documents cannot be reliably found
through these checks. Recovery is targeted and explicit; never scan GC/globals or
dispose somebody else's transaction.

Native acceptance remains pending
---------------------------------

Unit tests simulate native statuses and geometry values, including exceptions
after Start, rollback groups, reverse cleanup, pending/mismatched statuses,
cleanup failures, untracked leaks, checkpoints, Unicode and context binding.
They establish no native Revit threading or transaction behavior. With an
explicitly supplied disposable Revit 2025 fixture, check managed geometry commit
and exception rollback by readback, rollback-group flex trials, nested cleanup
failure, native failure-processing Pending, cancellation at checkpoints,
stdout/stderr restoration, inactive-document binding, and unsafe-result blocking
across all mutation paths. No native test or extension reload has been performed.
Also verify `element.Document is doc` versus `element.Document.Equals(doc)` for
separately obtained wrappers, rollback-group geometry/receipts through those
wrappers, and a committed secondary family document closed after loading. Native
Equals and IsValidObject/Close behavior remain unverified by the doubles.

Bounded stream capture
----------------------

`execute_script(..., output_limit_chars=1000000)` and
`execute_payload(..., output_limit_chars=1000000)` share one retained-character
budget across stdout and stderr. The execution owner supplies this trusted
configuration keyword; scripts cannot increase it through their JSON payload.
The limit is a nonnegative integer, with zero retaining no output. Standard
stream writes keep their prefix until the shared budget is exhausted and then
drop excess text while code continues. Truncation never triggers rollback or
changes execution effects. `output_truncated`, `stderr_truncated`, and
`output_capture` (`limit_chars`, `retained_chars`, `stdout_dropped_chars`,
`stderr_dropped_chars`) describe the loss. Partial output uses the same capped
prefix. Whichever stream writes first consumes the shared budget.

Both the buffer and fallback write journal retain bounded text; empty writes
and discarded overflow do not append journal entries. Concurrent writes reserve
the shared budget under a lock. This bounds capture memory during execution,
including scripts that repeatedly print beyond the limit; it does not bound
objects allocated by arbitrary script code, exception traces, or other receipts.
The operation owner separately bounds serialized result/journal receipts. Native
IronPython Unicode capture and stream-thread behavior still need the fixture.
