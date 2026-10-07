Routes listener lifecycle investigation
======================================

Delivery status: rerunnable diagnostics and source-backed baseline fix proposal.
Native reload acceptance remains blocked on an explicitly supplied disposable
Revit host. No extension was installed, session reloaded, configuration changed,
or model accessed for this investigation. Production startup is unchanged.

Evidence and provenance
-----------------------

The existing `prototype/host-execution-lane` at `e808d07` was read without editing
its checkout. Its `prototype/FINDINGS.md` also matches the supplied local evidence
path. The observed environment was Revit 2025 API `25.4.50.35`, native build
`20260410_1515(x64)`, IronPython `2.7.12 (2.7.12.1000)` on .NET `8.0.31`, source
pyRevit `cfce05924074985878393fcc1692ec729a6f17d0`, and loaded runtime assembly
`pyRevitLabs.PyRevit.Runtime.2025, Version=6.5.3.26176`. Preserve this mixed
custom source/binary provenance; it is not stock-release acceptance.

After one reload the prototype's first state GET succeeded, but an old-generation
submission and subsequent state GET timed out. Unknown probe routes and native
`/routes/sisters` also timed out with zero response bytes. A later full reload
restored HTTP responsiveness. The corrected targeted probe reload subsequently
rejected an old generation. Those later successes do not explain the outage.
The closed-document-wrapper defect was separately fixed in the prototype; it
must not be conflated with the listener outage or the STA sleep warning.

The sibling pyRevit checkout was clean at the same source commit when inspected.
The audit runs selected actual source lifecycle methods with inert doubles:

```powershell
python -m scripts.listener_lifecycle.source_audit 'D:/OneDrive - PLA Designs/Documents/Dev/pyRevit MCP/Dev/pyRevit' --output source-audit.json
```

Observed: `first_activation_worker_count: 2`, `retained_worker_count: 1`, and
events `start`, `start`, `socket.close`, `HTTPServer.shutdown`, `join`. Exit 1
signals a detected source defect, not a native failure. The checked-in
`scripts/listener_lifecycle/source-evidence.json` records the inspected paths and
file hashes. The audit creates no socket or thread and executes no source-level
imports. It does not establish that either defect caused the historical outage.

The audit supports the two inspected source shapes. An absent definition,
unavailable harness dependency, or shutdown pattern whose ordering cannot be
observed returns `audit_status: unsupported_source`, null defect flags and an
error receipt, with exit 2. It is inconclusive rather than healthy. Exit 0 is
reserved for a supported source shape with neither detected defect, and exit 1
for supported source-level defect evidence. None of these exits prove native
listener behavior. Source files are read once for consistent code/hash evidence.

A separate source-only comparison on October 7 inspected
`C:/Program Files/pyRevit-Master`, whose version file reports
`7.0.0.26254+1828`. Its audit returned one activation worker and
events `start`, `HTTPServer.shutdown`, `socket.close`, `join`, with both defect
flags false (exit 0). Inspected file hashes were
`server.py: 676f5ed1e96e8a11bf9f7c07d06755e7090b8efbf299500a5fd09d8d40d1ce3e`
and `server/__init__.py: 40984c0997e4597be2b4d83a63ce5972af05ae1fd1e3675521c4fa64ef52663d`.
That installed source already removes the duplicate activation start and calls
shutdown before socket close. It also uses a `_stopping` guard in its
`_serve_forever` wrapper, with a log-and-retry loop for serve errors. The
historical duplicate-start and close-order proposal is therefore relevant to
the recorded `cfce059` source, not a claim that those defects persist in every
installed version. Installed disk source is not proof of the code or assemblies
loaded in any Revit process. No Revit process was queried for this comparison.

Source-supported distinctions
-----------------------------

* Extension lifecycle: the prototype owns its Idling delegate, private
  ExternalEvent, retained runtime, and route handlers. Detaching its callback
  does not own or repair the native Routes server. Retired runtime references
  must remain expired; disposing an active/pending event is unsafe.
* Historical native listener lifecycle at `cfce059`: `RoutesServer.__init__()` calls `start()`;
  `activate_server()` calls `start()` again. Both threads target the same
  `serve_forever` method, while `server_thread` retains only the second.
  `stop()` therefore joins only one retained thread. `ThreadedHttpServer.shutdown`
  closes the socket before `HTTPServer.shutdown`. This is a concrete ownership
  defect and a candidate for disposed-socket symptoms, not proof of causation.
* Registrations: native serverinfo uses a PID-associated pickle. `register()` can
  return an existing file; discovery enumerates running processes. A record is
  neither a live socket handshake nor instance/runtime identity, and a port is
  not an identity. The collector checks actual socket PID/start time separately.
* Engine lifetime: `IronPythonEngine.Shutdown()` cleans builtins and streams.
  Session reload clears engines, resets routes, and deactivates/reactivates the
  listener. Retained Python delegates and workers can outlive the engine whose
  resources they use. The probe records loaded assemblies, module path and thread
  observations to distinguish this hypothesis; no engine cleanup patch is claimed.

Ranked hypotheses for the disposable trial
-----------------------------------------

1. Incomplete socket or accepted-worker teardown. Installed 7.0 already removes
   the historical duplicate start and fixes shutdown-before-close ordering;
   compare that release first. Those historical defects remain hypotheses only
   for a build that still contains them. Native endpoint hangs on 7.0 would need
   separate evidence about socket release and accepted-worker/engine lifetime.
2. Engine resources referenced by a surviving native worker are retired during
   full reload. Callback-only replacement should pass while full reload fails;
   source-correct listener teardown alone may not cure it. Record engine/assembly
   provenance and correlated exception logs before considering ownership changes.
3. Stale route/delegate registration. Diagnostic callback replacement should
   expose a retired generation or duplicate heartbeat/event callbacks while native
   `/routes/sisters` continues responding. Simultaneous native timeout weakens
   this as a complete explanation.
4. Registration versus socket ownership mismatch. PID/start-time or local socket
   ownership should differ from cached registration. Do not send further requests
   to that endpoint or rediscover a substitute process automatically.

No disposable host was supplied, so no native reproduction/minimization loop or
causal fix was possible. Source doubles and a local CPython HTTP fixture test
the diagnostics only. This intentionally uses the workstream's approved fallback
instead of treating source tests as a native regression test.

Concrete baseline fix proposal
------------------------------

Use the inspected 7.0 release (or the explicitly chosen supported release) as
the comparison baseline. Verify its source and loaded provenance separately;
the disk inspection above establishes neither the active listener's source nor
its native behavior. Do not repeat its already-fixed duplicate-start or
shutdown-order changes.

The remaining proposal for that 7.0 source is explicit `server_close()` socket
cleanup, a documented policy for already accepted workers before retiring their
engine, and visible failed-stop state. Joining only the accept loop does not
drain requests blocked on the shared ExternalEvent. Its serve wrapper's retry
loop must not hide a failed stop or present uncertain ownership as healthy.
Keep failed-stop references and diagnostics rather than deleting registration
or publishing a replacement listener while ownership is uncertain. Evaluate
these changes separately in pyRevit after an unmodified disposable-host trial;
this PR implements the diagnostics and proposal only.

Only for a historical baseline still exhibiting the recorded defects, remove
the second `routes_server.start()` in `activate_server()` and preserve the
constructor's start behavior. Stop admission, call `HTTPServer.shutdown()` from
a different thread than the serve loop, join the sole serve thread, then
`server_close()`. Repeated start must be idempotent or explicitly refused.

Test repeated start/stop, startup failure, accepted-worker drain, reload and
process exit on the recorded IronPython/Revit build and a stock supported
baseline. Change one variable per comparison. This thread did not edit the
sibling pyRevit checkout, monkeypatch its listener, or add another listener.

User-run controlled probe
-------------------------

`scripts/listener_lifecycle/RoutesLifecycleProbe.extension` is a diagnostic
artifact, outside production registration. Its startup does nothing. A human
must deliberately stage it into an isolated disposable host, with no other
execution work running, and click **Lifecycle / Start**. This instruction does
not authorize installation into an existing editing session. No automatic
installation, registration, reload, process restart or listener restart exists.
The probe never accesses Documents, opens transactions, runs submitted code, or
implements a competing target/operation schema.

Buttons:

* **Start** creates one diagnostic ExternalEvent and Idling subscription and one
  GET route. Repeating Start replaces only these diagnostic resources when idle.
* **Capture** writes `lifecycle-evidence.json` within the staged extension and
  records Python listener observations plus actual process/engine provenance.
  Save a separately named copy after each phase; captures replace this local file.
* **Pulse** raises the diagnostic event. Capture again after it executes to
  compare `event_count`. No model work occurs.
* **Replace Probe** detaches the exact old delegate, disposes its idle event,
  expires its diagnostic nonce and creates a fresh diagnostic. Busy events or
  previous cleanup failures refuse replacement. This is callback replacement,
  not proof of actual engine unload or full pyRevit reload.
* **Stop** detaches/disposes only diagnostic resources and removes only its GET
  route. It does not stop native Routes. Never use reload to force cleanup while
  any other runtime has work or an interaction active.

Construction retains the successfully created event before attempting Idling
subscription or initial capture. If either fails, cleanup attempts the retained
delegate/event. Failed cleanup keeps the expired owner and prevents another Start
from creating duplicate resources. Successful cleanup permits a later clean
Start. This is tested containment of Python/native adapter failures, not proof
that a disposed engine permits its delegate to be removed.

GET `/listener_lifecycle_probe/state` has only a `request` argument and returns
copied primitives. Adding `?generation=<old-nonce>` returns HTTP 409 after
replacement. The nonce is diagnostic evidence, not a production `target` handle.
It provides no permission to execute or recover an operation. The collector is
GET-only and local-loopback-only; native siblings/unknown-path responses are
observations, not production receiver identity validation.

Thread observations support both Python 3 `_target` and IronPython 2.7
`_Thread__target` storage, plus direct HTTP server and wrapper RoutesServer
serve-loop targets, including IronPython bound-method `im_self`. Each matched
row records target name and thread name, ID and daemon status.
`unobservable_target_threads` records threads whose target cannot be inspected.
If no target is introspectable, `serve_thread_detection: unavailable` accompanies
a null `observable_serve_threads`; it is not an empty observed worker list.
`serve_thread_observation` marks all results as best effort. An empty observed
list cannot establish that a worker is absent,
an engine is retired, or accepted requests have drained. These private attributes
remain diagnostic details rather than a production ownership contract.

Run each phase from this checkout using the staged evidence's exact PID, start
time and observed socket port; there is no default destination:

```powershell
python -m scripts.listener_lifecycle.collect --port <port> --pid <pid> --started-at '<UTC-start-time>' --phase baseline --output baseline.json
python -m scripts.listener_lifecycle.collect --port <port> --pid <pid> --started-at '<UTC-start-time>' --phase callback-replacement --previous-generation '<old-nonce>' --output replacement.json
```

The Windows collector checks listening socket ownership before and after each
sequential GET, uses a 3-second overall GET deadline (maximum configurable 10),
preserves transport errors/received byte counts, and writes partial receipts.
Wrong owner stops the collector without calling that process. Failure to obtain
OS ownership information fails closed. Receipt files contain local sibling
registration metadata: keep them local and redact unrelated endpoints before
sharing. HTTP success alone never marks native acceptance passed.

The OS query retains every listening row's PID, local address and port. If a
process start time is unreadable, the row contains a null timestamp and an
`ownership_error`; it is not silently dropped from a mixed-owner result. Any
such row prevents another GET. This avoids accepting only the readable rows
while a conflicting socket owner remains unverified.

`listen_socket_count` in the receipt/checks is the maximum observed number of
Listen rows across the before/after queries, separately from
`unique_owner_process_count` (maximum distinct PID count).
Two same-PID rows still count as two, and their local addresses remain visible.
Multiple rows may reflect address-family/bind choices or a duplicate socket;
this is hypothesis evidence, not an established outage cause or a health gate.

The overall deadline covers connection setup, response headers and body. A
socket watchdog interrupts only this diagnostic's connection if reads keep
arriving slowly; previously each socket read could renew the timeout. Bytes
received before deadline expiry remain counted in the failure receipt. Each OS
ownership query has its own 10-second subprocess limit, separate from the GET
budget. There is no Revit execution cancellation or listener shutdown involved.

For an explicitly approved disposable host, record this matrix manually:

| Phase | Required evidence |
| --- | --- |
| Fresh startup / repeated Start | One diagnostic delegate/event; pulse completes once; native siblings and unknown route respond; source provenance and socket owner agree. |
| Callback replacement, at least 3 repetitions | Fresh nonce; old diagnostic rejected; retired counters stop; no duplicate callbacks; native listener remains responsive. |
| Targeted extension reload, at least 3 repetitions | User performs the supported targeted reload while all work is idle. Click Start if registration was cleared. Record actual engine replacement and callback cleanup separately from the Replace button. |
| Full pyRevit reload, at least 3 repetitions | Capture before; user reloads only the disposable host while idle, clicks Start, then captures/collects after. Old runtime/target tokens must expire, no work replay. Preserve native siblings timeouts even if the diagnostic works. |
| Process restart | User closes/restarts disposable Revit normally. Supply new PID/start time; fresh process/runtime identities, no revived operations or stale registrations. |
| Baseline fix comparison | Compare unmodified 7.0 (or the chosen supported release) with one narrowly patched remaining lifecycle gap. Preserve disk source hashes and actually loaded assemblies for both trials; do not infer loaded source from disk hashes. |

If HTTP fails, use Capture and retain the local evidence and timestamped pyRevit
exception log. Do not automatically reload/restart to make the measurement pass.
After a full reload without Stop, cleanup of a retained object from the retired
engine may fail. Capture first, before attempting Start/Replace; if Capture also
fails, preserve the previous evidence file and exception logs. A subsequent
`Previous diagnostic cleanup failed` refusal is an expected fail-closed matrix
result. Start/Replace remain blocked until process restart; restarting the
disposable host is the only supported recovery in this case. Do not clear its
retained owner, retry activation automatically, or restart an editing session.
Stop the diagnostic while idle, then the human can remove its staged directory
and close the disposable host normally. No shared add-in settings need changing.

Operations adapter constraints and release gate
----------------------------------------------

Keep the listener replaceable behind admission/inspection/cancellation handlers;
those handler signatures must stay free of `uiapp`, `uidoc`, and `doc`. The
execution runtime owns a serialized event lane; the native Routes listener is
separate ownership. Prevent overlap with legacy API-context Routes requests.
Stop must expire its runtime and queued work without replay; refuse event
disposal while active/pending. A successful reconnect does not revive expired
target/document handles. Use the identity thread's full IDs and per-call handles;
the diagnostic nonce must never become a parallel identity contract.

Outstanding release gate: demonstrate native listener and event lifecycle through
the disposable matrix on the chosen adapter, including native `/routes/sisters`,
old-token rejection, no duplicate callbacks/listeners, accepted-worker teardown,
and no operation replay. If the baseline fix cannot pass, evaluate a narrowly
owned listener separately with explicit socket/worker/engine ownership tests.
The existing evidence does not yet require that architectural change.

Automated verification
----------------------

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_listener_lifecycle.py -q
```

The tests exercise selected lifecycle source, busy-event replacement refusal,
exact delegate detachment, stale diagnostic generation, cleanup failure,
runner-flag release, copied snapshots, request-only signatures, inert startup,
OS owner mismatch, distinct native/probe health, and a real local HTTP server's
zero-byte timeout. Real Windows tests exercise the embedded PowerShell using a
local Python socket and controlled mixed readable/unreadable process rows.
Parameterized thread tests cover both storage styles, bound-method styles and
serve-loop owners. These are source and CPython diagnostics checks, not native
Revit API, IronPython, engine unload or reload coverage.
