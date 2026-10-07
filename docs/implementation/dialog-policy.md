Optional dialog policy contract
===============================

`revit_mcp/dialog_policy.py` is an independent primitive. Importing it installs
nothing; `startup.py` is unchanged. `DialogPolicy()` leaves every dialog alone.
There are **no shipped supported Revit dialog cases**. The offline tests use
synthetic IDs, builds and actions; they do not establish native support.

Upstream review
---------------

Reviewed the actual [upstream #63 diff](https://github.com/mcp-servers-for-revit/mcp-server-for-revit-python/pull/63)
on October 5, 2026, while OPEN at
`9a0ebe828d71b8bc259ee58f4419a0d0c58f311a`. Its startup handler searches a combined
ID/message/help string for several phrases, including `could not find`, falls
back to OK when the first override throws, and subscribes unconditionally.
None of that suppression code is adopted here. The PR is linked to this T3 thread
as reviewed evidence, not published implementation.

Autodesk's [DialogBoxShowing event documentation](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/cb46ea4c-2b80-0ec2-063f-dda6f662948a.htm)
explains the distinct event argument types, prohibits document changes in the
callback, and shows subscription/removal. [OverrideResult](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/49ba2725-74c9-02b3-4321-eac1f2295bd3.htm)
returns whether the code was accepted; permitted values depend on actual dialog
buttons. These generic API facts do not establish the exact Desktop Connector
or unresolved-reference IDs/actions in Revit 2025. Those cases remain unsupported
until authoritative case-specific evidence and disposable-host validation exist.

Configuration and receipts
--------------------------

Construct `DialogPolicy(catalog=None, responses=None, enabled=False)` from a
trusted, reviewed catalog. Catalog structure:

```python
catalog[exact_dialog_id] = {
    "event_type": exact_dotnet_event_type_full_name,
    "revit_builds": [exact_verified_version_build_string],
    "actions": {
        action_name: {
            "result_code": verified_nonzero_int32,
            "description": documented_button_meaning_and_consequences,
            "evidence": authoritative_case_reference_and_fixture_validation_record,
        },
    },
}
responses[exact_dialog_id] = action_name
policy = DialogPolicy(catalog, responses, enabled=True)
```

The permitted catalog event types are the full Autodesk Revit UI Events names for
`DialogBoxShowingEventArgs` and `TaskDialogShowingEventArgs`. Empty-ID dialogs,
including standard message boxes and TaskDialogs without an explicit ID, are
observation-only by construction: empty catalog IDs are rejected. The observer
still receipts those events, but never matches by message text or dialog type
alone. `MessageBoxShowingEventArgs` is not a supported catalog type.
The native adapter reads `Application.VersionBuild`
and `args.GetType().FullName`; it performs case-sensitive equality, without
substring matching or message classification. Unknown IDs, wrong types,
unverified builds, disabled policies, and unselected actions receive no override.
Missing evidence, undocumented selections, malformed fields, booleans as result
codes, zero, and values outside Int32 are rejected before subscription changes.
Configuration strings are a review requirement, not a machine proof of their
truth: never construct the catalog from arbitrary remote request data.
`policy.snapshot()` returns copied primitive `enabled`, `catalog` and `responses`
configuration for diagnostics and the execution owner's deduplication inputs.

`policy.decide(dialog_id, event_type, revit_build)` returns `(reason, action)`;
`action=None` means untouched. Policy configuration and returned actions are
copied. The callback attempts exactly one documented code, with no fallback.
`subscription.snapshot()` returns primitive copies, attachment/activity state,
current policy configuration/generation, optional scope token, current sequence,
bounded receipts (default 128, maximum 4096), and `dropped_receipts`. Each receipt
contains a sequence, timestamp, exact ID/type/build, selected action with its
evidence, attempt flag, accepted flag, reason, policy generation, caller-supplied
scope token, and any exception details.
`override_accepted` means only that Revit accepted this response code; it does
not prove document opening, operation completion, commit, rollback, or saving.
Messages are not retained because they may expose model paths or user data.
Export receipts before replacement/shutdown; they are not a persistent journal.

Subscription lifecycle
----------------------

`replace_subscription(retained_state, policy, revit_build, attach, detach,
delegate_factory, receipt_limit=128)` accepts injected native event hooks.
`initialize_for_uiapplication(uiapp, retained_state, policy=None,
receipt_limit=128)` provides an optional adapter that creates and retains one
actual .NET delegate. Call either only in a valid API context, serialized with
execution and other initialization. `remove_subscription(retained_state)` disables
and detaches the feature's delegate, and repeated removal is harmless.

The lifecycle owner must supply **the same process-retained mapping** across
initializations/engine reloads. A new local dictionary each startup cannot prevent
duplicate callbacks. No global variable in a reloaded module can establish this
guarantee. The lifecycle workstream owns the retained storage and shutdown/reload
hooks. Replacement removes the previous delegate before adding the new one.
If removal throws, the old handler is disabled, remains retained for a later
removal, and no replacement attaches. Startup must surface that failure rather
than continue as though initialization succeeded. Host event attachment must be
atomic: an attach hook that adds and then throws cannot report a safe outcome.
Mocks test repeated initialization, module reload, stale callbacks, exact
delegate removal, and failed detach. Native engine/event lifetime remains pending.

Policy scope without subscription replacement
---------------------------------------------

`subscription.set_policy(policy, scope_token=None)` validates and swaps the policy
under the callback lock, returns the previous policy, and increments
`policy_generation`. Initial generation is 0; every successful swap, including
restoration of the same policy, increments it. Invalid policies/tokens do not
change state. Tokens are optional opaque nonempty strings from the caller; this
module allocates no operation or identity IDs. Swaps never attach/detach or change
activity: a closed, unstarted or failed-detach callback stays inactive even if
an enabled policy is swapped in. Only explicit lifecycle initialization/start can
activate a callback.

`with subscription.scoped_policy(policy, scope_token=None):` restores the previous
policy and token in `finally`, also on exceptions and after the subscription is
closed inside the scope. Restoration increments generation and does not reactivate
anything. Nested scopes must unwind in order; one host owner must serialize
independent scopes. These helpers do not enforce execution ownership or native
context validation; those remain consumer responsibilities.

The retained instance anchors validated policy classes across module reloads so
it can accept the current module's `DialogPolicy` and restore prior validated
classes after further reloads. It still rejects non-policy objects. Offline
multiple-reload tests cover this Python class behavior, not native engine survival.

`subscription.current_sequence()` reads the latest event ordinal, initially 0,
monotonically increasing for that subscription's lifetime, including records lost
on capture/retention failure. Policy changes do not reset sequences or discard
receipts. Correlate events in `(start_sequence, end_sequence]` with the scope's
generation/token and the owner's existing runtime/operation identity. Use the
generation to exclude any surrounding idle observations. Actual subscription
replacement ends that sequence lifetime; ranges must not be combined across
replacement. Export receipts at lifecycle boundaries, rather than swapping the
native delegate on every operation boundary.

Execution integration requirements (pending)
-------------------------------------------

Keep this primitive separate until completed execution/routing commits supply:

1. Full instance/runtime validation before admission and execution, document
   token validation in API context, and required per-call `target`/`document`
   handles. This module creates no competing identity or operation schema.
2. A single serialized operation owner. Only that owner's active scope may enable
   selected responses. On scope entry validate a caller's explicit opt-in and
   selections against a host-reviewed catalog. Default, failed admission,
   unrelated UI commands and idle periods must retain an observation-only policy.
   Use `set_policy` or `scoped_policy` on the retained delegate; do not use
   `replace_subscription` to enter/leave an operation.
3. Use `scoped_policy` or guarantee restoration with `set_policy` in `finally`,
   including errors, cancellation and
   pending native interaction. Policy state cannot leak into the next operation.
   An unknown dialog is observed and left for the user, never forcibly canceled.
4. Receipt correlation using the operation owner's existing IDs/identities and a
   `current_sequence()` range within the same subscription lifetime plus the
   active policy generation/optional caller token; expose dropped records.
   Include the policy
   selection in the operation owner's payload hash for deduplication. Callback
   observations do not change transaction effects or claim successful execution.
5. An interaction hook that treats a known, unanswered dialog as potential user
   interaction and clears that condition only on actual resume/completion. An
   event precedes showing a dialog; its receipt alone does not prove the UI is
   still waiting. Silence/timeouts do not establish `waiting_for_user`.
6. Runtime metadata exporting loaded versions/build provenance and policy state
   through existing cached inspection. HTTP workers read primitive snapshots,
   never Revit event/application/document wrappers.

No per-operation route/parameter or automatic startup subscription is introduced
in this commit. The primitives/docs are complete independently; supported native
cases, process-retained storage wiring and execution-scope integration are separate
acceptance work, not implied by a passing mock suite.
