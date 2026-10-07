Listener PR #6 review response
=============================

Scope: Origin `NateZwainleskPLA/pyrevit-mcp` PR #6, `pr/listener-lifecycle`
against `master`. Original published head: `fd4250c5bc6bf33bc849eda6b55c509fdb343b47`.
The original build branch and peer worktrees remain unchanged.

Review status
-------------

The existing Opus reviewer thread
`mcp:ee24b98a-4e42-467a-9310-c13efb5ac89d` stopped at its provider session limit
before a final report or findings handoff. One owner-requested resume in that
same thread immediately hit the same limit. No additional reviewer thread,
provider switch, or claimed reviewer approval substitutes for that missing
handoff. The responses below address concrete problems reconstructed from the
saved review activity and its local thread-detection repro. Final review
completion/confirmation remains outstanding.

The saved system notice identifies an account-wide Claude five-hour usage cap,
resetting October 7, 2026 at 15:20 America/Los_Angeles (22:20 UTC). The existing
reviewer/worktree/evidence remain intact. No further pre-reset retry, new thread,
provider substitution, scheduler or timer for retrying the review was created.

Ownership query: unreadable rows
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

Thread observation compatibility
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

Source comparison and native limits
-----------------------------------

The historical `cfce059` defects are retained as historical evidence. A separate
source-only audit of installed `C:/Program Files/pyRevit-Master` returns one
start and shutdown-before-close, with exit 0. The runbook records inspected file
hashes and directs users to compare the actual chosen baseline before proposing
a patch that is already present. No installed-source inspection is presented
as evidence of what any live Revit process has loaded.

No native fixture was supplied, and no native requests, probe activation,
installation, reload, model edits or shared configuration changes occurred.
The listener's accepted-worker drain, event/engine retention and full native
reload matrix remain pending release gates. No production listener patch or
dialog/diagnostics foundation is introduced by these corrections.

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
a proven defect. The original Opus review is still incomplete; these assessments
must not be described as exhaustive Opus findings, completion or reapproval.

Validation commands
-------------------

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_listener_lifecycle.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit -q
git diff --check
```

Final results are reported with the local correction commit to the coordinator;
they establish the diagnostic behaviors above, not native acceptance or the
unavailable reviewer's approval.
