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
