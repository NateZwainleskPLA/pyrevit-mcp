# Prototype the in-Revit execution lane and control plane over pyRevit Routes

Type: prototype
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: 15, 16

## Question

Can a Revit Host implement the resolved execution-safety and operation-lifecycle contracts on top of pyRevit Routes as installed, and what does the spec have to say about it?

Use the engine, development baseline, and facility constraints resolved in [Choose the pyRevit engine for host-side runtime code](16-choose-host-engine.md#answer). Record the actual loaded engine, pyRevit build/checkout, Revit version, and .NET runtime with the prototype evidence. Include startup-state/callback persistence and reload behavior in the lifetime checks. Distinguish exploratory evidence from acceptance on the release-time stock baseline.

Facts verified in the installed pyRevit Routes source on 2026-09-04:

- One module-level `RequestHandler` and one `ExternalEvent` are shared by every Routes request in the process (`routes/server/server.py`).
- Any handler that declares `uiapp`, `uidoc`, or `doc` is marshaled to the Revit UI thread; the HTTP thread blocks and busy-waits on `IsPending` until it completes.
- Two concurrent API-context requests overwrite the shared handler's `request` and `handler` fields before `Raise()`, a race.
- Handlers without API-context arguments run directly on the HTTP server thread.
- `ExternalEvent.Create` is only allowed on the main thread, so any extension-owned event must be created at startup.
- `serverinfo.get_registered_servers()` lists sibling Revit instances from per-instance pickle files and allocates ports upward from the configured base.

Build a throwaway extension that: admits submissions and serves inspection and cancellation from non-context handlers against a thread-safe registry; runs queued work through an extension-owned ExternalEvent on the UI thread; polls and cancels a long-running operation while it runs; survives a Local User Interaction (pick) mid-operation; and exposes sibling discovery. Report which resolved requirements hold, which need amendment (for example, control-plane latency while Revit is busy or modal), and what the adapter must never do (such as concurrent context calls to one host).

Also exercise the runtime obligations in [Define the explicit-target tool catalog and per-command declarations](15-define-tool-catalog.md): database-mode work on an inactive document must leave the active document unchanged; UI activation requires the explicit flag and post-activation validation; document close must verify completion and must stop after save failure; cooperative color cancellation must roll back the full requested view batch before commit. Check bounded control-plane reads without unsafe off-thread Revit API access. Record unsupported cases or necessary decision amendments explicitly rather than adding hidden activation, posted-command success claims, or extensive view-color workarounds. This remains a throwaway feasibility prototype, not implementation of the full catalog.

## Comments

- 2026-09-09: Claimed for NateZwainleskPLA as the first open, unblocked, unclaimed ticket. The user participated in pyRevit reloads and live picking. The final pick trial was explicitly confirmed: the user saw the status-bar instruction and pressed Esc. Earlier ambiguous interaction and probe defects are retained in the evidence rather than counted as passes.
- Prototype and evidence captured on local branch `prototype/host-execution-lane`, commit `e808d07e7d12876c974e3e084cb5dfe101aa5cc6`, under `prototype/`. [Exploratory findings and evidence index](../../../../pyrevit-mcp-prototype-host-execution-lane/prototype/FINDINGS.md) and [runnable probe instructions](../../../../pyrevit-mcp-prototype-host-execution-lane/prototype/README.md). Durable retrieval: `git show e808d07e7d12876c974e3e084cb5dfe101aa5cc6:prototype/FINDINGS.md`. The branch is local and has not been merged into master or pushed.
- The user also reported a console-only STA `Thread.Sleep` warning that was absent from the MCP responses. It is recorded as a limitation of the deliberate busy-thread experiment, not hidden or interpreted as a successful production waiting strategy.

## Answer

### Feasibility verdict

The private execution lane and synchronized control registry are feasible in the tested development environment. The complete as-installed Routes lifecycle is not yet proven: an intermittent HTTP outage around reload blocks adopting it as the release-ready host transport. Resolve the newly specified [Choose the host listener lifecycle after the Routes reload failure](20-choose-host-listener-lifecycle.md) before finalizing migration sequencing.

Use non-context Routes handlers for admission, operation inspection, cancellation, and serving cached snapshots. Retain an extension-owned ExternalEvent created during valid startup API context, with all queued Revit API work executed through that lane. This avoids the shared Routes context handler and its busy-wait for these requests. HTTP readers must access copied primitives under synchronization, not dereference live Revit objects. Target/document validation remains required at execution and after activation or Local User Interaction.

### Observed support for the existing contracts

- **Runtime and lifetime:** actual IronPython 2.7.12 on .NET 8.0.31, Revit 2025 build 25.4.50.35. Python modules loaded from clean development pyRevit commit `cfce05924074985878393fcc1692ec729a6f17d0`; loaded runtime assemblies also carried 6.5.3.26176 versions. This mixed custom environment is exploratory evidence, not a stock-release support claim. Startup retained callbacks, later commands ran on UI thread 1, full reloads created new generations and stopped the prior runtime, and a subsequent old-generation submission was rejected. Old operations were not resumed.
- **Execution and controls:** observed FIFO execution, queued cancellation, running cancellation at a cooperative checkpoint, and HTTP polling while the UI thread was occupied. The busy experiment's 77 state reads had observed p95 29.40 ms. These are small feasibility samples; existing acceptance bounds and matrix still apply.
- **Local User Interaction:** during the final native pick, HTTP polling remained responsive (21 reads, p95 26.80 ms), and cancellation was recorded while the operation remained running. The user's Esc completed it normally with `user_canceled` and no model effects. An agent cancellation request does not forcibly interrupt native selection.
- **Document context:** read the inactive scratch document without changing activation; missing UI permission produced `ui_change_required`; explicit activation succeeded and verified the addressed document identity.
- **Graphics:** canceled after reaching the second requested view, rolled back the enclosing transaction, and independently verified that all 24 checked projection-line-color overrides matched their unset fixture defaults. This proves the rollback mechanism for the fixture, not every view/category or the successful-commit race.
- **Save and close:** native save cancellation returned an error and left the document open without attempting close. Explicit inactive-document close returned true, invalidated the document, and, after fixing prototype snapshot cleanup, removed it from the refreshed snapshot while allowing subsequent queue work. Native synchronous active-document close returned an explicit unsupported/error result and left the document open.
- **Discovery:** native sibling discovery returned the one live process and its registration. Two-process concurrency and process-exit behavior remain acceptance coverage, not inferred successes.

### Specification consequences and limits

Retain the resolved operation, explicit-UI, transaction, cancellation, and catalog contracts. The demonstrated synchronous active-close path must return an explicit unsupported/error outcome. Do not silently activate another document, infer success from posting a UI command, or promise a completion mechanism that has not been verified. A later implementation may supply a separately verified mechanism within the existing contract.

Target Snapshots remain advisory point-in-time data: freshness pauses during API callbacks and local interaction. Prune invalid Document wrappers before refreshing, and make execution-lane cleanup exception-safe. The first probe failed that cleanup after a successful close; the corrected close plus subsequent queued operation was verified. This was a probe defect, distinct from the broader HTTP outage.

Do not send concurrent API-context Routes requests to one host, inspect Revit documents off-thread to make control reads appear fresh, treat a transport timeout as cancellation, or retry ambiguous mutations with new intent. Preserve exact-identity retry, expiry, and quarantine rules already specified. The prototype does not implement the production deduplication or recovery mechanisms.

The deliberate STA sleeps elicited the console warning and do not establish normal UI responsiveness or a production wait primitive. Replacing them with a message-pumping wait may change reentrancy and needs its own validation. Native pick polling is separate evidence. Arbitrary modal dialogs, stock release acceptance, process restart, two-target execution, capacity contention, full deduplication/retention, and commit/quarantine races remain unverified. No acceptance contract is weakened by these limits.

### Follow-through

The post-reload outage affected an unknown route and native sibling discovery as well as probe operations; a later full reload restored responses. Its cause is unresolved. The listener-ownership/lifecycle fog has graduated to [Choose the host listener lifecycle after the Routes reload failure](20-choose-host-listener-lifecycle.md), and that decision now blocks migration sequencing. Do not choose a private listener or change pyRevit merely on this evidence.

The installed probe has been stopped, its event disposed and callbacks detached, its routes removed, and its folder renamed `WayfinderProbe.disabled`. All scratch documents were verified closed. Source and evidence remain on the throwaway branch; this ticket produces no migration implementation.
