# Application-scoped synchronous execution

Scripts can bootstrap a Revit instance at Home by opening their first document
and continuing in the same API callback. Application scope is explicit. The
existing document tools still require a document handle; omitting or invalidating
that handle never selects application scope.

## Public contract

- `execute_revit_application_code(target, code, description='Application code
  execution', transaction_mode='script', script_name='<revit-script>',
  allow_ui_change=False)`
- `execute_revit_application_script_file(target, file_path,
  description='Application script file execution', transaction_mode='script',
  allow_ui_change=False)`
- `POST /execute_application_code/`: normal script payload plus explicit
  `instance_id`, `runtime_id`, and boolean `allow_ui_change`. Client tools obtain
  these identities from the required target handle on every call.

The route and tools accept no document selector. The receiver rejects even
`document_id: null`; the client router rejects any supplied document handle.
Only `transaction_mode='script'` is supported. Managed mode fails before script
execution because there is no selected document for an automatic transaction.
Application scope opens no automatic transaction or document.

`doc`, `uidoc`, `revit.doc`, and `revit.uidoc` initially remain `None`, including
when the instance already has an active document. `revit.docs` is empty because
it describes the selected binding. Opening a document does not rebind these
values. Keep the returned document or UIDocument in a script variable and pass
it explicitly to helpers and transaction scopes.

`app` and `revit.app` are the `Application` from the supplied, validated
`UIApplication`. `uiapp` and `revit.uiapp` are that supplied `UIApplication` only
with `allow_ui_change=True`; otherwise both are `None`. No host-global context
supplies these properties. This facade is a convenience for arbitrary
IronPython, not a security sandbox: imports, other delegated pyRevit helpers,
raw API calls, and external effects remain the script author's responsibility.

The existing `/execute_code/` route retains explicit selected-document binding,
managed/script transactions, and the requirement that UI execution target the
active document. Its synchronous callback also supplies bound `app` and gated
`uiapp` properties. The private asynchronous lane remains unregistered and
document-scoped; application execution does not change its submission contract.

## Open and continue

Call `execute_revit_application_code(target='r1', code=<script below>)` with a
target obtained from discovery. Paths below are disposable-fixture examples.
Use IronPython 2.7 syntax.

```python
assert doc is None and uidoc is None
new_doc = app.OpenDocumentFile(r'C:\fixtures\bootstrap.rvt')
with execution.transaction(new_doc, 'Set project number'):
    new_doc.ProjectInformation.Number = 'BOOTSTRAP'
    execution.checkpoint()
execution.check('Project number', 'BOOTSTRAP', new_doc.ProjectInformation.Number)
print(new_doc.Title)
assert doc is None  # Keep using new_doc; the initial binding stays unchanged.
```

For UI activation, explicitly set `allow_ui_change=True` on the call:

```python
new_uidoc = uiapp.OpenAndActivateDocument(r'C:\fixtures\bootstrap.rvt')
new_doc = new_uidoc.Document
with execution.transaction(new_doc, 'Set project number'):
    new_doc.ProjectInformation.Number = 'BOOTSTRAP'
print(new_uidoc.ActiveView.Name)
```

For a trial that undoes its contained owned commits:

```python
new_doc = app.OpenDocumentFile(r'C:\fixtures\trial.rvt')
with execution.rollback_scope(new_doc, 'Trial'):
    with execution.transaction(new_doc, 'Trial edit'):
        new_doc.ProjectInformation.Number = 'TRIAL'
# Model edits in the group are rolled back. Opening the document is not undone.
```

File execution reads UTF-8 with an optional BOM on the MCP machine, normalizes
CRLF, and sends code, basename, and SHA-256 of the submitted contents through the
same route. The Revit server never reads a script file. Missing files and invalid
UTF-8 fail locally. The equivalent CLI uses an explicit mutually exclusive scope:

```text
python -m scripts.execute_revit_file --file bootstrap.py --target r1 --application --state <existing-directory.sqlite>
```

`--document d1` continues to select document scope. Neither omitting both scope
options nor specifying both is accepted. Application mode rejects
`--transaction-mode managed`. `--allow-ui-change` grants UI access in either
scope. The state file must be the existing persistent directory shared with the
MCP server, or supplied through `REVIT_TARGET_STATE`.

## Identity and safety

Client revalidation and receiver instance/runtime validation precede native
work. The receiver uses a real `uiapp` callback signature for API dispatch.
Stale or foreign identities never admit the script. Successful responses must
confirm the original addressed identities in `actual_target`; opening or
activating a document does not replace that confirmation. Single-attempt
transport is shared; uncertain mutations are never automatically replayed.

Application execution uses the same AppDomain-retained process safety guard as
all synchronous mutations. A blocked process rejects the call before native
access. Startup initialization remains strict, retained private owners exclude
registration, and disabled startup registers request-only rejection handlers.
Adding the route to the shared policy also adds it to the private lane's required
legacy-exclusion receipt. Reload never clears safety and no recovery/reset path
is added.

Before admission, the receiver checks open document validity and
`IsModifiable`. An existing foreign open transaction causes rejection without
running the script or cleaning that transaction. The execution context takes an
API-context document snapshot before script execution and another during
cleanup. It checks the union of initially open documents, documents used by
owned scopes, and documents still open after the script. Thus `doc=None` does
not skip checks, and a raw transaction left open on a newly opened document is
reported unsafe. A failure to inspect final document state is also unsafe.
The receiver independently checks final open documents as a backstop when a
native handler fails outside the script runner.
Only connector-owned scopes are unwound/disposed; foreign transactions are not
enumerated, rolled back, or disposed.

Closed secondary/helper documents are accepted when no owned scope is
unresolved. Owned transaction receipts survive closing. Wrapper comparison uses
the existing `Equals` handling for scope parenting and deduplication. Known
surviving owned commits remain `effects='committed'`; an owned rollback is
reported separately as `owned_effects='rolled_back'`, while overall raw and
external effects remain conservatively `unknown`. Opening/closing files and UI
changes are not undone by transaction rollback. Native state properties do not
prove that every raw transaction/group or external effect settled; there is no
foreign-transaction recovery guarantee.

Responses share bounded stdout/stderr capture, error/partial-output envelopes,
basename/line diagnostics, conversion helpers, checks, owned transaction
receipts, and cooperative checkpoints. Synchronous HTTP calls offer no separate
cancel operation; owner-supplied cancellation checks work through the shared
execution seam and do not enable the private lane.

`opened_documents` contains descriptors for newly observed documents still open
after the call, including error responses. Their `document_id` values come from
a fresh API-context refresh of the existing `TargetRegistry`. Documents opened
and closed within the call have no live descriptor. These UUID tokens are not
the client's `dN` handles: call `get_revit_target_metadata(target)` or discovery
afterward to obtain handles through the existing `TargetDirectory`, then use
the normal document-scoped tools. No second identity scheme is created.

## Verification and native proof requirements

Controlled tests exercise real routing, registry/directory, receiver and
execution seams with native doubles: Home bootstrap, explicit target-only
schemas, follow-up document selection, UI permission, managed-mode rejection,
stale/foreign identities, file transport, raw leaks, owned cleanup/rollback,
closed helpers, output bounds, cancellation, guard retention and startup/private
exclusion. These tests do not call a live Revit process.

Full-suite validation uses the existing read-only Python 3.13.14/MCP 1.30.0 venv
at `D:/CodexWorktrees/pyrevit-mcp-integration-revit-2024-2026/.venv/Scripts/python.exe`,
with this checkout as cwd and `PYTHONPATH`. The five changed native modules also
compile with the installed pyRevit IronPython 2.7.12 engine in a separate
PowerShell process, without importing Revit or evaluating the modules. Syntax
compilation does not establish Revit API behavior, CLR wrapper lifetime, or
native failure-processing correctness.

Native proof requires explicitly supplied disposable Revit fixtures and a
freshly loaded connector on each supported host. Validate Home-to-DB-open and
Home-to-UI-activation, existing-active-document binding, registry handles after
open/close, owned edits and rollback, intentionally closed family helpers,
wrapper aliases, stdout/stderr and script diagnostics. Raw leaked/pending-scope
tests require a separate disposable process: confirm the shared guard blocks
subsequent mutations and survives route reload without reset. Also prove
request-only disabled registration and private-owner startup rejection. Dialogs,
worksharing, detach/audit options, file locks and failures during native open are
host-dependent and remain unverified here. Existing open Revit processes and
deployed settings were not used or changed for this implementation.
