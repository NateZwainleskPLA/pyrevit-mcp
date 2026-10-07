# Routing PR #7 review and canonical composition

Recorded October 7, 2026. This supersedes the historical dependency notes in
`f40a77f`, `e373a79`, `cda4aeb` and `f5d78c9`. The user now authorizes publishing
completed corrections to Origin PR #7. The original Opus report is now complete:
**approve after fixes**, against pinned `e0b5cd6..e1fb74b`, with 328 passing tests,
15 native skips and eight repros asserting defective behavior. All six findings
are independently confirmed fixed in immutable candidate `bdf4b18` by the same
ordinary reviewer thread. No remaining objections to the six findings were
reported; native acceptance is not implied.

## Canonical dependencies consumed

Local aggregation `pr/routing-foundations` is
`a9f38fc60e3cbbd0aaed4c9febe8dfdb93e622dd`. It merges actual published canonical
parents, preserving ancestry instead of duplicating dependency patches:

| Origin PR | Canonical head |
| --- | --- |
| [Transport #2](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/2) | `223375dedc2c1da283b4f0a2c27786a3b9a4b974` |
| [Status #1](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/1), based on #2 | `e6de407396ca21e2e7ca0a50132917d2ab18546f` |
| [Identity #5](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/5), based on #1 | `396e8cbeaa116c57637f0a2262e54d6d4aacc244` |
| [Execution #3](https://github.com/NateZwainleskPLA/pyrevit-mcp/pull/3) | `deba1b68d96b4c09d79b2004386bb0f97f4888a4` |

Foundation original reviews were completed and actionable corrections were
owner-tested. Transport follow-up is independently **APPROVE**, report
`078c2707f7d2ce3e3466a764df37a099ea13294b`; other foundation follow-ups are separate
and not implied by that approval. Canonical parent synchronization from the
earlier `30ee4906` changes only inherited transport review documentation; source
and tests are identical, so its 354-unit-test evidence remains applicable.

Historical isolated status composition `72f491968c371923e3c3a973b772611c794c2df0`
(201 owner-reported tests) includes strict-health reconciliation
`2885aeb3fc7fcfe03a9ab6acca9a0318547b41f0` (182 tests and an 18-case HTTP matrix).
Neither replay branch is imported. Canonical status contains the completed
behavior over its actual transport parent.

## Owned corrections to saved review repros

Local `3787bb2d704aa8e7149815b20cd1c4b40cfa61c1`, completed by
`59e256acc8ece7149773ab98c1df202eea1c580b`, addresses the eight saved repros across
four groups. Their assertions are inverted in owned regression tests, expanded
with failure matrices and API/CLI boundaries:

- **Handshake failures escaped the structured interface.** Connection refusal,
  timeout and unsuccessful metadata HTTP responses now return
  `target_revalidation_failed`, preserving available handshake status, body,
  headers and exception type. The result states that execution was not sent and
  sets `mutation_outcome_unknown=False`. No directed request, retry or target
  substitution occurs. Direct `resolve` raises chained `target_unreachable` for
  HTTP, OS and JSON/value failures; existing `IdentityError` objects/codes pass
  through unchanged. `call` preserves structured underlying handshake evidence.
- **Operation confirmation could be disabled by request shape.** Missing IDs
  could accept another operation's receipt; GET inspection ignored its query ID.
  All operation endpoints now require POST and a nonempty body `operation_id`
  before handshake/transport, returning `missing_operation` for invalid method
  or ID. GET with an ID is also rejected. Confirmation always compares the body
  ID and rejects a foreign receipt. UUID validation and stored ownership remain operations'
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
  load. A blocked primitive snapshot selects a local exception; the handler and
  prior-engine `require_safe` are not called. Unsafe state is never reset.

`test_routing_review_contracts.py` covers these groups through the router, MCP,
file CLI and receiver, including a separately loaded prior-module safety guard.
Connection refusal, timeout, HTTP 503, actual invalid JSON and OS errors are
tested at direct resolution, router, main, inline/file tools and CLI boundaries.

`bdf4b18aa6d9e77f7b08ceedf3669e0655d8def6` resolves the remaining findings:
open/close descriptions require explicit UI permission, close is inactive-only,
and callers rediscover the opened document handle. Save/sync descriptions also
say specified document. Loopback-only local launch verification is documented
in the tool, result and contract. A matching PID/start/version at a LAN endpoint
remains bounded/unverified with no handle or final revalidation; remote PID
coincidence never proves local child ownership. Finding 6's documentation option
is deliberately used, rather than weakening OS ownership evidence.

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
481 passed
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
481 passed, 15 skipped
.\.venv\Scripts\python.exe -m compileall -q main.py tools scripts revit_mcp
passed
git diff --check
passed
```

The aggregation separately passed 354 unit tests; its latest parent sync is
documentation-only. The corrected source candidate passed 481 tests, including
87 focused review/router/receiver/launch cases. Seven actual execution
composition cases and 26 identity review cases also passed together. Controlled
doubles and Python 3 compilation do not establish native/IronPython behavior.

PR #7 keeps base `pr/routing-foundations` and native GH-Stacks lineage to PR #8.
The standing user authorization permits publishing completed own corrections.
Base/head publish together after final checks; pushing only the base would
distort the child diff. No peer-ref rewrite, duplicate prerequisite replay or
proposal import is needed. Original build refs remain intact.

Shared C2 is an honest-caller composition contract: the exclusion receipt is a
primitive dictionary, not an unforgeable security proof. Production composition
must supply the real guarded startup receipt. The startup owner lock and retained
factory lease enforce exclusion; routing adds no competing receipt/owner schema.
Shared prior-engine operations exception handling remains operations-owned.

## Independent corrected-candidate confirmation

The existing Opus reviewer inspected a read-only `git archive` of
`bdf4b18aa6d9e77f7b08ceedf3669e0655d8def6`, verified imports from that extraction,
and reported **all six findings fixed, no remaining objections**. Its full suite
passed 481 tests with 15 native skips; compileall and the candidate diff check
passed. All eight original defective-behavior repros failed as expected; ten new
positive confirmation tests passed. These confirm typed/chained resolution,
structured 503/no-delivery evidence, unaltered stale identities, MCP/file/CLI
results, prior-engine guard rejection, POST/ID admission, foreign receipt
rejection, route-aware ambiguity and corrected descriptions/messages.

Evidence is in the review thread's `docs/reviews/opus-pr-7.md` and
`docs/reviews/opus-pr-7-repro/test_confirm_bdf4b18.py`. Later canonical-parent
and honest-caller/review-state documentation commits leave production/tests
byte-identical to the confirmed candidate. The reviewer explicitly did not
review the canonical foundation composition as a new diff, and C1-C3 remain
coordinator/owner contracts. No broader approval is inferred.

No disposable fixture was supplied. Native threading, UI, CLR lifetime,
listener reload/disposal and launch remain pending. Historical native tests
are skipped; their legacy harness needs adaptation before use. No live session,
model, setting or endpoint protection changed; no merge/deployment/private
activation occurred. The flagged `uvx` executable was not invoked.
