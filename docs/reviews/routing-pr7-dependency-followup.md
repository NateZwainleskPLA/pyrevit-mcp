# Routing PR #7: legacy readiness dependency follow-up

Recorded October 7, 2026. This is a local-only review note. No remote PR,
remote publication branch, Revit session or configuration is changed by this follow-up.
The published routing head remains `e1fb74b876fafeecff11cae4ac8b6d9c1af29b25`.

## Dependency findings

The coordinator reported that the Opus review of transport PR #2 recommends
approval after M1 and has no High findings. Its M2 finding identifies a legacy
launch hazard: dictionary compatibility views can cause foreign HTTP 4xx JSON
to satisfy a waiter that accepts `isinstance(response, dict)`. The transport
owner is preparing local-only classification using the retained
`transport_result`, without adding target routing. Report reference supplied by
the coordinator: `review-opus-pr-2/docs/reviews/opus-pr-2.md`, local `5280c0f`.
This note does not claim independent review of that report or completion of
the transport correction.

The status owner separately completed local-only commit
`2eb54f6bf895e5ee5b8334e76107b764fdfb14da`. It keeps `/status/` in document API
context and adds a separate `register_liveness_routes(api)` for request-worker
GET `/health/`. The legacy waiter probes that primitive listener endpoint.
Neither that status commit nor unfinished transport corrections are imported
into routing by this follow-up.

## Modern routing checks retained

The published modern launch implementation already avoids the legacy waiter:

- `tools.target_discovery.metadata_handshake` requests cached `/metadata/`,
  requires HTTP 200, decodes JSON and validates the identity snapshot. Error
  dictionaries and redirects are not successful metadata handshakes.
- Launch retains `Popen` and matches a local loopback target to its exact spawned
  PID, process-start timestamp and requested Revit version.
- A valid target and initialized document snapshot (`documents_known`) are
  required; `runtime_available=False` rejects the candidate.
- Final directory revalidation must preserve full instance/runtime IDs and
  process lifetime. A superseded generation and an exited child cannot satisfy
  readiness.
- Discovery/revalidation is bounded by the launch deadline. Generic HTTP
  status dictionaries do not establish readiness, and no execution retry or
  alternative target is selected.

These checks establish verified registration for the launched destination.
They do not prove modal clearance, current document usability, native execution
availability, safe listener reload or CLR engine retention.

## Eventual integration requirements

When completed dependency corrections are authorized for integration, reconcile
the legacy startup/launch/test overlaps explicitly. Retain modern metadata
discovery, exact child matching, initialized snapshot checks and final full-ID
revalidation. Do not restore dictionary-type acceptance or use `/health/` as
identity or model execution readiness.

Keep `register_status_routes(targeted_api)` registering only `/status/`. Omit
the legacy raw liveness registrar from targeted/disabled startup. Passing
`/health/` through `TargetedAPI` currently rejects it as unknown; adding a normal
policy would give it a real `uiapp` argument and return it to API-context
dispatch. Any later protected liveness endpoint needs a separately reviewed
request-only full-instance/runtime-ID guard, not a new identity schema.

Status's local health change and transport's local legacy response classification
must be reconciled together where their legacy waiter hunks overlap. Neither
correction weakens directed-call identity/document validation or the retained
private-owner startup exclusion. Until then the published foundation base and
routing PR remain unchanged.

## Validation and limits

The existing launch/discovery regression cases were rerun for this follow-up:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_wait_for_revit.py tests/unit/test_launch_identity.py tests/unit/test_target_discovery.py -q
26 passed in 0.55s
```

The diff check passed. These cases cover generic HTTP responses, another process,
reused lifetime, wrong
version, remote PID coincidence, uninitialized snapshots, process exit and
generation changes during final revalidation. Only this note changes; no new
routing implementation or speculative test is added.

No disposable native fixture was supplied. Native modal, API dispatch, listener
lifetime and actual launch acceptance remain pending. No push, remote PR edit,
merge or deployment is authorized by this local review follow-up.

## Pending identity review corrections

The coordinator also reported Opus PR #5 review `f0deafb` requesting changes:
invalid/wildcard advertised endpoints can abort registration (F1), stale PID
records can veto a live same-port instance (F2), rejected observations alter
in-memory verification despite SQL rollback (F3), linked/family document
classification is incomplete (F4), process timestamps depend on locale (F5),
and expiration failure can skip delegate cleanup (F6). Report reference supplied
by the coordinator: `review-opus-pr-5/docs/reviews/opus-pr-5.md`. These are pending
identity-owner corrections; this note does not claim they are resolved or import
their implementation.

Routing's later integration must reconcile F1c explicitly. The identity PR's
legacy-only startup may preserve independent legacy routes when identity is
unavailable. Targeted and disabled startup must continue requiring full-ID
validation, with no legacy fallback and no `TargetedAPI` registration of
`/health/`. Any degraded metadata registrar must stay request-only and cause
discovery/revalidation to fail, rather than fabricate target identity. Preserve
`startup_owner_guard` before identity initialization, registration or expiration.
Current targeted startup propagates identity initialization failures; it does
not continue into legacy handler registration.

F4 must exclude linked documents during fresh live resolution, not just cached
discovery. The identity owner owns `TargetRegistry.resolve_document`; routing
will consume the completed correction rather than add a second registry or
document schema. Valid family documents should be classified and handled by
each tool's supported semantics, without an accidental blanket family ban.

The identity owner was asked for the completed local contract/hash, including
degraded-metadata composition and fresh linked-document resolution. Integration
waits for that completed dependency. No source rewrite, deployment or remote
publication is included in this note.
