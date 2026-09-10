# Define concurrency, retry, and stale-target safety

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: 03, 04, 06

## Question

What serialization, queueing, idempotency, retry, timeout, stale-target, document-activation, and failure rules prevent concurrent or repeated stateless requests from racing, mutating the wrong model, duplicating work, or hiding an operation still running inside Revit?

Explicitly decide which work may run in parallel across Revit Targets and Document Targets, and where Revit API or UI-thread constraints require serialization, without assuming that the single-target execution model should limit independent Revit processes.

## Answer

### Execution lane and queue

- Each Revit Target owns exactly one FIFO Execution Queue and runs at most one Revit Operation at a time. No operations interleave within one Revit process, even when they address different documents or claim to be read-only. Independent Revit Targets may execute concurrently; there is no workstation-wide execution lock.
- The queue permits one running operation plus 32 waiting operations by default. One current-user setting, constrained to 1–256, applies to every target. Lowering it below the current depth never evicts accepted work; new admissions receive structured `queue_full` errors until the depth falls below the limit.
- FIFO order spans clients, tools, and Document Targets, with no priority classes initially. Discovery, health, operation inspection, and cancellation are control interactions and bypass the execution queue.
- Submission does not execute the command inline in the route handler. The target atomically performs deduplication lookup, target validation, capacity reservation, operation creation, and enqueueing as one serialized admission step. A stale target, conflicting or expired identity, or full queue fails before an operation exists. A successful admission means an authoritative operation exists before acknowledgement.

### Submission identity and retry

- Every target-bound command requires a caller-generated, opaque, case-sensitive `sub_<uuidv7>` Submission Identity. An unknown identity is eligible for initial admission when its embedded time is no more than ten minutes old and no more than five minutes in the future. A known identity remains recoverable while its operation or deduplication record is retained, regardless of age.
- The target fingerprints the normalized parsed command envelope rather than raw JSON bytes. The fingerprint covers the Revit Target, optional Document Target, command kind, arguments, interaction declaration, Document Access Mode, Cancellation Capability, Transaction Ownership, and every other execution-affecting option. JSON whitespace and object-key order do not matter; changing an execution-affecting value produces `submission_conflict` and never creates another operation.
- An exact duplicate returns the original operation snapshot or inline result. A minimal identity record, fingerprint, and final result remains available for four hours after terminal completion even when the original command completed inside the five-second inline budget and never exposed its operation handle. Once forgotten, the time-bearing identity is `submission_expired`, not new intent.
- The MCP Adapter may make at most two short-backoff retries when delivery to the exact Target Runtime is ambiguous, using the exact same Revit Target, Submission Identity, and immutable envelope. This covers both “not delivered” and “accepted but acknowledgement lost” without duplicate execution. It never retries a complete error response, queue rejection, stale target, tool error, or failed operation; never creates a new identity; and never redirects the retry to another target generation. After an adapter crash, the client may recover by resubmitting the same identity.

### Validation, document activation, and staleness

- Validate Revit and Document Target identity and parentage during admission and again immediately before execution. A Document Target that goes stale while queued completes its already-admitted operation with a structured error tool result and `effects: none`; it is never replaced by the active document, a matching path or title, or a newly discovered handle.
- Every command declares a Document Access Mode. A database-mode command receives the addressed `Document` without activating an inactive document. A UI-mode command validates the addressed active `UIDocument`; if activation is needed, it requires the agent's explicit `allow_ui_change=true`, reports that visible side effect, and does not restore the previously active document afterward. Without that flag, required activation produces `ui_change_required` before changing the UI. [Define the explicit-target tool catalog and per-command declarations](15-define-tool-catalog.md) owns the per-tool declarations and explicit interaction flags.
- Document activation, post-activation validation, and command entry occur in one scheduler-controlled Revit UI-thread turn. Local User Interaction is the intentional yield; the target revalidates all intended targets after it and before any later mutation. Manual UI changes between operations are expected and handled by execution-time validation.
- A command that intentionally closes its own Document Target may complete successfully. Later queued work for that document fails its execution-time validation. If the owning Revit Target expires, its operations become unavailable rather than being rewritten as terminal; no work moves to a replacement generation.

### Cancellation, transactions, and effects

- Accepted operations have no generic forced execution timeout. Client disconnection and the five-second inline handoff do not cancel work. Command-specific time limits are permitted only when the underlying work can stop at a safe checkpoint; the system never aborts Revit's UI thread or kills Revit to manufacture cancellation.
- Every command declares Cancellation Capability as `queued_only` or `cooperative`. Queued cancellation remains immediate. Cooperative commands define safe checkpoints; arbitrary code receives a `cancellation_requested()` helper but must poll it and leave any manual transactions safe. A running operation may still complete or fail before a cancellation request takes effect.
- Every command declares Transaction Ownership as `none`, `atomic`, `checkpointed`, or `manual`. Built-in mutations prefer `atomic`; cancellation or an expected error before commit rolls back and reports `effects: none`, while a commit that wins the race completes normally. A `checkpointed` command may leave explicitly documented committed units and reports `effects: partial` when stopped. Arbitrary code remains `manual` and reports `effects: unknown` after abnormal termination unless it can prove a stronger result.
- Terminal error and cancellation snapshots report model-effect certainty as `none`, `committed`, `partial`, or `unknown`. Expected Revit or domain errors are valid error tool results and therefore leave the operation `completed`; executor corruption or inability to produce a valid result leaves it `failed`. A failed result never authorizes automatic resubmission, even when effects are unknown.

### Failure containment and exposure shutdown

- Before starting the next queued operation, the runner must verify that the prior command returned Revit to a safe execution state, including closure of every transaction it owns. If it cannot verify safety—for example after badly behaved arbitrary code or an unaccounted modal or transaction state—it fails the current operation as appropriate and places the Revit Target in Execution Quarantine. Control interactions remain available, but no queued work starts and there is no automatic resume.
- A locally confirmed **Reset target execution** action cancels queued work, expires the quarantined target generation, and mints a new generation only after health checks establish a safe Revit state. If they cannot, the status surface directs the user to restart Revit. Old operations and Submission Identities are never adopted by the new generation.
- Disabling exposure immediately removes the Revit Target from discovery, rejects new submissions, cancels queued work, and requests cooperative cancellation of the running operation. The target remains addressable for inspection and cancellation during Exposure Draining, then expires when the active operation reaches a terminal state. Revit exit or process failure still causes immediate, unavoidable target and operation expiry.
