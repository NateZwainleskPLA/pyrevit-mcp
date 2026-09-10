# Revit MCP

This context describes the boundary between MCP protocol behavior and the live Revit environment exposed through the server.

## Language

**Protocol Statelessness**:
Each MCP request is self-describing and does not depend on an MCP session, connection affinity, or server memory retained from earlier requests.
_Avoid_: Stateless Revit, sessionless Revit

**MCP Adapter**:
A disposable process that exposes the MCP interface and routes each self-describing call to the addressed Revit Target. It owns no Revit Runtime State or Revit Operations, so replacing it does not change target or operation identity. It may retry an ambiguously delivered submission only with the exact same Revit Target, Submission Identity, and immutable command input; it never retries by creating new intent or selecting a replacement target.
_Avoid_: MCP session, Revit server

**Revit Runtime State**:
The live Revit application, active document, active view, and model contents against which a request operates. This state exists independently of MCP protocol sessions.
_Avoid_: MCP state, session state

**Revit Host**:
A running Revit process in which this pyRevit extension is loaded, whether or not that process is exposed to the MCP Adapter. The adapter may run while one or more Revit Hosts exist but expose no Revit Targets. Each host's user-controlled exposure can be enabled or disabled independently.
_Avoid_: Revit Target, connected Revit

**Revit Target**:
A short, opaque identifier for one enabled exposure of a Revit Host to the MCP Adapter. It remains stable across disposable MCP-adapter restarts, is never reused, and expires after exposure is disabled and any running operation has drained, or immediately when Revit exits or the pyRevit registration is lost. Re-enabling exposure creates a new Revit Target generation and new Document Targets for the documents that remain open. Callers obtain targets through discovery and carry the selected target explicitly on each request; process IDs, ports, versions, and window titles are descriptive metadata rather than identity. A target admits commands to one bounded FIFO execution queue, validates addressed targets again at execution and after interaction boundaries, and quarantines further execution if it cannot verify that Revit has returned to a safe state.
_Avoid_: Session, selected instance, active server

**Revit Launch Permission**:
The user's authorization for agents to start new Revit processes. It is independent of permission to expose a Revit Host as a Revit Target; allowing launch does not grant access to the launched host.
_Avoid_: Host exposure, automatic exposure

**Execution Queue**:
The Revit Target-owned FIFO of accepted Revit Operations waiting for its single execution lane. It admits 32 waiting operations by default, uses one current-user setting constrained to 1–256 for every target, and never evicts accepted work when that setting is lowered; discovery, health, inspection, and cancellation do not wait in this queue. Deduplication, target validation, capacity reservation, operation creation, and enqueueing form one serialized admission step, so rejected work never creates a hidden operation.
_Avoid_: MCP request queue, per-document queue, global queue

**Document Target**:
An opaque identifier for one independently user-facing, open document incarnation within a Revit Target. Inactive, unsaved, cloud-hosted, family, and read-only documents are eligible; linked, background, and internal documents are not. Activation changes, renames, saves, synchronization, and Save As update metadata without changing the identifier. The identifier expires when that live document closes and is never reused; reopening the same model creates a new Document Target. Model titles and file paths are descriptive metadata rather than identity. Every Document-scoped Request carries both its Revit Target and Document Target explicitly in every supported protocol era, even when only one document is eligible.
_Avoid_: Active document, current model, file path

**Revit-scoped Automation**:
A privileged code execution addressed to one Revit Target that owns its document-selection workflow. It may use the active Revit context and may open, inspect, modify, save, and close multiple documents without assigning Document Targets to documents whose lifetimes remain wholly inside that execution. It completes as one interaction with a final result rather than requiring a client round trip for each document.
_Avoid_: Untargeted execution, document sandbox

**Document-scoped Request**:
A request whose intended subject is one already-open, eligible document. It carries a Document Target so the selected document can be validated and must never fall through to a different or newly active document.
_Avoid_: Active-document request, current-model operation

**Target Snapshot**:
A point-in-time, workstation-wide discovery result that nests each live Revit Target with its nullable active Document Target, eligible Document Targets, and the minimal metadata needed to choose among them. It is returned in one discovery interaction rather than split into list-and-detail calls. The snapshot is advisory; every target is validated again when used.
_Avoid_: Current session, selected-target state, target catalog

**Revit Operation**:
The target-owned execution record created for every command addressed to a Revit Target. It has one opaque, case-sensitive, never-reused `op_<uuidv4>` handle, used unchanged as an MCP Task ID when Tasks represents it; every protocol-neutral operation request carries and validates both this handle and its owning Revit Target. Its complete client-supplied input is fixed at submission, and it never pauses for another MCP round trip, though an explicitly interactive command may await Local User Interaction inside Revit. Its lifecycle is `queued`, `running`, then `completed`, `failed`, or `canceled`; `completed` means that execution produced a valid final tool result, which may itself report a tool-level error, while `failed` means the operation machinery could not produce one. Expected Revit and domain errors are valid error tool results and therefore complete the operation; executor corruption or inability to produce a valid result fails it. Terminal error and cancellation snapshots distinguish model effects as `none`, `committed`, `partial`, or `unknown`. A cancellation request is recorded separately until the operation reaches a safe terminal outcome. One operation executes at a time within each Revit Target, while operations owned by independent Revit Targets may execute concurrently. Accepted work has no generic forced timeout; cancellation is cooperative according to the command's declared capability and command-specific time limits exist only where execution can stop safely. A quick command may complete within its initiating MCP request without exposing the record, but its Submission Identity, command fingerprint, and result remain available for the same four-hour deduplication period as exposed terminal results. When work outlives the inline wait, the same record is exposed either as an MCP Task or through its protocol-neutral handle, according to the current request's capabilities; this handoff is not a timeout or execution failure. An exposed operation's progress and result remain accessible across client disconnections and MCP-adapter restarts while the owning Revit Target remains live. It expires irrecoverably when that Revit Target expires; expiration is loss of availability rather than an operation state, and a new target generation does not resume or adopt it. Discovery, catalog, health, operation inspection, and cancellation are control interactions rather than queued Revit Operations.
_Avoid_: Request, connection, session

**Submission Identity**:
A client-generated, time-bearing `sub_<uuidv7>` identity for one intended target-bound command. An unknown identity is initially fresh for ten minutes with five minutes of allowed future clock skew. Reusing it with the same normalized command envelope recovers the retained Revit Operation; changing the Revit Target, Document Target, command kind, arguments, interaction declaration, or execution options is a conflict and never authorizes another execution. Once the operation is no longer retained, the identity is expired and cannot become a new submission.
_Avoid_: MCP request ID, retry count, operation handle

**Exposure Draining**:
The period after a user disables a Revit Host's exposure while one operation is still running. The Revit Target disappears from discovery and accepts no new work, but remains addressable for operation inspection and cancellation until the running operation finishes and the target expires.
_Avoid_: Immediate exposure expiry, hidden execution

**Execution Quarantine**:
A Revit Target state that admits no further execution because the runner cannot verify that Revit safely exited the previous command. Recovery expires the affected target generation rather than automatically resuming its queue.
_Avoid_: Retry mode, paused operation

**Cancellation Capability**:
A command's declaration that running cancellation is either `queued_only` or `cooperative`. Cooperative commands expose safe checkpoints; arbitrary code may inspect a cancellation request but remains responsible for leaving its transactions safe.
_Avoid_: Forced timeout, thread abort

**Document Access Mode**:
A command's declared need for either database access to its addressed Document Target or UI access through that target as the active `UIDocument`; database access can read or modify the document without implicitly activating it. UI changes require an explicit agent request, with the agent responsible for deciding when to interrupt the user; UI access does not imply restoration of the previously active document.
_Avoid_: Active-document fallback, automatic context

**Transaction Ownership**:
A command's declaration that its Revit transaction behavior is `none`, `atomic`, `checkpointed`, or `manual`. Atomic work either commits or reports no model effect, checkpointed work may report documented partial commits, and manual work such as arbitrary code may have unknown effects after abnormal termination.
_Avoid_: Automatic transaction, implied rollback

**Local User Interaction**:
Input supplied directly by the person at the workstation through the owning Revit Host's UI during an explicitly interactive Revit Operation, such as selecting elements, choosing a point, or answering a pyRevit dialog. The operation remains `running` while it waits; this is distinct from MCP client input and from the Tasks `input_required` state. Dismissing the interaction produces a normal tool result such as `user_canceled` rather than changing the operation's lifecycle state to `canceled`.
_Avoid_: Client input, elicitation, task input

**Forensic Record**:
A bounded, current-user-readable forensic timeline intended for local diagnosis and deliberate export to trusted support. It correlates routing and Revit Operation activity with separately identifiable exact-code artifacts, but is never authoritative input for recovering, resuming, replaying, or reconstructing an operation.
_Avoid_: Diagnostic Journal, MCP journal, Operation store, recovery journal, audit log

**Workstation Trust Boundary**:
Processes running under the current Windows user are trusted for this workstation-local system. Network callers and browser origins outside the local application flow are not trusted.
_Avoid_: Secure localhost, zero-trust workstation

**Extension Footprint**:
The installed product is one pyRevit extension and may include a helper process launched on demand from that extension. It does not install a persistent daemon, Windows service, or external database.
_Avoid_: Single process, workstation service
