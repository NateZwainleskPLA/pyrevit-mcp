# Define Revit Target and Document Target identity semantics

Type: grilling
Status: resolved
Blocked by: none

## Question

What are the discovery, identity, lifetime, omission, validation, and stale-handle rules for Revit Targets and Document Targets so every model-scoped request is self-describing and can never silently fall through to the wrong Revit process or document?

## Answer

### Identity and eligibility

- Revit Targets and Document Targets are opaque, case-sensitive, non-reusable handles with type-prefixed UUIDv4 forms: `rvt_<uuid>` and `doc_<uuid>`. The random 128-bit value carries no PID, port, version, path, title, or other routing information and clients must not parse it.
- A Revit Target identifies one enabled exposure generation of a Revit Host. Opening, closing, saving, or activating documents does not change it.
- A Document Target identifies one live open-document incarnation beneath exactly one Revit Target. Activation changes, renames, saves, synchronization, and Save As update metadata without changing the handle. Closing ends the incarnation; reopening the same model, even from the same path, creates a new handle.
- Eligible Document Targets are independently user-facing open project and family documents, including inactive, unsaved, cloud-hosted, read-only, and workshared documents. Linked models, imported files, internal/system documents, and background documents whose lifetimes remain wholly inside an automation are not eligible.

### Lifetime

- A disposable MCP adapter restart does not change Revit or Document Targets.
- Disabling host exposure immediately removes the Revit Target from discovery and begins Exposure Draining when an operation is running; the generation remains addressable only for operation inspection and cancellation until that operation finishes, then expires. Revit exit or loss of the pyRevit/extension registration expires it immediately. Re-enabling exposure or replacing the registration creates a new Revit Target and remints Document Targets for any documents that remain visibly open.
- Target state must therefore live with, or be recoverable from, the live pyRevit registration rather than the disposable adapter. The topology ticket decides its concrete storage and discovery mechanism.

### Discovery

- One target-discovery interaction returns a fresh, workstation-wide Target Snapshot. It nests every exposed live Revit Target with all eligible Document Targets; it is not split into list and per-target detail calls. Disabled Revit Hosts are omitted and may contribute only to privacy-preserving host and exposure counts, never host or document metadata.
- Each Revit entry contains `revit_target`, Revit version/build, process ID, registration time, a nullable `active_document_target`, and its document entries. At most one Document Target is active per Revit Target; the field is null when no eligible document is active.
- Each document entry contains `document_target`, title, kind (`project` or `family`), a structured local/cloud/unsaved location with available path or cloud identifiers, and read-only, workshared, and modified/unsaved state.
- No redundant `display_label` is required. Agents can form conversational aliases from the structured metadata, while opaque identifiers remain available for calls and diagnostics. Metadata never becomes identity.
- The Target Snapshot is point-in-time and advisory. Every handle is revalidated when used. Correctness cannot depend on a client cache or subscription.
- Complete snapshots are returned by explicit discovery or when an action explicitly requests a final snapshot. Ordinary action results echo only the targets used and compact changes such as closed targets or `targets_changed`. An MCP `subscriptions/listen` invalidation may be supported as an optional optimization, but never as a correctness requirement.

### Request scope and omission

- Workstation actions such as target discovery, installation discovery, and launching Revit require no target. Installation listing remains available independently of launch permission; launch requires the separate opt-in user setting and does not grant host exposure, as defined by [Decide the fate of the Revit launch and installation-discovery tools](12-decide-launch-tools-fate.md).
- Every Revit-scoped automation, in every supported protocol era, requires `revit_target` and deliberately omits `document_target`. It may use the active Revit context and may open, inspect, modify, save, and close multiple documents within one execution and return one final result without per-document MCP round trips.
- Every Document-scoped Request, in every supported protocol era, requires both `revit_target` and `document_target`, even when only one Revit process or eligible document exists. The absence of `document_target` denotes Revit-scoped automation; it is never shorthand for “whichever document is active.”
- Arbitrary-code execution supports those explicit Revit- and document-scoped modes. It remains a privileged, unsandboxed escape hatch: a supplied Document Target controls and documents the intended `doc` context but cannot prevent deliberate code from reaching other application documents through the Revit/pyRevit APIs. Manual transaction behavior and final output capture remain available within those scopes.
- The former temporary legacy-path promise is superseded by [Retire the temporary legacy execution path from the target-identity decision](14-retire-legacy-execution-path.md), which records the cutover precedence and migration-only reuse boundary.

### Validation and stale handles

- Both handles are validated inside the selected Revit process immediately before execution, including the parent-child relationship between the Revit and Document Targets. A race that closes or replaces a target before actual Revit execution must fail at that boundary.
- Unknown, expired, closed, wrong-parent, or otherwise stale handles produce structured tool-execution errors, not malformed-request protocol errors. The result identifies the target type and rejected handle, gives a machine-readable reason such as `document_closed`, `revit_restarted`, or `target_mismatch`, marks rediscovery as the recovery action, and indicates whether a retry is possible.
- Validation never substitutes the active document, a matching title or path, another Revit process, or a newly discovered handle. Mutating calls are not automatically retried against replacements; the agent must rediscover and deliberately choose again.
