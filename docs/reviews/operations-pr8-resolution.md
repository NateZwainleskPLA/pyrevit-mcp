# Operations PR8 review corrections

Original scoped review: `147f432ac17caf133ae26e6ad2dbcfad43fc99fd` on
`review/opus-pr-8`, pinned routing base `e1fb74b` to operations head `c2b0ef3`.
Verdict was changes requested. The original reproduction tests assert defective
behavior; `tests/unit/test_operation_review_regressions.py` instead asserts the
corrected behavior using actual registry, journal, runner and shared safety
objects with inert host doubles. No native acceptance is implied.

- **F1 resolved.** Generation expiry leaves callback-owned running/waiting
  records finalizable, marks their generation expired and cancels queued work
  with no effects. Completion is still journaled after orderly stop. Runtime
  regressions call `stop()` during the callback, check both active states,
  preserve committed effects and require that the SAME shared safety object
  remains safe. Expired live inspection still fails; archived inspection remains
  local. This extends the independent stop fix `1be1fb9` rather than replacing
  known outcomes with a fictitious restart.
- **F2 resolved.** Pre-write record/capacity limits raise `JournalCapacityError`
  and reject admission without a durability latch. Other running and queued
  work completes normally. Actual temp-write/replace/sync failures retain the
  existing uncertainty/blocking semantics. Capacity-pressure reclamation is
  bounded and only removes known terminal, other-generation receipts older
  than seven days (configurable). Unknown effects, unfinished records and
  current-generation dedup tombstones survive. Protected evidence can still
  fill the archive; admission then rejects safely until explicit operator
  reconciliation while the writer is stopped.
- **F3 resolved.** Host observation computes locally, then publishes one
  `(known, safe)` tuple. HTTP admission sees the last complete observation
  during a healthy scan; enumeration failure publishes unknown/unsafe before
  propagating. API execution always revalidates freshly. Deterministic blocked
  iterator and failure cases cover both behaviors.
- **F4 resolved.** Store construction rejects a journal limit smaller than the
  result limit plus a 32 KiB envelope reserve. Admission bounds primitive
  identity metadata to one quarter of that reserve, leaving room for events,
  expiry/cancellation flags and bounded journal diagnostics. Boundary tests
  verify successful truncated completion and early rejection without disk work.
- **F5 optional, retained conservative behavior.** Restart load continues to
  report unfinished records as unknown, including admission-only records. A
  stale/restored file cannot prove native storage history; recovery never replays
  it. This is documented deliberately. Orderly in-process shutdown now reports
  provably queued work precisely as canceled/none. Reviewer agreement on this
  optional disposition is requested with focused confirmation.
- **F6 maintainability resolved; schema enhancement deferred.** Both factory
  layers use one exclusion-receipt validator/required-route calculation. A
  future unforgeable composition receipt belongs to the routing owner and is
  not introduced as another identity or registration schema. The receipt is
  an integration assertion; the real startup guard and retained lease remain
  mandatory, and listener/native evidence still gates adoption.

Final publication must use the UPDATED canonical Origin routing parent and
inherit its published identity/transport/execution corrections. Only owned
operation corrections, tests and documentation are replayed; isolated copies
of foundation patches are test evidence, not publication history. Original
build refs and peer worktrees remain untouched. Deployed integration checkout,
Revit sessions/models, add-in settings and shared safety state are not changed.

Native pending: callback thread/engine/accepted-worker lifetime, real transaction
effects/UI, and journal durability. The installed pyRevit evidence in the review
was IronPython 3.4.2, using `os.replace`/`os.fsync`; the compatibility fallback
for older IronPython is not proof of that native path. No disposable native
fixture was supplied.
