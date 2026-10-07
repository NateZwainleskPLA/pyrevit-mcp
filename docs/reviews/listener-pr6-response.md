Listener PR #6 review response
=============================

Scope: Origin `NateZwainleskPLA/pyrevit-mcp` PR #6, `pr/listener-lifecycle`
against `master`. Original published head: `fd4250c5bc6bf33bc849eda6b55c509fdb343b47`.
The original build branch and peer worktrees remain unchanged.

Review status
-------------

The existing Opus reviewer thread
`mcp:ee24b98a-4e42-467a-9310-c13efb5ac89d` completed its original formal report
at local reviewer commit `f1f7f2d`, reviewing `4e8ec5f..fd4250c`. Verdict:
**approve with changes**, with findings F1-F6. That original-report gate is
fulfilled. The report and repro remain in its read-only review checkout;
this record maps each finding to owned corrections and owner validation.
Focused reviewer confirmation of corrected candidate `dc262f1` is complete,
recorded at local reviewer commit `7119caf`: all F1-F6 resolved, no material
residuals, and no objection to the owned fast-forward publication. The reviewer
confirmed imports from this checkout, 35 focused/109 unit tests, the inverted
original repro, actual Windows ownership rows, and both source audits.

The review notes a conservative boundary race: if the watchdog fires as the
last byte arrives, a complete response can be labeled a timeout. This is accepted
as non-blocking because diagnostics fail conservatively; it is not native
acceptance or evidence of an outage cause.

The saved system notice identifies an account-wide Claude five-hour usage cap,
resetting October 7, 2026 at 15:20 America/Los_Angeles (22:20 UTC). The existing
reviewer/worktree/evidence remain intact. No further pre-reset retry, new thread,
provider substitution, scheduler or timer for retrying the review was created.

F1: ownership query retains unreadable rows
-------------------------------

The embedded PowerShell pipeline previously tried to call `ToUniversalTime()`
on a process start time that could be null or inaccessible. PowerShell could
emit an error and drop that individual pipeline row while the final JSON
conversion still exited successfully. In a mixed readable/unreadable-owner
result, validating only surviving rows could accept an incomplete ownership
inventory.

The corrected query sets terminating error handling and retains each original
connection row's owning PID, local address, and local port. Per-process lookup
failure produces `process_started_at: null` and `ownership_error`. The Python
guard rejects that row and never sends a further GET based on a partially
verified inventory. This remains deliberately conservative across all listening
rows on the supplied port; it does not select a replacement process.

Validation executes the actual embedded PowerShell with controlled OS data
sources: one readable process and one null-start-time process on distinct local
bindings of the same port. Both rows survive, the readable-only result matches,
and the mixed result fails closed. The separate real Windows local Python
socket test also remains passing. These fixtures neither inspect nor contact
Revit.

F2: thread observation compatibility
--------------------------------

The saved reviewer repro returned an empty `observable_serve_threads` list for
both IronPython 2.7's `_Thread__target` storage and a newer RoutesServer's
`_serve_forever` wrapper target, even though a matching worker existed.

The corrected observation supports `_target` and `_Thread__target`, Python 3
`__self__` and Python 2 `im_self`, and the corresponding direct/wrapper
serve-loop owners. Eight parameterized cases cover the complete combination.
The original reviewer repro now observes both workers when run against this
checkout. Threads with unavailable targets are recorded separately, and a
best-effort label makes clear that missing observations do not prove absence,
teardown, or accepted-worker drain.
Matched rows now also include daemon status and target name. If no thread has
an introspectable target, the receipt explicitly reports detection unavailable
and null observable threads; the reviewer-requested unavailable test covers it.

F3: source comparison and native limits
-----------------------------------

The historical `cfce059` defects are retained as historical evidence. A separate
source-only audit of installed `C:/Program Files/pyRevit-Master` returns one
start and shutdown-before-close, with exit 0. Its version file reports
`7.0.0.26254+1828`; its wrapper already has a `_stopping` guard and retry loop.
The runbook now makes that release (or the chosen supported release) the
comparison baseline, with a remaining proposal limited to `server_close()`,
accepted-worker drain policy, and failed-stop visibility. Historical patches
apply only where their defects remain. No installed-source inspection is presented
as evidence of what any live Revit process has loaded.

No native fixture was supplied, and no native requests, probe activation,
installation, reload, model edits or shared configuration changes occurred.
The listener's accepted-worker drain, event/engine retention and full native
reload matrix remain pending release gates. No production listener patch or
dialog/diagnostics foundation is introduced by these corrections.

F4: Listen rows are counted independently of unique processes
-----------------------------------------------------------

The raw query retains local address/port. Receipt/checks now report maximum
observed `listen_socket_count` across before/after queries, and separately
`unique_owner_process_count`. A two-socket/same-PID fixture reports 2 sockets
and 1 process, retains both addresses, and still passes the required HTTP checks.
Socket counts are hypothesis evidence, not a proven outage cause or a health gate.
A mixed-owner fixture preserves both rows and sends no GET when one start time
is inaccessible.

F5: overall request deadline
----------------------------

Commit `102e28e` bounds connection setup, headers and body under the same
deadline, including drip-fed headers/body that renew ordinary per-read timeouts.
The tests and separate ownership-query limits are described below.

F6: retired-engine cleanup failure is restart-only recovery
---------------------------------------------------------

The runbook now explicitly directs Capture before Start/Replace after full
reload, retains previous evidence/logs if Capture fails, and treats
`Previous diagnostic cleanup failed` as an expected fail-closed matrix result.
Start/Replace remain blocked until the disposable process restarts; there is no
automatic owner clearing, activation retry, or restart of an editing session.
Native cross-engine cleanup remains unproved.

Assessment of unconfirmed review concerns
----------------------------------------

These were questions in saved reasoning, not finalized Opus findings. Owner
tests assessed them independently:

* Initial capture/cleanup failure: reproduced an unretained successfully created
  event when capture threw and disposal also threw. A failing test demonstrated
  the missing retained owner. Construction now creates the event before
  subscription, retains the probe, and then activates it inside the cleanup
  boundary. Partial subscription failure and initial capture failure either
  detach/dispose successfully or retain an expired owner that blocks replacement.
  Tests also confirm that successful cleanup allows a clean later Start.
* Old-engine teardown: actual cross-engine native removal cannot be established
  without a disposable fixture. Doubles verify that a retained delegate removal
  exception expires callbacks, preserves the owner/event, and blocks replacement
  rather than clearing the lease. Another test creates a new Python Probe class
  while retaining an old instance and verifies removal of the exact old delegate.
  These establish adapter containment, not native engine lifetime. The native
  release gate remains explicitly open.
* Unsupported audit source shape: reproduced `StopIteration` for a missing
  source definition and `ValueError` for unobserved shutdown ordering. The audit
  now emits an inconclusive `unsupported_source` receipt with null defect flags,
  source hashes/error and exit 2. Tests exercise both shapes and CLI receipt/exit
  behavior; supported historical and separately installed source audits retain
  their meaningful defect/no-defect results.
* Per-read versus overall timeout: slow-drip local HTTP fixtures reproduced a
  response exceeding the supplied timeout while each read arrived in time. The
  collector now enforces an overall connection/header/body deadline by shutting
  down only its own socket when the budget expires. Tests cover both drip-fed
  headers and body, preserve partial byte counts, and verify bounded failure.
  OS ownership subprocess limits are documented separately. This local network
  watchdog neither cancels Revit work nor schedules a reviewer retry.

All locally reproduced diagnostic defects above are corrected and tested.
Unconfirmed native teardown remains a release gate, not a finding converted to
a proven defect. These independent assessments are separate from the finalized
F1-F6 findings and must not be described as reviewer reapproval.

Validation commands
-------------------

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_listener_lifecycle.py -q
# 35 passed
.\.venv\Scripts\python.exe -m pytest tests/unit -q
# 109 passed
git diff --check
# passed
```

Final results are reported with the local correction commit to the coordinator;
they establish the diagnostic behaviors above, not native acceptance. The
separately completed focused reviewer confirmation is recorded above.
