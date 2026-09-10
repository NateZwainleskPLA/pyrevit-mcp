# Define the conformance and acceptance contract

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: 05, 07, 08, 10

## Question

What protocol conformance, multi-instance and multi-document scenarios, task lifecycle cases, packaging checks, compatibility cases, failure injections, performance bounds, and documentation outcomes are sufficient to call the migration specification implementation-ready and later prove an implementation conforms to it?

## Answer

### Two acceptance gates

The effort has two separate gates. Passing one never implies passing the other.

1. **Specification ready** means the migration specification is complete enough to implement without making an unstated architecture or safety decision. Every normative requirement is traceable to a resolved Wayfinder decision; interfaces, schemas, state transitions, error categories, invariants, supported-environment policy, migration order, and rollback boundaries are explicit; every requirement names its verification method; and no unresolved placeholder, contradictory legacy behavior, or destination-relevant fog remains.
2. **Implementation accepted** means a particular signed release artifact has passed the executable and manual evidence below on its declared support matrix. Source review, a successful build, or specification completeness alone is insufficient.

The repository owns a versioned acceptance manifest mapping stable requirement identities to tests or narrowly allowed manual checks. A release evidence bundle records the source revision, component versions, pinned MCP SDK and conformance versions, artifact hashes and signature result, environment matrix, test results, performance measurements, and any permitted waiver. Results must be reproducible from documented commands without modifying a user's normal Revit profile or model data.

### Evidence layers and release policy

- Deterministic protocol, validation, catalog, identity, queue, operation, retry, cancellation, retention, and Forensic Record behavior is automated. A simulated Target Runtime supplies controllable clocks, barriers, failures, and target/document lifetimes; tests avoid sleeps where a deterministic synchronization point can express the scenario.
- Revit API behavior, document activation, transactions, Local User Interaction, pyRevit registration, multiple Revit processes, packaging, and process-lifetime behavior are also exercised in live installed Revit. Mocks cannot satisfy those claims.
- Manual checks are limited to usability of the Revit MCP Status surface and confirmation dialogs, endpoint-security observations that cannot be automated, and independent inspection of the final signature and installer experience. No routing, identity, idempotency, model-safety, or data-loss claim may rely only on a manual checklist.
- Tests begin from known disposable models and user-data directories, preserve failure artifacts, and clean up processes and temporary data. A retry may collect diagnostics but never converts the initial failed attempt into a clean pass.
- Identity, wrong-target prevention, duplicate-execution prevention, model-effect reporting, queue safety, protocol compatibility, package integrity, and data-loss gates admit no release waiver. A noncritical failure may be waived only with its affected support claim, rationale, owner, expiry release, and user-visible limitation recorded in the evidence bundle and release notes.

### Declared support matrix

- Each release publishes exact supported Windows editions/build ranges, CPU architecture, Revit major versions, pyRevit versions, client transports, MCP revisions inherited from the pinned SDK, and upgrade/rollback origins. Anything else is unverified rather than implicitly supported.
- Every supported Revit major version passes an installed live smoke covering extension load, Adapter startup, exposure, Target Snapshot discovery, one database read, one atomic mutation against a disposable model, operation polling, clean shutdown, update, and rollback.
- One primary Windows/Revit/pyRevit combination runs the exhaustive live suite. Remaining supported boundaries use pairwise coverage across Windows, Revit, pyRevit, HTTP/stdio, fresh install/update/rollback, and disabled/enabled exposure. A known combination-specific risk adds an explicit case instead of relying on pairwise coverage.
- Hardware, licenses, Revit builds, pyRevit builds, test models, locale, and relevant security software used for acceptance are recorded with the result.

### Protocol and compatibility conformance

- Run the pinned official MCP conformance harness against the modern Streamable HTTP endpoint. Cover `server/discover`, deterministic cacheable catalogs, explicit self-describing tool requests, capability negotiation, malformed and unsupported requests, loopback binding, allowed and rejected `Origin` values, reconnects, and Adapter restart without protocol-session dependence.
- Add product-owned tests only at pyRevit MCP seams: modern and latest-legacy clients see identical tool schemas and route through the same Target Runtime; modern HTTP and legacy stdio installed-package smokes succeed; a mixed-era live scenario preserves one target's FIFO order; and negotiated era, revision, SDK version, and Adapter version appear in the Forensic Record.
- Exact target and document handles are mandatory in every applicable era. Tests prove missing, malformed, stale, expired, cross-parent, and cross-generation handles fail without fallback to the active document, matching metadata, another Revit process, or a replacement generation.
- Catalog output is byte-stable for the same build and advertised capabilities. A pinned SDK upgrade reruns conformance, schema snapshots, the supported-revision review, and mixed-era tests before its support claims change.
- The first migration release must not advertise Tasks. Its protocol-neutral operation fallback is mandatory. If Tasks is later added, acceptance pins its extension revision and proves capability gating, `op_`/`taskId` identity, state and cancellation projection, result equivalence, reconnect/poll behavior, and fallback behavior for clients without Tasks. It never introduces `input_required` for admitted Revit Operations.

### Deterministic Target Runtime and operation scenarios

The automated harness must prove at least:

- discovery with zero hosts, only unexposed hosts, one exposed host, and multiple independently exposed hosts; enabling, disabling, draining, re-enabling, Revit exit, registration loss, and Adapter restart;
- multiple eligible documents including inactive, unsaved, family, cloud-hosted, read-only, and workshared documents, plus exclusion of linked/background/internal documents; activation, rename, save, Save As, close/reopen, parent mismatch, and stale-while-queued behavior;
- FIFO admission within one target across clients and documents, queue boundaries at the configured minimum/default/maximum, lowering capacity without eviction, and genuine parallel progress across independent Revit Targets;
- inline completion and the five-second handoff; every lifecycle transition; repeatable terminal polling; four-hour retention and expiry using a fake clock; target lifetime as the hard ceiling; queued and running cancellation races; Local User Interaction dismissal; and absence of cancellation on disconnect;
- fresh, exact-duplicate, conflicting, future, old, retained, and expired Submission Identities; ambiguous delivery before and after admission; acknowledgement loss; Adapter crash and exact resubmission; and proof that no case executes the same intent twice or redirects it;
- `none`, `atomic`, `checkpointed`, and `manual` Transaction Ownership; valid tool errors versus machinery failures; all model-effect certainty values; safe-state verification; quarantine; confirmed reset; and refusal to start queued work while safety is unknown;
- Forensic Record allowlisting, correlation, flush boundaries, rotation, retention, pruning, settings reload, degraded writes, artifact admission failure, export integrity, corrupt/truncated segments, schema-version reading, and reset safeguards without using the record to reconstruct operational state.

### Required live-Revit scenarios

The exhaustive live suite uses disposable copies and demonstrates:

1. Two Revit Hosts with independently controlled exposure and at least two eligible documents in one host. Commands sent deliberately to each Revit Target and Document Target affect only the addressed subject.
2. A long-running operation in each host overlaps in wall-clock time, while two operations in one host remain FIFO even when they address different documents.
3. Database access to an inactive document does not activate it; UI access activates exactly the addressed document; post-interaction revalidation prevents mutation after the target changes.
4. Atomic success and rollback, checkpointed partial effect, arbitrary-code abnormal termination with honest effect certainty, queued cancellation, cooperative running cancellation, interaction dismissal, document close while queued, exposure draining, and quarantine recovery.
5. Adapter termination and restart during queued/running work, lost acknowledgement followed by exact resubmission, Revit process exit, stale native Routes registration, incompatible Target Runtime revision, configured-port collision, and unavailable or disabled exposure.
6. A mixed modern/legacy FIFO case plus modern HTTP and legacy stdio package smokes, all using the same explicit-target catalog and execution path.

Each mutation verifies model state directly rather than accepting only a successful tool response. Every destructive or failure-injection case uses a disposable model and verifies the reported model-effect certainty against the resulting model.

### Packaging, installation, and security checks

- Build from a clean checkout with locked dependencies. Inspect the final Windows-x64 artifact for expected files, pinned SDK, architecture, version metadata, signature and trust chain, hashes, and absence of undeclared runtime downloads or user-managed Python/`uv` dependencies.
- On a clean supported user profile with no developer runtime, prove fresh install, offline first start, multi-host cooperative start, no-elevation operation, one Adapter under launch contention, stable Connection Descriptor replacement, clean Revit shutdown, update, rollback while Revit is closed, uninstall descriptor removal, and confirmed reset semantics.
- Assert loopback-only listening, baseline Origin validation, explicit port-collision failure, restrictive per-user ACLs for settings and Forensic Record data, sanitized non-code records, and warned opt-in export of exact submitted code. Run the signed release artifact through the organization's ordinary endpoint-security scan and record the result without treating one vendor's scan as a universal guarantee.
- Corrupt, missing, unsigned, wrong-architecture, and interface-incompatible helpers fail visibly while the internal pyRevit Routes and status controls remain available. Production never silently downloads, changes endpoint, selects another runtime, or edits client configuration.

### Performance and resource bounds

Measure on the declared primary acceptance environment after one warm-up, report median and p95 over at least 30 samples, and preserve raw results. Bounds apply to product overhead; a Revit command's intrinsic execution or human interaction time is reported separately.

- Adapter readiness occurs within 10 seconds after the first healthy Revit Host registration is available.
- With healthy local hosts and no executing model command, health, Target Snapshot discovery, operation inspection, and cancellation responses have p95 at or below 1 second.
- The configured five-second inline budget hands active work back as an operation reference within 6 seconds total. Crossing that boundary never cancels or duplicates the operation.
- The default queue admits one running plus 32 waiting operations without loss, reordering, or unbounded process growth. A sustained test through at least ten complete default-queue turnovers returns resources to a stable plateau; continued growth across turnovers fails acceptance.
- Cross-target parallelism is demonstrated with deterministic barriers. Starting equivalent work on a second target must not wait for the first target's execution lane; this is a concurrency invariant, not a fragile speedup percentage.
- Forensic Record open segments, retained storage, artifacts, and exports obey their configured bounds. Catalog and control-request load cannot starve accepted target execution or bypass queue limits.

If a bound proves unrealistic on the minimum supported environment, changing it requires an explicit specification amendment with measured evidence; the implementation may not silently loosen the test.

### Documentation outcomes

Release documentation must contain:

- a support matrix and limitations;
- no-prerequisite install, update, rollback, uninstall, and reset instructions;
- client-owned HTTP and packaged-stdio connection examples, including how to use the Connection Descriptor without treating it as authoritative;
- the exposure consent model and a plain-language explanation of Revit Targets, Document Targets, Revit Operations, Submission Identities, Local User Interaction, cancellation, model-effect certainty, draining, and quarantine;
- troubleshooting paths for no hosts, no exposed targets, stale handles, interface mismatch, port collision, Adapter/helper failure, degraded diagnostics, queue full, expired operations, and endpoint-security quarantine;
- Forensic Record location, privacy limits, retention controls, export behavior, exact-code warning, and a support-export procedure;
- developer instructions for the conformance harness, simulated Target Runtime, live disposable models, environment matrix, performance measurements, requirement traceability, and release evidence bundle.

All commands, paths, screenshots, schemas, and examples are verified against the signed release artifact. Documentation that still describes a single active Revit instance, implicit active-document routing, a user-managed production Python runtime, SSE/combined legacy modes, or the former `main.py` workflow fails acceptance.
