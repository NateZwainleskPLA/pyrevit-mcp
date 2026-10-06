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

Source-supported distinctions
-----------------------------

* Extension lifecycle: the prototype owns its Idling delegate, private
  ExternalEvent, retained runtime, and route handlers. Detaching its callback
  does not own or repair the native Routes server. Retired runtime references
  must remain expired; disposing an active/pending event is unsafe.
* Native listener lifecycle: `RoutesServer.__init__()` calls `start()`;
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

1. Duplicate serve loops or incomplete socket teardown. Removing the second
   start and joining the sole worker before closing the socket should eliminate
   duplicate observable owner threads and teardown socket errors. If native
   endpoints still hang with this invariant, this is not a sufficient fix.
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

Implement in a separately reviewed pyRevit baseline change, after recording an
unmodified trial: remove `routes_server.start()` from `activate_server()` while
preserving the constructor's existing startup behavior. Make subsequent start
attempts explicitly idempotent or reject them with a clear state transition.
Stop admission, call `HTTPServer.shutdown()` from a different thread than the
serve loop, join the sole serve thread, then `server_close()`. Choose an explicit
policy for already accepted workers before retiring their engine; joining only
the accept loop does not drain requests blocked on the shared ExternalEvent.
Keep failed-stop references and diagnostics visible rather than publishing a new
healthy server or deleting its registration while ownership is uncertain.

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

GET `/listener_lifecycle_probe/state` has only a `request` argument and returns
copied primitives. Adding `?generation=<old-nonce>` returns HTTP 409 after
replacement. The nonce is diagnostic evidence, not a production `target` handle.
It provides no permission to execute or recover an operation. The collector is
GET-only and local-loopback-only; native siblings/unknown-path responses are
observations, not production receiver identity validation.

Run each phase from this checkout using the staged evidence's exact PID, start
time and observed socket port; there is no default destination:

```powershell
python -m scripts.listener_lifecycle.collect --port <port> --pid <pid> --started-at '<UTC-start-time>' --phase baseline --output baseline.json
python -m scripts.listener_lifecycle.collect --port <port> --pid <pid> --started-at '<UTC-start-time>' --phase callback-replacement --previous-generation '<old-nonce>' --output replacement.json
```

The Windows collector checks listening socket ownership before and after each
sequential GET, uses a 3-second request timeout (maximum configurable 10),
preserves transport errors/received byte counts, and writes partial receipts.
Wrong owner stops the collector without calling that process. Failure to obtain
OS ownership information fails closed. Receipt files contain local sibling
registration metadata: keep them local and redact unrelated endpoints before
sharing. HTTP success alone never marks native acceptance passed.

For an explicitly approved disposable host, record this matrix manually:

| Phase | Required evidence |
| --- | --- |
| Fresh startup / repeated Start | One diagnostic delegate/event; pulse completes once; native siblings and unknown route respond; source provenance and socket owner agree. |
| Callback replacement, at least 3 repetitions | Fresh nonce; old diagnostic rejected; retired counters stop; no duplicate callbacks; native listener remains responsive. |
| Targeted extension reload, at least 3 repetitions | User performs the supported targeted reload while all work is idle. Click Start if registration was cleared. Record actual engine replacement and callback cleanup separately from the Replace button. |
| Full pyRevit reload, at least 3 repetitions | Capture before; user reloads only the disposable host while idle, clicks Start, then captures/collects after. Old runtime/target tokens must expire, no work replay. Preserve native siblings timeouts even if the diagnostic works. |
| Process restart | User closes/restarts disposable Revit normally. Supply new PID/start time; fresh process/runtime identities, no revived operations or stale registrations. |
| Baseline fix comparison | Repeat the same matrix on one narrowly patched pyRevit baseline. Preserve source hashes and actually loaded assemblies for both trials. |

If HTTP fails, use Capture and retain the local evidence and timestamped pyRevit
exception log. Do not automatically reload/restart to make the measurement pass.
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
uv run --extra test python -m pytest tests/unit/test_listener_lifecycle.py -q
```

The tests exercise selected lifecycle source, busy-event replacement refusal,
exact delegate detachment, stale diagnostic generation, cleanup failure,
runner-flag release, copied snapshots, request-only signatures, inert startup,
OS owner mismatch, distinct native/probe health, and a real local HTTP server's
zero-byte timeout. These are source and CPython diagnostics checks, not native
Revit API, IronPython, engine unload or reload coverage.
