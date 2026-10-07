# Proposed title

Add explicit application-scoped synchronous Revit script execution

# Proposed description

Document-scoped execution cannot open the first document when Revit is at Home.
Add `execute_revit_application_code` and
`execute_revit_application_script_file`, backed by
`POST /execute_application_code/`, so a script can open a DB or UI document and
continue within the same API callback. Existing document tools still require
their document handle.

Application execution requires an explicit target and accepts no document
selector. Initial `doc`/`uidoc` stay `None` even when another document is active.
Scripts use the bound `app.OpenDocumentFile(...)`, or the supplied
`uiapp.OpenAndActivateDocument(...)` with `allow_ui_change=True`, and keep the
returned document in a local variable. There is no automatic transaction;
managed mode is rejected. Scripts can use `execution.transaction(new_doc, name)`
and rollback scopes. The local-file tool and explicit CLI `--application` option
reuse UTF-8/BOM reading, CRLF normalization, basename/hash submission and the
single-attempt transport.

Target revalidation, original `actual_target` confirmation, API-context dispatch
and the AppDomain-retained process safety guard cover the new route. Check
document state before execution and after owned cleanup, including initially
open and newly opened documents. A receiver-level check also catches leaks when
a native handler fails outside the runner. Raw transactions are never cleaned;
unsafe or unreadable final state blocks subsequent mutations. Settled owned
scopes and intentionally closed helpers retain the existing `Equals` and
closed-helper behavior, known commit receipts and conservative unknown raw
effects. Fresh `opened_documents` descriptors use the existing registry; normal
metadata/discovery assigns client document handles.

The route participates in disabled/private-owner startup exclusion and the
private lane's required exclusion receipt. The asynchronous lane stays
unregistered, opt-in and document-scoped. The facade supplies context for
arbitrary IronPython; it is not a security sandbox.

Validation:

- Full suite: **690 passed, 15 skipped**, using the existing read-only Python
  3.13.14/MCP 1.30.0 venv with this checkout as cwd and `PYTHONPATH`.
- Controlled red/green tests at routing, receiver and execution seams; real
  registry/directory bootstrap and follow-up document selection; actual MCP
  schemas; inline/file payloads and original identity confirmation; UI and
  managed-mode rejection; raw leaks, owned cleanup/rollback, closed helpers,
  output/checkpoints, shared guard retention and startup/private exclusion.
- All five changed native modules compile with installed pyRevit IronPython
  **2.7.12**, in a separate PowerShell process without importing/evaluating Revit.
- `git diff --check` passes.

Native proof remains pending: explicitly supplied disposable hosts must verify
Home bootstrap, UI activation, CLR document aliases/lifetime, open/close identity,
owned rollback/closed helpers, native pending failure processing and guard
retention. Fifteen fixture-dependent tests stay skipped. No live Revit work,
deployment, restart, safety reset, settings/AV changes, venv mutation, push or PR
publication was performed. This local branch is based exactly on completed
integration `2a0ceb0748a92aca9425940d19a9851e590312fc`.

Contract, examples and fixture requirements:
[`docs/implementation/application-scoped-execution.md`](../implementation/application-scoped-execution.md).
