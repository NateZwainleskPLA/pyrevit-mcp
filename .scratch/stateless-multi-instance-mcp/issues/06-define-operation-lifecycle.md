# Define the Revit Operation lifecycle and task fallback

Type: grilling
Status: resolved
Blocked by: 01, 03, 04

## Question

Which calls become durable Revit Operations, what states and retention guarantees do they have, how do polling, input, results, cancellation, restart recovery, and cleanup behave, and what is the safe fallback when a new- or legacy-protocol client does not advertise the Tasks extension?

## Answer

### Operation boundary and identity

- Every command addressed to a Revit Target creates a target-owned Revit Operation before execution begins. This gives quick and long-running work one execution, failure, and diagnostic model. Workstation discovery, catalog access, and bootstrap actions are ordinary requests because no Revit Target owns their work.
- Each operation has one opaque, case-sensitive, never-reused `op_<uuidv4>` handle. The same value becomes the MCP `taskId` if a later Tasks projection represents it. Protocol-neutral operation calls always carry both `revit_target` and `operation`; the target validates their ownership relationship on every call.
- A command that finishes inside the initiating request need not expose its operation record. An operation that outlives that request exposes its handle and remains accessible while retained.

### Submission and inline handoff

- The Revit Target creates the authoritative operation record before execution and before acknowledging submission.
- Every target-bound tool waits for an ordinary inline result for one server-controlled five-second budget. Clients neither extend this budget nor force asynchronous execution.
- Completion inside the budget returns the normal tool result. Work still active at the boundary continues unchanged and returns either an MCP Task, when a future implementation advertises and the current request declares the pinned Tasks extension, or an ordinary protocol-neutral operation reference otherwise. This is a normal handoff, never a timeout or execution failure.
- The first migration release does not advertise Tasks. The protocol-neutral fallback is required and conformance-tested first. Tasks may be added later only against a pinned extension revision and after its projection passes the protocol-conformance harness; Python SDK support or an explicitly maintained extension implementation must exist first.

### Lifecycle and results

- The lifecycle is `queued`, `running`, then one of `completed`, `failed`, or `canceled`. A queued operation may transition directly to `canceled`.
- `completed` means the machinery produced a valid final tool result. That result may carry `isError: true` for an expected tool-level problem. `failed` means the operation machinery could not produce a valid tool result. This maps without semantic drift to Tasks `completed` and `failed`.
- Expiration is loss of record availability, not a lifecycle state. Revit Target expiry likewise makes its operations unavailable rather than rewriting their terminal states.
- The Target Runtime operation seam has three methods: explicitly targeted `submit(command)`, `get(operation)`, and `cancel(operation)`. All return one Operation Snapshot shape. There is no separate result-fetch, client-input, list, renewal, acknowledgement, or deletion method.
- An Operation Snapshot contains its operation and target identity, optional Document Target, command kind, lifecycle state, creation/start/completion timestamps as applicable, `cancellation_requested`, optional progress, the terminal result or structured failure when applicable, `expires_at` when terminal, and a suggested polling interval while active. Progress always has a human-readable message; a percentage appears only when the work is genuinely measurable.
- `get_revit_operation(revit_target, operation)` is idempotent and returns that complete snapshot. Terminal results are repeatable and non-destructive. Polling is the baseline, beginning at the server-suggested one-second interval; notifications may later reduce polling but never replace it.
- A later Tasks adapter projects `queued` and `running` to `working`, `completed` to `completed`, `failed` to `failed`, and `canceled` to `cancelled`. It projects the same snapshot and result rather than owning another lifecycle.

### Input and Local User Interaction

- All MCP-client-supplied command input is complete and immutable at submission. An admitted operation never pauses for another MCP round trip or enters a Tasks `input_required` state. MCP clarification or elicitation happens before operation admission; information discovered missing afterward produces a final tool-level result and a newly submitted operation if the client chooses to continue.
- This does not prohibit Local User Interaction. A command that explicitly declares itself interactive may ask the person at the owning Revit Host to select elements, choose a point, or answer a Revit or pyRevit dialog. It remains `running`, optionally reporting a `waiting_for_user` progress phase, and occupies only that Revit Target's execution path.
- Dismissing Local User Interaction produces a normal tool result such as `user_canceled`; it does not make the operation lifecycle `canceled`. Commands declared noninteractive must not depend on unexpected dialogs as an input channel.

### Cancellation

- `cancel(revit_target, operation)` is idempotent. It immediately removes queued work and transitions it to `canceled`.
- For running work it records `cancellation_requested: true` and requests cooperative cancellation at a safe point. The response confirms that the request was recorded, not that execution has stopped; clients poll for the terminal outcome.
- Races are explicit: work may still become `completed` or `failed` before cancellation takes effect. Calling cancel on terminal work returns its unchanged terminal snapshot.
- Client disconnection and expiration of the five-second inline wait never imply cancellation. The system never aborts a Revit thread, kills Revit, or claims transaction rollback merely to force the `canceled` state. Safe cancellation points and transaction consequences belong to the execution-safety decision.

### Retention, restart, and cleanup

- Queued and running operations have no retention deadline. Exposed terminal operations retain their snapshot and result for four hours after reaching a terminal state. The absolute `expires_at` is fixed, polling does not refresh it, and clients cannot renew it.
- An operation that returned inline without exposing its handle retains a minimal Submission Identity record, command fingerprint, and final result for four hours so an ambiguous retry returns the original outcome. Automatic expiry removes that deduplication record, the terminal record, and any target-owned temporary result files; the Forensic Record may retain forensic evidence under its separate policy but can never reconstruct the result.
- The owning Revit Target's lifetime is the hard ceiling regardless of `expires_at`. Revit exit or extension-registration loss expires the target and all its operations immediately. Exposure disablement removes it from discovery and new admission, cancels queued work, requests cooperative cancellation of running work, and retains inspection and cancellation until that work reaches a terminal state; the target then expires. A new target generation never resumes, adopts, or replays operations.
- A disposable MCP Adapter restart does not alter an accepted operation. A client that already has the handle rediscovers the Revit Target if needed and polls the same target-owned record. No database, temporary result file, or Forensic Record reconstructs operation state.
- An adapter failure after target acceptance but before delivery of the handle creates an uncertain-admission race. Idempotent submission and recovery from that race, queue limits, execution timeouts, per-target versus cross-target parallelism, and safe Revit scheduling are intentionally delegated to **Define concurrency, retry, and stale-target safety**.
