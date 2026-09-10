# Define the Forensic Record contract

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: 04, 06, 07

## Question

What events, correlation schema, exact-code artifact format, per-user storage layout, access controls, non-code redaction rules, rotation and retention bounds, export workflow, cleanup behavior, and write-failure semantics must the Forensic Record use to support useful post-crash forensics without becoming authoritative Revit Operation state or an accidental replay mechanism?

## Answer

### Purpose and authority

- The **Forensic Record** is the extension-owned evidence collection. It is unrelated to Autodesk Revit's native Journal, which this product never reads, writes, rotates, exports, or deletes.
- The record serves local operator diagnosis and deliberate export to trusted support. It sends no telemetry and supports no unattended remote collection.
- It preserves enough evidence to reconstruct routing, delivery, admission, operation lifecycle, effect certainty, and diagnostic health. It never recovers, resumes, replays, decides, or reconstructs a Revit Operation, result, or model state.

### Module seams

- A deep **Forensic Writer** module accepts only closed, typed semantic events, secures exact-code artifacts, and reports writer health. Callers do not construct raw dictionaries or supply paths.
- A deep **Forensic Control** module owns status, configuration, export, and reset.
- These two modules hide serialization, field allowlisting, redaction, ACLs, flushing, checksums, rotation, retention, cleanup, and filesystem layout. The modules' interfaces are the acceptance-test seams.

### Per-user storage and access

- Use the fixed product root and evidence/settings layout defined by [Reconcile the per-user storage root across topology, installation, and Forensic Record decisions](13-reconcile-storage-root.md). That ticket owns Local AppData resolution and supersedes this decision's original use of `PYREVIT_APP_DIR` and Roaming AppData.
- Keep the atomic product settings file separate from `pyRevit_config.ini` so an all-users pyRevit installation cannot make per-user settings machine-scoped or admin-only.
- Apply an explicit Windows ACL admitting the current user, SYSTEM, and local administrators. Streams, artifacts, manifests, and staging files inherit it. Do not use the extension installation directory, ordinary temporary storage, or `ProgramData` for the retained record.
- Every MCP Adapter run and every Revit Target generation owns a separate single-writer NDJSON stream. No file has multiple writers and no central sequencer coordinates writers.
- Rotate a live stream into immutable 10 MiB segments. An open segment is never pruned or rewritten.

### Event and correlation contract

- Use a closed, versioned event catalog covering writer start/stop and diagnostic degradation/recovery; settings and retention cleanup; protocol negotiation and rejection; legacy-session creation and termination; discovery; delivery attempt, acknowledgement, ambiguity, retry, and failure; exposure enablement, draining, and target expiry; submission admission, rejection, and recovery; the normal inline-to-operation handoff; operation lifecycle transitions; cancellation requests; Local User Interaction boundaries; target and document validation failures; quarantine entry and confirmed clearing; export; and reset.
- Omit routine health and operation inspection, client polling, and progress chatter. Discovery events contain only bounded counts and outcome categories rather than target or document display metadata.
- Every event carries a schema version, opaque unique event identity, writer kind and run identity, monotonically increasing per-writer sequence, RFC 3339 UTC timestamp, event type, and effective settings revision.
- Where applicable, events also carry the Revit Target, Document Target, Revit Operation, Submission Identity, normalized-command fingerprint, delivery-attempt identity, and artifact identity. Omit inapplicable fields rather than inventing placeholder identities.
- Sequence is definitive only inside one writer stream. Delivery-attempt and domain identities establish causal links across streams. UTC timestamps permit an approximate merged display but never claim a total order between unrelated processes.

### Non-code minimization and terminal evidence

- Ordinary events are schema-allowlisted. Never persist request bodies, arbitrary arguments, tool results, document titles or paths, usernames, machine names, absolute paths, locals, source lines, arbitrary object representations, or arbitrary client-supplied fields.
- Preserve OS build; Revit, pyRevit, extension, Adapter, and SDK versions; negotiated protocol era and revision; effective Forensic Record settings; writer health; and gap counts. Preserve only sanitized, length-bounded `clientInfo.name` and `clientInfo.version`, explicitly marked as self-reported.
- Failure evidence consists of a stable product error category or code, exception type, and sanitized stack frames without locals, source text, absolute paths, or object representations. Raw messages are prohibited unless the product schema explicitly allowlists that product-defined message.
- A terminal operation transition records terminal state, elapsed time, whether cancellation was requested, model-effect certainty (`none`, `committed`, `partial`, or `unknown`), and result classification (`success`, `valid_tool_error`, or `machinery_failure`) plus any allowlisted error code. It never records a result body or free-form error text.

### Exact-code artifacts and admission

- Preserve accepted automation source as the exact decoded source, without normalization or wrapper, encoded as UTF-8 in a separate `.py` artifact with an opaque random filename. The linked admission evidence records artifact identity, SHA-256 digest, byte count, and encoding.
- Put no Submission Identity, target identity, command description, arguments, or execution wrapper in the filename or artifact. The artifact is inspectable evidence, not a self-contained replay package.
- Within serialized admission, complete structural, target, deduplication, and capacity checks first. Immediately before operation creation and enqueueing, atomically create, flush, and secure the artifact. If this cannot be done, reject the automation submission without creating a Revit Operation.
- An exact retry recovers the existing operation and artifact. A fresh Submission Identity receives a distinct artifact even when its source digest matches another artifact. Conflicting, malformed, stale-target, or capacity-rejected submissions retain sanitized rejection evidence only. An unexpected admission failure after artifact creation removes the orphan best-effort and marks any undeletable orphan for managed cleanup.

### Durability and degraded operation

- Flush admission, terminal-transition, quarantine, and diagnostic-health events immediately. Lower-risk events may buffer for at most one second.
- After an operation is admitted, a record-write failure never changes its lifecycle, result, effects, queue position, or cancellation behavior. The owning writer marks diagnostics degraded, retains the first and latest failure times and a stable failure category in memory, retries periodically, and marks recovery when durable writes resume.
- MCP health and the local status surface show persistent degraded state, affected writer, failure category, and first/latest failure time. Emit one rate-limited local process warning; do not attach warnings to every tool response.
- The code-artifact store must be healthy for new automation admissions. Non-code commands and already-admitted operations continue under degraded diagnostics.

### Rotation, retention, and settings

- Defaults are a 14-day age limit and a 250 MiB total size cap. The operator may change or disable age expiry. A finite size cap of at least 50 MiB is always required, may be set to any finite larger value, and has no product-defined maximum or `unlimited` sentinel.
- When age or size cleanup is due, remove the oldest closed segments and their linked code artifacts first, including closed segments belonging to a still-running writer. Never prune an open segment. Reject a new automation submission if its artifact cannot fit after eligible pruning.
- Run cleanup at writer startup, after segment rotation, after a settings change, and before export. Do not install a daemon or timer-only cleanup process. Disabled age expiry means evidence survives until displaced by the size cap.
- A single control surface atomically replaces `settings.json` with a monotonically increasing revision. Writers load it at startup, detect changes within 60 seconds, and stamp each event with the effective revision. Reducing the size cap triggers cleanup immediately.

### Export, integrity, schema evolution, and reset

- `Export diagnostics` defaults to the last 24 hours and accepts a custom interval. If the interval selects any retained event for a Revit Operation, expand the selection to every retained event for that operation.
- Create a ZIP outside the managed store containing a manifest, checksums, selected NDJSON segments, and a sanitized environment summary. Exact-code artifacts are excluded by default and require a separate warned `include submitted code` choice; include only artifacts linked to selected operations.
- The manifest records the requested and expanded intervals, effective settings, schema versions, pruning or corruption gaps, active-writer cutoffs, file checksums, and whether code was included. The completed ZIP is user-owned and never subject to managed retention or reset.
- A reader ignores and reports only an incomplete trailing NDJSON line left by a crash. It preserves any segment with interior corruption or a checksum mismatch, reports the gap, and never repairs, infers, or rewrites evidence. Missing or digest-mismatched code artifacts are reported as gaps and never reconstructed.
- Completed segments are immutable across product upgrades. Additive schema changes increment a minor version; breaking changes create a new major storage version. The installed reader fully interprets the current and immediately preceding major. Older or unknown segments are exported byte-for-byte with an `uninterpreted` warning rather than migrated or discarded.
- `Reset Revit MCP data` requires the Adapter stopped and every target disabled and drained. It deletes managed Forensic Record data, product settings, and temporary support staging, but never exported ZIPs or Autodesk Revit Journals. Locked-file failures are reported precisely and left retryable rather than hidden or force-deleted.
