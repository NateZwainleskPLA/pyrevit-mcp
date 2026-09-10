# Reconcile the per-user storage root across topology, installation, and Forensic Record decisions

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Which per-user directory root holds the Connection Descriptor, product settings, and Forensic Record, and how is it resolved?

**Choose MCP adapter topology and durable state ownership** and **Choose the installation and runtime packaging contract** place the descriptor and diagnostics under Local App Data. **Define the Forensic Record contract** resolves storage through `PYREVIT_APP_DIR`, which the installed pyRevit source defines as `%APPDATA%\pyRevit` (Roaming). A 250 MiB evidence store plus exact-code artifacts in a roaming profile on a domain-joined workstation will sync, slow logon, and leak submitted code onto profile servers.

Decide the root (Local versus Roaming), whether settings and the descriptor may differ from evidence, how the packaged adapter (which has no pyRevit runtime) and the Revit Host (which does) resolve the same path, and what an operator sees if the roots disagree. Amend the three tickets so they agree.

## Comments

### User decisions — 2026-09-09

The user chose one product directory in Local AppData for all three artifacts, a fixed root with no operator-configurable override in the first release, and isolation of a mismatched host while preserving inspection/cancellation of already accepted work and continued operation of other hosts.

## Answer

### Fixed root and layout

Use `%LOCALAPPDATA%\pyRevit\revit-mcp-python` as the documented product root. The `pyRevit\revit-mcp-python` suffix is a fixed storage identity shared by the packaged adapter and host code, not a value inferred from an installation folder, display name, or running Revit version. Store `connection.json`, `settings.json`, and `ForensicRecord\v1` beneath it. Settings remain separate from `pyRevit_config.ini`.

The first release has no operator-configurable root override and no split between local evidence and roaming settings. Product version, Revit version, and display-name changes do not relocate the root. Evidence schema versions remain beneath the stable root under the Forensic Record contract. Exported diagnostic ZIPs remain user-owned files outside managed storage.

### Resolution and agreement

`%LOCALAPPDATA%` is documentation shorthand for Windows' current-user Local AppData special folder. Both processes resolve that folder independently through Windows APIs and append the same suffix; neither reads `PYREVIT_APP_DIR`, `PYREVIT_PATH_OVERRIDE`, or a product-root override to choose this directory. The host can use .NET `Environment.GetFolderPath(SpecialFolder.LocalApplicationData)`; the packaged Python adapter can call the Windows shell folder API through `ctypes` without importing pyRevit. Resolver failure is explicit, with no fallback to Roaming, the installation directory, ProgramData, or temporary storage.

The Target Runtime compatibility handshake carries each process's resolved absolute root and storage-contract revision. Compare normalized Windows directory paths, not raw spelling or environment-variable strings. Verify agreement before admitting new commands through a host and again when establishing a replacement adapter/host connection. A path received from another process is comparison data, never an instruction to switch roots. Client-started adapters use the same independent resolver before any host exists.

If the roots disagree, report `storage_root_mismatch` and refuse new commands to the affected host. Other compatible hosts continue. Preserve operation inspection and cancellation for already accepted work; those operations retain their existing execution, result, and Forensic Record write-failure semantics. A mismatch never creates a replacement target, replays a command, or moves an operation. Do not copy, merge, delete, or adopt data from the other root, and do not search alternate roots for settings or a Connection Descriptor.

The affected host's Revit MCP Status surface and adapter's local status output show both resolved paths, the mismatch category, and which host connection is blocked. Resolver failures show the failing side and a stable failure category. Status identifies the effective settings, Connection Descriptor, and evidence locations even when healthy. Local paths stay out of ordinary Forensic Record events and sanitized client-facing health; those surfaces may report the error category and affected exposed target without leaking filesystem paths or disabled-host identity. Correction is explicit, followed by a fresh successful handshake before new commands resume; the product performs no automatic repair or storage relocation.

This chooses a Windows non-roaming application-data location; it does not promise exclusion from an organization's separate backup or profile-management tooling. Settings/ACL, evidence retention, degraded-write behavior, export, uninstall, and reset continue to follow their existing contracts within this root. This planning amendment moves no existing files and implies no legacy-settings import.

### Evidence and acceptance

Evidence: the sibling pyRevit checkout's `pyrevitlib/pyrevit/__init__.py:844–847` delegates `PYREVIT_APP_DIR` to `dev/pyRevitLabs/pyRevitLabs.Common/Consts.cs:61–66`, which honors `PYREVIT_PATH_OVERRIDE` and otherwise uses Roaming ApplicationData. Microsoft's [SpecialFolder reference](https://learn.microsoft.com/en-us/dotnet/api/system.environment.specialfolder) distinguishes LocalApplicationData from roaming ApplicationData. A CPython `SHGetFolderPathW(CSIDL_LOCAL_APPDATA)` call and a PowerShell/.NET LocalApplicationData call returned the same directory on this workstation; live host and additional-profile verification remain implementation acceptance work.

Implementation acceptance must demonstrate identical resolution in the packaged adapter and each supported host engine, startup without Revit, independence from the installation folder and pyRevit overrides, agreement after adapter replacement, and explicit resolution failure with no fallback. Inject a host/adapter root mismatch and prove isolation of new commands, continued inspection/cancellation of accepted work, continued service to other hosts, both paths in local status, and no automatic file copying or alternate-root use. The API checks above establish feasibility only; they are not live-host or packaged-product acceptance evidence.

The storage statements in [Choose MCP adapter topology and durable state ownership](04-choose-runtime-topology.md), [Choose the installation and runtime packaging contract](05-choose-installation-contract.md), and [Define the Forensic Record contract](10-define-diagnostic-journal.md) now defer to this ticket. No new decision ticket or fog graduation is needed; these are requirements for the existing migration specification and acceptance work.
