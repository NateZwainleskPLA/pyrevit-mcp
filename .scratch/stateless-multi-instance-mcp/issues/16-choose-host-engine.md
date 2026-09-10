# Choose the pyRevit engine for host-side runtime code

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Which pyRevit engine (IronPython 2.7, IronPython 3.4, or CPython) runs the extension's host-side code, and what does that choice constrain?

The Revit Target owns a FIFO Execution Queue, an in-memory operation registry, Submission Identity parsing (`sub_<uuidv7>`), command fingerprinting, SHA-256 code-artifact hashing, Windows ACL application, single-writer NDJSON streams with rotation, and cooperative cancellation. All of it runs inside Revit under a pyRevit engine, and user code submitted through code execution runs in the same engine. No decision records which engine, the minimum pyRevit version, or whether the extension may pin an engine in its manifest.

Decide the engine and minimum pyRevit version, and list the facilities the chosen engine provides or lacks for hashing, threading, ACLs, UUID handling, and JSON, so the prototype and spec can rely on them.

## Comments

- 2026-09-09: Claimed for NateZwainleskPLA as the first open, unblocked, unclaimed ticket in numeric order. Planning only; the tool-catalog ticket is already claimed.
- Opening decision round (historical): determine whether submitted Revit code must support modern Python syntax or CPython packages. Proposed retaining the existing IronPython-compatible scripting contract unless those capabilities are required; this does not constrain the separate MCP helper's Python runtime. The decisions from the subsequent exchange are consolidated under Answer below.
- Local evidence: `revit_mcp/code_execution.py` imports Python 2 `StringIO` and executes submitted code in the route handler's interpreter. `revit_mcp/utils.py` explicitly uses Python 2 `unicode`. `extension.json` currently declares no engine constraint. The migration's acceptance contract requires an exact declared and tested environment matrix, so an upstream compatibility claim alone cannot establish product support.

### Accepted engine choice

- After clarification of the two runtime scopes, the user agreed with retaining IronPython 2.7.12 inside Revit for this migration. This applies to extension host-side runtime code and submitted Revit scripts. Modern Python syntax and CPython packages inside Revit are not a migration requirement; the separate MCP helper retains its independently selected modern Python runtime. This does not add a general-purpose package execution feature to the helper.
- The user settled the engine choice first, then the minimum-version policy and incompatible-host behavior. No live runtime or installation has been changed.

### Accepted minimum-version policy

- The user specified that the minimum pyRevit version will be whatever is newest at product release time, and confirmed their current environment is 6.5.4. Interpret the release baseline as the newest stable official pyRevit release at that time. This supersedes the proposed fixed minimum of 6.5.5.
- Record the concrete minimum and exact tested pyRevit/engine/Revit combination in the shipped release's compatibility metadata and acceptance evidence. The minimum is fixed for that product release, rather than moving automatically on installed copies when pyRevit publishes another version. A version number alone does not establish compatibility or replace the acceptance checks.
- Use the current 6.5.4 environment for development and exploratory prototype evidence. Final release acceptance must cover the selected release-time baseline. If that baseline changes the available engine or invalidates the agreed IronPython 2.7.12 contract, revisit compatibility before shipping rather than silently adopting a different engine.

### Accepted incompatible-host policy

- Incompatible hosts: check the actual loaded engine and product compatibility before exposing a Revit Target. Leave an incompatible host unexposed and show an actionable local diagnostic. Never silently switch the host-wide pyRevit attachment or fall back to CPython/IronPython 3; other compatible hosts continue to work. Initial accepted engine build is IPY2712PR (IronPython 2.7.12); expanding the supported engine set requires validation. The extension declares/checks this requirement rather than relying on an unsupported per-extension IronPython version pin.
- After clarification that Revit continues operating normally while only that incompatible instance remains unavailable to MCP, the user confirmed: "yep sounds good." This completes the decision round.

### Supporting engine investigation (2026-09-09; not a resolution)

- The sibling `../pyRevit` checkout is custom commit `cfce05924074985878393fcc1692ec729a6f17d0`, labelled 6.5.4. Its `pyRevitfile` declares default IronPython 2.7.12, alternate IronPython 3.4.2, and CPython 3.12.3. The installed Revit add-in manifests select `IPY2712PR`; that establishes configured attachment, not the interpreter already loaded in a live process. The Program Files clone reports 6.5.3.26176+2017.
- `dev/pyRevitLoader/pyRevitExtensionParser/BundleParser.cs` supports Python family selection and clean/full-frame/persistent flags, not an engine version pin. `dev/pyRevitLabs.PyRevit.Runtime/ScriptRuntime.cs` obtains the IronPython version from the attachment environment. The [official architecture guide](https://docs.pyrevitlabs.io/architecture/) corroborates attachment-wide IronPython selection. Changing IronPython 2 versus 3 is therefore not an isolated extension preference in the inspected implementation.
- A CPython startup shebang follows the shared selection path in `SessionManagerService.cs` and `ScriptRuntime.cs`. This establishes a selection mechanism, not safe Routes interoperability: `CPythonEngine.cs` uses `Py.GIL()` and disposes its execution scope, while `IronPythonEngine.cs` explicitly honors persistent startup globals. Callback lifetime, reload behavior, and crossing an IronPython-owned Routes server need a targeted live prototype before choosing CPython.
- The investigation recommended IronPython 2.7.12 unless modern syntax or CPython packages were a requirement. IronPython 3.4.2 does not provide modern syntax such as f-strings and requires an attachment change. The user subsequently accepted the IronPython 2.7.12 recommendation.
- Through [IronPython .NET integration](https://ironpython.net/documentation/dotnet/dotnet.html), SHA-256 can use `SHA256.Create().ComputeHash` over explicit UTF-8 bytes, synchronization can use .NET locks/events, and ACLs can use `DirectorySecurity`/`FileSecurity`. [.NET FileSystemAclExtensions](https://learn.microsoft.com/en-us/dotnet/api/system.io.filesystemaclextensions.setaccesscontrol) and assembly loading must be validated for the selected Revit/.NET matrix. Routes already uses Python threading and JSON, but synchronization, canonical JSON/Unicode encoding, single-writer rotation and flush behavior remain implementation responsibilities. Cancellation requires cooperative checkpoints.
- Submission Identity parsing needs strict prefix, canonical UUID text, version/variant and timestamp validation; it does not need UUIDv7 generation in Revit. Do not rely on `Guid.CreateVersion7` or `Guid.Version` on .NET 8: they arrived in [.NET 9](https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-9/libraries).
- The latest stock release verified at investigation time through GitHub was [pyRevit 6.5.5, published August 25, 2026](https://github.com/pyrevitlabs/pyRevit/releases/tag/v6.5.5.26237%2B2044). Neither a historical minimum nor product support on that release was established. The user subsequently chose the release-time minimum policy below; the local custom 6.5.4 label alone is not released-product acceptance evidence.

## Answer

### Engine and scripting contract

Use pyRevit's IronPython 2.7.12 engine (`IPY2712PR`) for the extension's host-side runtime and for submitted code that runs inside Revit. Keep that code compatible with Python 2.7 syntax and the available IronPython/.NET libraries. Modern Python syntax and CPython packages inside Revit are not requirements of this migration. The MCP Adapter retains its independently packaged modern Python runtime; this decision adds no new adapter tool or package-execution capability.

The extension declares and checks engine compatibility. It cannot independently pin IronPython 2 versus IronPython 3 in its manifest using the inspected pyRevit engine selection mechanism: the attached host engine determines that version. Do not silently change the attachment or substitute CPython or IronPython 3. Any future supported engine change requires explicit compatibility validation.

### pyRevit minimum and development baseline

The minimum supported pyRevit version is the newest stable official release available when the migrated product ships. Resolve that policy to a concrete version in the product release's compatibility metadata and acceptance evidence. That minimum stays fixed for the shipped artifact; subsequent upstream releases do not automatically change it or acquire verified support.

The user's current pyRevit 6.5.4 environment is the development and exploratory prototype baseline. Record its exact checkout/build and actually loaded engine with evidence. Final acceptance must cover the release-time stock baseline and the exact declared Revit/pyRevit/engine matrix required by [Define the conformance and acceptance contract](09-define-acceptance-contract.md). If that stock baseline cannot satisfy the selected engine contract, revisit compatibility before shipping. This is a release selection rule, not an unresolved choice of a minimum today.

### Incompatible-host behavior

Before exposing a Revit Target, check the actual loaded engine and declared product compatibility. Keep an incompatible host unavailable to MCP and show an actionable local diagnostic identifying the mismatch and the corrective action. Revit continues operating normally, other compatible hosts remain available, and the extension leaves any host-wide engine change to the user. Manifest configuration alone is insufficient evidence of what a running process loaded.

### Facilities and constraints

The supporting source evidence and primary-source links above establish available mechanisms, not a completed live-runtime acceptance test.

| Need | Host-side facility and constraint |
| --- | --- |
| Hashing | Use .NET `SHA256.Create().ComputeHash` over explicitly encoded bytes. Canonical command encoding and exact-code UTF-8 encoding must satisfy the execution-safety and Forensic Record contracts. |
| Threading and cancellation | Python threading and .NET locks/events are available. Synchronize admission and registry access explicitly; use the extension-owned UI execution lane for Revit API work. Running cancellation remains cooperative, with no thread abort or generic forced timeout. |
| Windows ACLs | .NET `DirectorySecurity`/`FileSecurity` and the applicable filesystem ACL APIs provide the mechanism. Verify assembly loading and ACL application on each declared .NET/Revit boundary. |
| UUIDs | Parse and validate Submission Identity prefix, canonical UUID text, version, variant, and timestamp explicitly. UUIDv7 generation is unnecessary in the host; do not assume .NET 9's `Guid.CreateVersion7` or `Guid.Version` exists on .NET 8. Operation UUIDv4 generation can use the available GUID/UUID facilities. |
| JSON and evidence files | Python `json` and .NET file/stream facilities are available. Verify Unicode, canonical fingerprint encoding, single-writer ownership, rotation, retention, and flush behavior; library availability does not supply these guarantees automatically. |
| Runtime lifetime | Use persistent host-side startup state for the target-owned queue and operations. Verify callback lifetime, synchronization, and reload/target-expiry behavior in the prototype; process or target loss does not create a recovery store. |

### Handoff

[Prototype the in-Revit execution lane and control plane over pyRevit Routes](17-prototype-host-execution-lane.md) now has a selected engine and development baseline. It must report actual runtime evidence and any required amendments to the existing contracts. This ticket does not establish that Routes already meets those contracts, implement the migration, or broaden the glossary with engine implementation details. No additional decision ticket or fog graduation is needed from this resolution.
