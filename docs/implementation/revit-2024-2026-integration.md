# Revit 2024–2026 integration build

Branch: `integration/revit-2024-2026` on Origin
`NateZwainleskPLA/pyrevit-mcp`. It starts at Origin master `4e8ec5f`
and merges the actual published heads of all eight PRs, with no PR closed or
merged into master. The original publication and build branches are preserved.

| PR | Publication head |
| --- | --- |
| #1 Status API context | `3b537758ce7ef7ccfa618e0df3222bfbc925748d` |
| #2 Structured transport | `e698a7eb1b8f083ed884ee694b2af284462d2934` |
| #3 Execution foundations | `10ec37d601e005b4e2737c7daa672e05a61c44dc` |
| #5 Identity and handles | `40f6de1e88d4a12db56332245d13e265306dfb44` |
| #7 Routing, launch and files | `e1fb74b876fafeecff11cae4ac8b6d9c1af29b25` |
| #8 Recoverable operations | `c2b0ef39f1819aa66eb66f004249d28f6f2c7851` |
| #4 Dialog policy and diagnostics | `6440d151f09b7ca83de87aa937779c5c45663a87` |
| #6 Listener lifecycle diagnostics | `fd4250c5bc6bf33bc849eda6b55c509fdb343b47` |

## Integration checks

All eight merges were conflict-free. The merged suite passes **461 tests**;
15 historical native tests remain skipped because they require a model fixture
and their fixtures need adaptation to the targeted API. No bundled or user
model is opened for these checks.

The MCP client imports and registers 23 tools in its own Python 3.13 virtual
environment. `pip check` passes. MCP is constrained to `>=1.9.0,<2` because this
server imports the 1.x `mcp.server.fastmcp` interface. `requirements.txt`
records the actual tested environment with MCP 1.30.0. Use the installed
`.venv/Scripts/python.exe`, rather than the old uv invocation/lockfile.

## Local installation

Checkout: `D:/CodexWorktrees/pyrevit-mcp-integration-revit-2024-2026`.
Revit 2024, 2025 and 2026 are already attached to the installed pyRevit 7 clone,
with the .NET Framework engine for 2024 and .NET engines for 2025/2026.

The existing `revit-mcp-python.extension` contains local edits. The installer
backs up its exact startup and the Codex client configuration before replacing
the startup with a version-scoped dispatcher. Revit 2024–2026 execute the
preserved local pre-registration Routes guards, then load this integration
checkout. Other Revit years execute the complete original startup. Existing
extension modules, local edits, pyRevit binaries, add-in manifests and extension
enable/disable settings are not rewritten.

The existing Codex `revit-mcp-python` server points directly at the integration
virtual environment and `main.py`. Its directory state is persisted under the
installation backup root so opaque handles survive client restarts. Restart
the MCP client connection to obtain the new explicit target/document tool
signatures. One client discovers all three versions; each directed call must
specify its target.

```powershell
.venv/Scripts/python.exe -m scripts.install_revit_integration `
  --source D:/CodexWorktrees/pyrevit-mcp-integration-revit-2024-2026 `
  --legacy-extension 'D:/OneDrive - PLA Designs/Documents/pyRevit/revit-mcp-python.extension' `
  --backup-root "$env:LOCALAPPDATA/RevitMCP/integration-installs" `
  --codex-config "$env:USERPROFILE/.codex/config.toml"
```

The installer emits `installation.json` and original file backups in a fresh
timestamped directory. Native startup writes `loaded-<pid>.json` there, recording
the deployed commit, actual source module paths, target metadata, or an error.
These runtime records are local evidence, not committed credentials/config.

Rollback requires unchanged installed files; it refuses to overwrite subsequent
user edits. Restart Revit/client after restoration:

```powershell
.venv/Scripts/python.exe -m scripts.install_revit_integration `
  --restore '<timestamped installation directory>'
```

## Activation boundaries

The installation registers targeted synchronous routes and identity discovery.
Private asynchronous execution remains opt-in and unregistered by default;
its exclusive ownership/native lifecycle gates still apply. The dialog policy's
native response catalog is empty. Listener diagnostics are merged as tooling;
the disposable listener probe is not installed or activated automatically.
The machine's pre-existing local Routes guards are preserved separately and
are not presented as newly validated production fixes from PR #6.

Installation/startup verification does not establish geometry, transactions,
interactive picking, reload/engine lifetime or journal durability acceptance.
Native results and deployed commit are recorded after installation below.

## Verified deployment, October 6, 2026

Deployed source commit: `bd2700b2c730f9d41e9269ef14b4b93aef9ff3c5`.
The later branch commit adds this report and the read-only verification helper;
it does not change the connector modules loaded into these three processes.

| Revit | Build | Verification process | Endpoint | Result |
| --- | --- | --- | --- | --- |
| 2024 | 24.3.50.51 | 50252 | `http://127.0.0.1:48884/revit_mcp` | Native startup loaded; cached metadata HTTP 200; Windows PID/start/listener ownership verified |
| 2025 | 25.5.0.57 | 33612 | `http://127.0.0.1:48886/revit_mcp` | Same checks passed after the user's update completed and Revit was relaunched |
| 2026 | 26.4.10.51 | 54736 | `http://127.0.0.1:48885/revit_mcp` | Native startup loaded; cached metadata HTTP 200; Windows PID/start/listener ownership verified |

Each native receipt identifies 19 connector source modules from the integration
checkout. A real MCP stdio initialize/list-tools/call-tool session exposes 23
tools and discovers all three versions with distinct target handles. The handle
directory is persisted and reused across verification/client sessions. All three
document snapshots were empty; no model was opened or modified.

Backups and detailed receipts:
`C:/Users/NateZwainlesk/AppData/Local/RevitMCP/integration-installs/20261006T173513Z`.
The local `installation.json` records exact original/installed file hashes;
`native-verification.json` records discovery and MCP checks. Neither backed-up
configuration nor credentials are committed to this branch.

The first Revit 2025 attempt ran while the user was updating it and stopped at
unit-schema initialization, before pyRevit. The fresh process after completion
loaded the connector successfully. Revit 2025 subsequently showed an unrelated
`AG_Custom_Ribbon_Tab_Builder` external-application startup warning; that does
not invalidate cached connector startup/identity evidence, and is not claimed
fixed here.

A single read-only API-context probe in Revit 2024 timed out at Home. It was not
retried or used as a readiness poll. The helper defaults to cached metadata;
native document/transaction/model execution readiness remains unverified.
The 15 historical fixture-dependent native tests remain skipped. The final
combined suite still passes 461 tests and `pip check` passes.

Repeat the read-only installation checks while these versions are running:

```powershell
.venv/Scripts/python.exe -m scripts.verify_revit_installation `
  --case-dir 'C:/Users/NateZwainlesk/AppData/Local/RevitMCP/integration-installs/20261006T173513Z' `
  --output 'C:/Users/NateZwainlesk/AppData/Local/RevitMCP/integration-installs/20261006T173513Z/native-verification.json'
```

PR #1's later local-only review correction `2eb54f6` is not included or pushed.
The modern integration launch retains its existing cached metadata handshake;
it does not poll the document-context `/status/` route for readiness.
