# Routing PR #7 review and canonical composition

Recorded October 7, 2026. This supersedes the historical dependency notes in
`f40a77f`, `e373a79`, `cda4aeb` and `f5d78c9`. The user now authorizes publishing
completed corrections to Origin PR #7. Its original Opus review is still
unfinished because of the provider's account-wide usage cap. Publication awaits
that required review; no independent reapproval or native acceptance is claimed.

## Canonical dependencies consumed

Local aggregation `pr/routing-foundations` is
`30ee4906cd8e76dc91562974d624c10a17ac4431`. It merges actual published canonical
parents, preserving ancestry instead of duplicating dependency patches:

| Origin PR | Canonical head |
| --- | --- |
| [Transport #2](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/2) | `d287d4338e1a467c6577d1496e4fd25fa5d6e752` |
| [Status #1](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/1), based on #2 | `2f1ba45fe6a91205f18120c414e6efb6a289f021` |
| [Identity #5](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/5), based on #1 | `511b6dc8b46aa8692d283706e03b7b471f1991b2` |
| [Execution #3](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/3) | `deba1b68d96b4c09d79b2004386bb0f97f4888a4` |

Foundation original reviews were completed and actionable corrections were
owner-tested; independent follow-up confirmation remains pending the account
cap. PR #7's unfinished original review is a separate gate.

Historical isolated status composition `72f491968c371923e3c3a973b772611c794c2df0`
(201 owner-reported tests) includes strict-health reconciliation
`2885aeb3fc7fcfe03a9ab6acca9a0318547b41f0` (182 tests and an 18-case HTTP matrix).
Neither replay branch is imported. Canonical status contains the completed
behavior over its actual transport parent.

## Owned corrections to saved review repros

Local `3787bb2d704aa8e7149815b20cd1c4b40cfa61c1` addresses four saved PR #7
repro groups. These are evidence, not a completed formal report:

- **Handshake failures escaped the structured interface.** Connection refusal,
  timeout and unsuccessful metadata HTTP responses now return
  `target_revalidation_failed`, preserving available handshake status, body,
  headers and exception type. The result states that execution was not sent and
  sets `mutation_outcome_unknown=False`. No directed request, retry or target
  substitution occurs. Typed identity failures keep their existing fail-closed
  path.
- **Operation confirmation could be disabled by request shape.** Missing IDs
  could accept another operation's receipt; GET inspection ignored its query ID.
  All operation endpoints now require a nonempty `operation_id` before any
  handshake/transport. Confirmation reads GET parameters or the POST body and
  rejects a foreign ID. UUID validation and stored ownership remain operations'
  responsibility. Inspect/cancel stay runtime-scoped, preserving historical
  document provenance without requiring a live document.
- **Read-only POST failures looked like uncertain mutations.** Known queries
  and inspection clear the delivery-ambiguity mutation flag. Mutations,
  submission/cancellation and explicitly permitted unknown routes stay
  conservative. Receiver bodies/effects remain intact. Existing transport
  failures, including invalid JSON, are not replaced by identity confirmation.
  A false ambiguity flag does not prove no effects.
- **A retained prior-engine guard exception had the wrong contract.** Any guard
  rejection before admission returns HTTP 409 `mutation_blocked`, `effects=none`
  and actual identity, even if its exception class belongs to a previous module
  load. The handler never runs and the retained unsafe state is never reset.

`test_routing_review_contracts.py` covers these groups through the router, MCP,
file CLI and receiver, including a separately loaded prior-module safety guard.

## Composition behavior retained and verified

`b7609f3` composes canonical status/transport/execution corrections; `385a57c`
composes canonical identity and actual receiver/execution regression tests.

Targeted and disabled startup retain **strict** `initialize_identity` under
`startup_owner_guard`, before replacement/expiration. They never call the
legacy-only degraded initializer. Controlled early/partial failures propagate
without model/status registration or raw health. Existing retained-owner tests
reject before identity work and preserve the exact shared guard/lease. Only
successful guarded disabled startup emits complete exclusion/reload evidence.

The aggregation retains legacy health tests for its own legacy composition.
Routing omits the raw registrar and replaces obsolete legacy waiter tests with
`test_launch_metadata_transport.py`. Modern launch still uses cached
`/metadata/`, strict successful snapshot validation, exact spawned child
PID/start/version, initialized documents and final full-ID revalidation. Its
real HTTP matrix rejects degraded 503, unrelated JSON, malformed/non-object
responses and error envelopes. Health liveness is never identity/model readiness.

`test_routing_execution_composition.py` uses the actual registry, receiver and
`execute_payload` with controlled native doubles. Inactive work and default
`Transaction`/`TransactionGroup` helpers bind to the requested document. These
pyRevit helpers remain **untracked**; only execution-owned scopes prove owned
effects. Gated views/assignment use the supplied eligible UIDocument, never the
global host UIDocument. Inactive UI work rejects before execution. An unsafe
result latches the same guard used by subsequent save/execution; queries remain
available.

Fresh live resolution excludes links even after a previously valid snapshot.
The additive family descriptor is descriptive: its old/defaulted value cannot
override resolved native properties or create a blanket family-document ban.
Identity owns allocation, schema, native comparison and exact delegate cleanup.

## Validation and remaining gates

Existing `.venv` Python, after complete canonical composition:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit -q -p no:cacheprovider
446 passed
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
446 passed, 15 skipped
.\.venv\Scripts\python.exe -m compileall -q main.py tools scripts revit_mcp
passed
git diff --check
passed
```

The aggregation separately passed 354 unit tests. Seven actual execution
composition cases and 26 identity review cases passed together. Controlled
doubles and Python 3 compilation do not establish native/IronPython behavior.

PR #7 keeps base `pr/routing-foundations` and native GH-Stacks lineage to PR #8.
The follow-up is not yet pushed. Base/head will publish together after the
original review and final checks; pushing only the base would distort the child
diff. No peer-ref rewrite, duplicate prerequisite replay or proposal import is
needed. Original build refs remain intact.

No disposable fixture was supplied. Native threading, UI, CLR lifetime,
listener reload/disposal and launch remain pending. Historical native tests
are skipped; their legacy harness needs adaptation before use. No live session,
model, setting or endpoint protection changed; no merge/deployment/private
activation occurred. The flagged `uvx` executable was not invoked.
