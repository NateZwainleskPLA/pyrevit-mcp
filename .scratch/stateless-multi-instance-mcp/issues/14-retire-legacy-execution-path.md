# Retire the temporary legacy execution path from the target-identity decision

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Does the legacy cutover decision fully supersede the "temporary legacy path" retained by the target-identity decision, and what replaces it during migration?

**Define Revit Target and Document Target identity semantics** keeps a temporary legacy path with the current `execute_revit_code(code, description)` signature, fixed first-instance routing, active `doc`/`uidoc` injection, and unrestricted namespace. **Define the legacy compatibility and cutover contract**, resolved later, forbids any targetless execution path, any legacy-only artifact, and preservation of former single-Revit active-document semantics. CONTEXT.md still qualifies Document-scoped Requests as "modern", implying a non-modern path survives.

Confirm which decision wins. If cutover wins, amend the target-identity ticket and CONTEXT.md, and state whether any transitional behaviour (for example, existing tool-specific Routes behind the Target Runtime during migration, as the topology ticket allows) is permitted and for how long.

## Comments

- 2026-09-09: Claimed for NateZwainleskPLA as the second available decision, leaving **Reconcile the per-user storage root across topology, installation, and Forensic Record decisions** to the concurrent session.
- Proposed resolution, awaiting the human decision: the later cutover contract supersedes the temporary targetless execution promise for every supported protocol era. Preserve privileged arbitrary-code execution within explicit Revit- and Document-scoped modes, including active-context access for deliberately Revit-scoped automation. Existing tool-specific Routes may serve only as internal migration scaffolding behind the Target Runtime, with explicit target validation and the common execution lane, and must be retired before the first accepted signed release. The migration-sequence ticket would name the exact removal checkpoint. An alternative presented to the user permits compliant internal Routes to remain; neither proposal preserves a client-facing targetless path.
- Code evidence: `tools/code_execution_tools.py` currently submits only code and description to `/execute_code/`; `main.py` uses a fixed localhost port; `revit_mcp/code_execution.py` injects the active `doc`/`uidoc` and unrestricted builtins. Other handlers also read active context directly. Consequently, reusing an unchanged route behind a wrapper does not establish document targeting: migration reuse must bind and validate the intended context and preserve execution ownership. Removing targetless routing does not itself require removing privileged code, manual transactions, or output capture.
- 2026-09-09 resolution: the user selected “Adopt the recommended resolution.” The answer below records the adopted decision; the proposal above is conversation history.

## Answer

### Cutover precedence and retained capabilities

- [Define the legacy compatibility and cutover contract](08-define-legacy-cutover.md) fully supersedes the temporary legacy execution promise in [Define Revit Target and Document Target identity semantics](03-define-target-identity.md). Every supported protocol era uses the same explicit-target catalog and Target Runtime. No client-facing targetless execution signature, first-instance default, or session-selected target survives the migration contract.
- Revit-scoped automation requires a Revit Target; Document-scoped Requests require both their Revit Target and Document Target. Workstation discovery and permission-gated launch remain workstation-scoped and require no execution target.
- Privileged arbitrary-code execution, manual transaction behavior, and final output capture remain available within those explicit scopes. Revit-scoped automation may deliberately use active context and manage multiple documents. A Document Target binds the intended document context and must never silently fall back to the active document; it does not sandbox arbitrary code from other Revit APIs or documents.

### Transitional Routes and removal boundary

- Existing tool-specific Routes may remain only as internal migration scaffolding behind the Target Runtime. Every admitted command must retain explicit target binding and validation, the common target-owned Execution Queue, and the established operation, retry, and cancellation contract. No alternate client-facing catalog or execution bypass is permitted.
- Unchanged handlers that independently obtain the active document cannot satisfy Document-scoped Requests merely by receiving a targeted wrapper. Adapt their context access or reuse their implementation logic under Target Runtime ownership before using them for those requests.
- Remove the old tool-specific Routes scaffolding before the first accepted signed release. [Define the migration sequence and rollback checkpoints](11-define-migration-sequence.md) must identify the exact removal checkpoint and its evidence within this fixed deadline. Rollback remains whole-package replacement under the cutover contract, not a legacy mode in the new package.
- This deadline concerns the old tool-specific Routes scaffolding, not pyRevit Routes as a possible transport for the Target Runtime; the host execution-lane prototype still owns the latter investigation.

### Reconciliation

- Updated the identity decision to apply scope requirements to every supported protocol era and replaced its legacy-path promise with a pointer here.
- Updated the topology decision to point here for transitional reuse and removed the ambiguous “legacy adapter” wording.
- Removed the “modern” qualifier from the Document Target glossary definition in `CONTEXT.md`.
- Added the removal-checkpoint requirement to the existing migration-sequence ticket. No additional decision ticket is needed; resolving this ticket unblocks the tool-catalog ticket's remaining dependency.
