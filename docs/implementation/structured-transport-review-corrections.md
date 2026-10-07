# Structured transport review corrections

These are local corrections to Origin PR #2's published transport head
`e698a7eb1b8f083ed884ee694b2af284462d2934`, following the Opus review at local
commit `5280c0f`. No correction has been pushed or posted to GitHub. The original
build branch remains preserved. No native Revit session was contacted.

## Findings addressed

### M1: native pyRevit exception envelopes

A JSON `exception` object with a `message` is recognized as a receiver error.
The receiver body is preserved unchanged. Readable output includes ERROR DETAILS,
source, message, embedded traceback lines, and remaining identity/effects fields.
All received non-2xx responses start with `Error:`; native handler HTTP 408 is
labelled a pyRevit route handler exception, rather than the standard HTTP timeout
phrase. It is distinct from a client-side timeout failure. Plain dictionary
envelopes also receive error framing, including when a conflicting success or
recoverable status is supplied.

Local structured results without an HTTP status render their body without an
invented HTTP prefix. This converges with routing's local preflight formatter
guard; no routing or identity schema is introduced.

Regression tests reproduced the missing classification/prefix before the fix.
Tests cover HTTP 408 and 500 over GET and POST, full structured bodies, compatible
views and plain dictionary formatting. The broader non-2xx prefix tests include
302, 404, 409 and 503.

### M2: legacy launch transport readiness

Legacy polling examines `response.transport_result`. It requires received JSON
as an object, rejects receiver exceptions, and accepts HTTP 200 or a legacy HTTP
503 explicitly marked with `api_name == "revit_mcp"`. Foreign 4xx/5xx JSON,
unmarked 503, non-JSON failures and bare dictionary/string values do not establish
readiness. Tests exercise actual `request_revit`/`httpx.MockTransport` responses,
including deceptive 4xx/5xx bodies claiming connector liveness.

This local correction leaves `/status/` unchanged. The coordinator is composing
completed status commit `2eb54f6bf895e5ee5b8334e76107b764fdfb14da`, which switches
legacy polling to the separate raw `/health/` registrar. During that composition,
retain `/health/`, its document-free semantics and no endpoint fallback, and
replace the legacy predicate with **received JSON object + HTTP 200 +
`api_name == "revit_mcp"` + `status == "alive"`**. Do not retain the legacy 503
allowance for `/health/`. Adapt these tests' `/status/` assertions accordingly.
Modern metadata/full-identity readiness and TargetedAPI routing remain owned by
routing. Conflict guidance and the completed local M2 hash were sent to the
coordinator and status owner.

### L1: request-build errors

The transport builds a request before sending it. Invalid URLs and request-build
TypeError/ValueError failures become `request_error` with known pre-delivery
status and `mutation_outcome_unknown == False`. Tests verify invalid ports,
unserializable payload objects and non-JSON numeric values make zero send
attempts. Existing tool-facing readable error strings are retained.

### L2: timeout duration and conditional effects wording

Timeout results expose `timeout_seconds`, taken from the effective timeout for
the failed connect/read/write/pool phase. Formatting restores the duration when
available. Delivery-ambiguous failures say the request may still be running and
"If this request changes the model, verify model state before resubmitting."
They neither label every POST a mutation nor require a nonexistent operation
inspection interface. This does not change the conservative internal ambiguity
flag or add endpoint classification.

### L3: empty successful acknowledgement

An empty or whitespace-only 2xx body is `kind == "empty_response"`, with no
failure, no JSON receipt and no transport delivery ambiguity. Raw HTTP evidence
is retained and text says "Empty response received." This acknowledgement does
not establish completed execution, committed effects, rollback or deduplication.
`body is None` with `json_received == False` remains distinct from JSON null.
Empty non-2xx replies still receive decoding-failure/error treatment.

### L4: injected-client timeout policy

Omitted timeout uses `httpx.USE_CLIENT_DEFAULT` for an injected client. An owned
client retains the 30-second default. Explicit timeouts, including disabled
timeouts (`None`), override the client policy. Tests cover inheritance, override,
disabled timeouts and phase-specific duration reporting. Sending also explicitly
disables redirects, so an injected client's redirect policy cannot replay a POST.
Transport does not retry any request.

## Informational items left unchanged

- `trust_env` proxy behavior predates this change. Altering user proxy policy is
  outside these corrections; no environment or proxy settings were changed.
- Raw bytes, response text and decoded image JSON still coexist. This retention
  preserves the diagnostic envelope; memory optimization is deferred and would
  require a separate output-retention design and realistic size checks.

## Validation and limits

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit -q -p no:cacheprovider
# 166 passed

.\.venv\Scripts\python.exe C:\Users\NateZwainlesk\.t3\worktrees\pyrevit-mcp\review-opus-pr-2\docs\reviews\repro_opus_pr2.py
# Corrected M1/L1/L2/L3/L4 behavior; foreign/unmarked/error liveness replies rejected

git diff --check
# Passed
```

Tests use controlled HTTP doubles, not a running native host. The pyRevit
exception-envelope and callback-body facts were supplied by the source-only
review. The repro named "503 revit_mcp unhealthy" lacks `api_name`, so it is now
correctly rejected; a connector-marked 503 is covered separately in unit tests.
No disposable native fixture was supplied. Native transactions/effects,
listener reload, busy-host API dispatch and receiver identity acceptance remain
unverified. No extension, add-in settings or user model was changed.
