Scoped Revit MCP diagnostic runbook
==================================

This runbook separates connector provenance, blocked native interaction, listener
lifecycle, and possible add-in conflicts. Its tools prepare local evidence and
read metadata; they do not start/close Revit, open/save a model, change add-in
settings, reload an extension, dismiss a dialog, or submit an MCP mutation.
Native experiments require an explicitly supplied disposable fixture and a
dedicated, authorized diagnostic host. The repository's `tests/test.rvt` is not
automatically authorized by its presence.

Current validation boundary
---------------------------

The dialog primitive is opt-in with an empty supported catalog, and importing
either new module has no startup side effects. `startup.py` remains unchanged.
Offline tests cover exact policy validation, callback receipts, subscription
replacement and filesystem evidence. They establish no Revit 2025 dialog/button
semantics, native API threading, engine retention or listener reload behavior.
No disposable native fixture was supplied for this workstream, so native checks
are **not run**, and all cases below remain pending.

Loaded runtime evidence
-----------------------

Use the identity workstream's cached metadata/discovery contract to choose the
intended host. Record its actual instance/runtime IDs, PID/start time, version,
endpoint and document descriptors, including snapshot freshness. Every eventual
host call requires `target`; document work also requires `document`. Recheck the
full identities at the receiver and document token in API context. A port, title,
installed build, or current working directory does not prove which code/model is
loaded. This workstream introduces no alternate discovery route or handle mapping.

`revit_mcp.runtime_diagnostics.collect_loaded_runtime_metadata(application,
runtime_snapshot, loaded_build=None, pyrevit_version=None)` is a read-only capture
helper for a future approved runtime hook. Call it once in a valid API context
and cache the returned primitives for background inspection. Supply the existing
identity owner's primitive snapshot without rebuilding it. It preserves that
snapshot verbatim, including future fields/freshness, and records capture time
separately; capturing diagnostics does not refresh the identity snapshot.

The helper reports loaded Revit `VersionNumber`, `VersionName`, `VersionBuild`,
Python/IronPython version/platform, and loaded connector module paths/declared
versions from `sys.modules`. It accepts a build stamp **retained at initialization**
and a version from the loaded pyRevit host; absent stamps/versions remain null.
The lifecycle owner supplies them. A current `git rev-parse`, package manifest,
installer inventory or source-file digest is not a loaded-runtime build stamp.
`source_file_sha256_at_capture` is explicitly a hash of bytes on disk at capture,
which may have changed since load. Capture/file-access errors remain visible.

Illustrative future hook, inside an authorized disposable host's API callback:

```python
from revit_mcp.runtime_diagnostics import collect_loaded_runtime_metadata

# These values come from completed identity/lifecycle interfaces, not new IDs.
cached_diagnostics = collect_loaded_runtime_metadata(
    uiapp.Application,
    approved_identity_snapshot,
    loaded_build=initialization_build_stamp,
    pyrevit_version=loaded_pyrevit_version,
)
```

This is a helper contract, not an installed route or runnable unbound MCP call.
Native capture and cached endpoint wiring wait for the owning interfaces. Save
the resulting JSON with the actual target, operation receipt where applicable,
UTC observation time, and client/server logs. Record unknown provenance explicitly
rather than label the on-disk checkout as the loaded extension.

Prepare a disposable case offline
---------------------------------

The client-side utility `python -m tools.diagnostic_case` performs only local
copies/hashes and named-settings comparisons. Supply a known disposable standalone
`.rvt` or `.rfa` file yourself. Each case directory must be new; an existing case
is rejected so previous diagnostic edits/evidence cannot be overwritten.

```powershell
uv run python -m tools.diagnostic_case prepare `
  --fixture "C:\DisposableFixtures\ExplicitlySuppliedFamily.rfa" `
  --case-dir "C:\DiagnosticCases\UniqueCase-001" `
  --runtime-metadata "C:\DiagnosticEvidence\LoadedRuntime.json" `
  --record-setting "C:\DiagnosticProfile\RecordedSettings.ini"
```

`--runtime-metadata` and repeatable `--record-setting` are optional. Runtime JSON
is preserved as supplied evidence, not treated as a fresh handshake or routing
binding. The utility creates `case.json`, `fixture/<original-name>`, and copies
each named existing setting beneath `settings/<index>/`. It records absolute
original/backup paths, byte hashes, and settings that originally did not exist.
It verifies copied bytes against the unchanged source. Errors leave an incomplete
case directory for inspection; do not reuse it. Fake fixture bytes in the unit
tests are never native-opened and are not a substitute for a real fixture.

A byte copy of a workshared model is not necessarily a standalone fixture: it can
retain its central association. Have the authorized human prepare and identify a
detached standalone diagnostic copy with a new save destination before native
experiments. Record that procedure and path. The utility does not detach, sync,
upgrade a model or inspect worksharing. Keep production originals and existing
editing sessions outside the experiment.

Native experiment and evidence record
------------------------------------

1. Record the fixture authorization/path, case directory, baseline hashes,
   expected Revit version/build, desired test and dedicated host identity. Agree
   separately on any installation/startup/reload action in that diagnostic host.
   This implementation task authorizes none in an existing editing session.
2. Capture loaded runtime evidence and resolve fresh handles. Confirm the
   diagnostic process and exact disposable document before each experiment;
   receiver-side full checks still apply. Preserve pre-test snapshot age and
   logs. Do not infer readiness merely from a reachable HTTP listener.
3. Start observation-only dialog capture through the optional adapter using the
   lifecycle owner's retained mapping. Record subscription state, one event per
   callback, actual `DialogId`, .NET event type, exact build and receipt sequence.
   No dialog is automatically answered. The authorized human records the visible
   button labels/action consequences and handles the dialog normally. Avoid
   collecting model-sensitive messages unless specifically needed for the case.
4. An automatic response case can be added only after exact dialog-specific
   authoritative button/action information is available and the case is tested
   on the listed build in the disposable host. Explicitly select that documented
   action and opt in. Record attempted code, accepted boolean/errors, actual
   native outcome and document/operation readback. `OverrideResult=True` alone
   proves neither completion nor transaction effects. Unknown dialogs remain
   untouched. No fallback to OK, broad text matches or generic suppression.
5. If native interaction blocks work, preserve the original operation ID and
   inspect its receipt through the established inspection API when available.
   A timeout does not prove failure and is not permission to replay a mutation.
   An observed dialog precedes its display and does not prove it remains open;
   distinguish confirmed user interaction from an unavailable/busy API callback.
6. Export receipts before subscription removal/replacement, then disable and
   detach the exact delegate. If removal fails, preserve the disabled reference
   and report the failure; add no replacement. Record terminal operation state
   and effects separately, including unknown outcomes and dropped receipts.

Pending acceptance matrix:

| Check | Expected evidence | Current coverage |
| --- | --- | --- |
| Default/unknown dialog | No override attempt, visible normal user handling | Offline policy only; native pending |
| Supported exact ID/type/build/action | One code accepted plus actual intended native outcome | No supported native cases yet |
| Rejected/throwing override | One attempt, rejected/error receipt, no fallback | Offline callback only; native pending |
| Repeated initialization | Exactly one retained delegate and one receipt per event | Offline reload/replacement only |
| Detach/reload/restart | Old delegate removed, no duplicate callbacks, expired identities remain expired | Native engine lifetime pending |
| Per-operation scope | Opt-in after full identity/document checks; unrelated UI untouched; finally cleanup | Integration pending |
| Loaded diagnostics | Actual loaded builds/paths and primitive cached inspection | Fake application tests only |
| Fixture/settings evidence | Originals unchanged, hashes and restoration comparison | Filesystem tests passed |

Opt-in add-in isolation
----------------------

General add-in isolation is a separate troubleshooting experiment when baseline
evidence warrants it. It is not normal MCP mutation, an execution prerequisite,
or an automatic recovery step. Obtain explicit authorization for the exact
diagnostic host/profile/settings and intervention. Prefer a dedicated diagnostic
user profile or isolated environment with known manifests, leaving the user's
editing process/settings intact. Do not disable add-ins, change shared add-in
configuration, terminate the user's process or reload their loaded extension as
part of this runbook's implementation.

Before an authorized intervention, name every file/setting that will change and
record its original bytes/absence with `--record-setting`. For non-file settings,
record the exact key/value, original existence, export/backup location and manual
restoration action in the evidence record. Inventory paths, loaded versions and
enabled state. Change one diagnostic variable at a time; preserve a clean
baseline, bridge-only and chosen diagnostic configuration as separate cases.
An editor passing in one profile does not identify which add-in caused an earlier
failure, and connector health does not establish full editor stability.

Record restoration and close the case
------------------------------------

The authorized human restores only the explicitly recorded diagnostic changes:
existing files/settings to their exact originals and originally absent settings
to absence. Record each action, time, operator and result. Never infer a restore
from a restart or from a missing exception. Preserve backup evidence; if a backup
hash differs, stop treating it as a valid restoration source.

```powershell
uv run python -m tools.diagnostic_case verify-settings `
  --case-dir "C:\DiagnosticCases\UniqueCase-001" `
  > "C:\DiagnosticCases\UniqueCase-001\SettingsVerificationAfter.json"
```

This command only compares files. It performs no restoration or deletion. Exit 1
means `mismatch`; exit 0 with `verified` means every recorded file matches its
baseline and its backup is valid. `no_settings_recorded` proves no restoration.
Keep the case at its recorded location because manifest paths are absolute.
File-byte comparisons do not verify registry/UI-only settings, permissions or
symlink state; record those checks separately if the experiment changed them.

Append the comparison result to the case evidence, alongside any manual non-file
restoration checks, loaded metadata, subscription receipts, listener/API health,
operation identities/outcomes, user-handled prompts and unresolved observations.
Keep `native_validation: not_run` until actual native checks are completed and
their evidence is recorded. List partial/failed/pending checks individually; do
not convert an offline test pass into native acceptance.
