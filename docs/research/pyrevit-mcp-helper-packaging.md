# Packaging an on-demand MCP helper inside a pyRevit extension

Research date: 2026-08-10

## Question

Which technically viable packaging mechanisms can ship and launch the modern-Python MCP helper from one pyRevit extension, without a persistent service, and what do primary sources and minimal local experiments establish about user prerequisites, artifact size, signing/antivirus behavior, dependency compatibility, update burden, and supported Revit/pyRevit versions?

## Answer in brief

A pyRevit extension can contain an on-demand MCP subprocess without installing a service. The strongest default candidate is a **Windows-x64 PyInstaller bundle**, launched directly by the MCP host over stdio. It gives the Revit user no Python, `pip`, or `uv` prerequisite. A signed one-file build is the smallest and simplest artifact tested; a one-folder build avoids extraction on every launch and is the operational fallback if one-file behavior causes security-tool or startup problems.

An **official embeddable CPython distribution plus vendored wheels** is also viable and avoids freezer-specific import discovery, but it is a materially larger, multi-file application bundle whose dependencies must be assembled and updated by the project. A **bundled `uv.exe` bootstrap** hides the manual `uv` installation step but does not remove the runtime: it downloads and maintains Python, a virtual environment, packages, and cache on first use. It had by far the largest tested installed footprint and still introduces first-run network behavior. Requiring a user-installed Python or `uv` remains a defensible escape hatch, not the preferred experience.

Packaging cannot begin from the current program unchanged. The repository targets Python 3.11+ and imports `FastMCP`, `Image`, and `Context` from the SDK v1 `mcp.server.fastmcp` module, while MCP Python SDK 2.0 requires Python 3.10+ and renamed `FastMCP` to `MCPServer`. SDK 2.0 also replaced its `httpx` dependency with `httpx2`; this repository imports `httpx` without declaring it directly. The SDK migration must therefore land before a production bundle is frozen. [Current project metadata](https://github.com/NateZwainleskPLA/pyrevit-mcp/blob/51b4829655b5a9822da16e13644158722e060f84/pyproject.toml), [current MCP entry point](https://github.com/NateZwainleskPLA/pyrevit-mcp/blob/51b4829655b5a9822da16e13644158722e060f84/main.py), [official SDK v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/)

## Decision table

| Mechanism | User prerequisites | Tested distribution size | First-run behavior | Update owner | Assessment |
| --- | --- | ---: | --- | --- | --- |
| PyInstaller one-file | None beyond supported Windows | 21.86 MiB, one file | Self-extracts to a temporary directory; 2.0–2.6 s to import MCP and exit on EOF in the probe | Project rebuilds, tests, signs, and replaces the executable | **Preferred default candidate** |
| PyInstaller one-folder | None beyond supported Windows | 43.25 MiB, 143 files | No one-file extraction; 0.80–1.58 s in the same probe | Project rebuilds, tests, signs, and replaces the folder | **Preferred fallback** if one-file is blocked or too slow |
| Embeddable CPython 3.13.14 + vendored MCP 2.0 wheels | None; the application must ensure the Microsoft C Runtime exists | 73.47 MiB expanded / 31.94 MiB zipped, 2,817 files | 0.69–0.74 s in the probe; no dependency download | Project vendors and validates Python plus all wheels as one application | **Viable fallback** when transparent Python files are preferable to freezing |
| Bundled `uv` 0.12.3 + pinned project | Network on first provisioning unless runtime and packages are also shipped | `uv.exe` 45.80 MiB; one test provision accumulated 185.33 MiB of logical cache/Python data plus a 43.62 MiB logical venv | Cold ephemeral import 16.2 s; persistent-project warm import 1.16 s | Project pins `uv`, Python, and lockfile; `uv` provisions and caches them | **Not recommended as default**; useful bootstrap/escape hatch |
| User-installed Python/`uv` | User installs and maintains the prerequisite | Extension source only | Environment creation/download at setup or first run | Split between user and project | **Acceptable exception** to the preference for no managed prerequisites |

The measurements are lower bounds from a minimal MCP SDK 2.0 server probe, not a forecast of the finished Revit helper. They measure logical file lengths rather than allocated disk blocks. They do not include the future routing/task implementation, signing data, or a full MCP request round trip.

## What the primary sources establish

### MCP runtime and dependency boundary

The current stable Python SDK documents Python 3.10+ and uses `from mcp.server import MCPServer`; its `[cli]` extra exists to install the development CLI, so a production executable does not need to carry `[cli]` merely to serve MCP. [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)

The v2 migration guide identifies the exact failures seen locally: `FastMCP` was renamed to `MCPServer`, transport settings moved from the constructor to `run()`/app methods, and `httpx`/`httpx-sse` were replaced by `httpx2`. It says an application that still uses `httpx` must either declare it itself or migrate those calls to `httpx2`. It also documents the new dependency floors and exact `mcp-types` pin. [SDK v2 migration guide: common changes and dependency floors](https://py.sdk.modelcontextprotocol.io/migration/#changes-almost-every-project-hits)

This is a packaging concern because all tested self-contained mechanisms capture a resolved dependency set. The production build should use the base `mcp==2.x` dependency, choose `httpx2` or directly declare `httpx`, and lock the complete Windows-x64 dependency graph before freezing or vendoring it.

### Frozen executable

PyInstaller officially bundles the active Python interpreter and imported dependencies so users do not install Python or modules. It supports a one-folder bundle and a one-file executable. One-file mode extracts its archive to a random `_MEI...` temporary folder at startup, runs from there, and removes the folder on normal exit; crashes or forced termination can leave the folder behind. PyInstaller also warns that one-file starts more slowly and recommends proving one-folder first. [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html)

PyInstaller is not a cross-compiler: a Windows bundle must be built on Windows. Its own installation guidance also says `pyinstaller` and `pyinstaller-hooks-contrib` should remain approximately synchronized. That makes a pinned Windows CI build, followed by clean-machine smoke tests, part of the maintenance cost. [PyInstaller platform support](https://pyinstaller.org/en/stable/), [PyInstaller installation guidance](https://pyinstaller.org/en/stable/installation.html)

Nuitka also officially supports independent `standalone` and `onefile` outputs, so it is another technically viable freezer. It requires a compatible C compiler at build time and brings a second compilation/toolchain path without removing the need to sign and test a Windows executable. It was not locally prototyped because PyInstaller already established the feasibility and approximate lower bound for this decision. [Nuitka user manual](https://nuitka.net/user-documentation/user-manual.html)

### Embeddable CPython

Python's Windows documentation defines the embeddable distribution as a minimal, almost fully isolated application-local runtime. It intentionally omits `pip`; third-party packages should be installed alongside it and treated as vendored application components. The application is responsible for the Microsoft C Runtime. Python recommends either a specialized launcher or directly invoking the included `python.exe`/`pythonw.exe`; the latter exposes Python as the process identity. [Python 3.13 embeddable distribution](https://docs.python.org/3.13/using/windows.html#the-embeddable-package)

That model fits a pyRevit extension folder: the MCP host can launch `<extension>/runtime/python.exe <extension>/main.py`, while the in-Revit extension remains on pyRevit's engine. It does not fit an auto-updating `pip` environment; each extension release must replace a tested Python-and-wheels bundle.

### Bundled or external `uv`

`uv` is itself available as a standalone Windows binary and can automatically download a missing Python runtime. `uv run` ensures a project environment agrees with its lockfile before running a command. It can operate offline only from locally available files/cache. Thus shipping `uv.exe` removes the user's manual installation step, but a genuinely offline first run requires also shipping the runtime and dependency artifacts—the same material a frozen or embedded bundle already contains. [uv installation](https://docs.astral.sh/uv/getting-started/installation/), [uv-managed Python downloads](https://docs.astral.sh/uv/guides/install-python/), [uv project execution](https://docs.astral.sh/uv/concepts/projects/run/), [uv offline option](https://docs.astral.sh/uv/reference/cli/)

## Signing and antivirus behavior

No packaging mechanism can promise that endpoint security will accept every release. Microsoft says SmartScreen evaluates publisher reputation and file-hash reputation. An unsigned downloaded executable normally produces an unknown-publisher warning and may be non-bypassable under enterprise policy. A valid OV/EV signature identifies the publisher and lets publisher reputation accumulate, but even a newly signed binary may initially warn. Microsoft recommends signing every release with a consistent identity and not modifying files after signing. [Microsoft SmartScreen reputation guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)

PyInstaller maintainers track antivirus false positives as a recurring issue around its common bootloader and advise signing distributed executables. This is evidence of risk, not evidence that a particular build will be detected. [PyInstaller antivirus false-positive issue](https://github.com/pyinstaller/pyinstaller/issues/6754)

The local signature check found:

- the downloaded official CPython 3.13.14 `python.exe` had a valid Python Software Foundation Authenticode signature;
- the official `uv` 0.12.3 Windows release `uv.exe` was unsigned;
- the locally built PyInstaller probe was unsigned, as expected before a project signing step.

No artifact was submitted to VirusTotal or an antivirus vendor, and no conclusion about detection rate is warranted. The release requirement should be Authenticode signing and timestamping of project-built executable artifacts, plus a clean Windows security smoke test. Microsoft's `SignTool` is the standard Windows tool for signing, verifying, and timestamping files. [Microsoft SignTool documentation](https://learn.microsoft.com/en-us/dotnet/framework/tools/signtool-exe)

## Local experiments

All experiments ran on Windows 11 x64. They used Python 3.12.10 for PyInstaller, official MCP Python SDK 2.0.0, PyInstaller 6.22.0, official CPython 3.13.14 embeddable x64, and official `uv` 0.12.3 x64. The probe was the SDK's documented minimal shape: instantiate `MCPServer`, register a `ping` tool, call `mcp.run()` under the main guard, and then launch with empty stdin so the stdio process exits cleanly.

### Compatibility probe

- Installing MCP SDK 2.0.0 succeeded with binary wheels for its native Windows dependencies, including `pydantic-core`, `cryptography`, `cffi`, `rpds-py`, and `pywin32` on CPython 3.12 and 3.13 x64.
- Importing the current repository entry point against SDK 2.0 failed with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, matching the official migration guide.
- The repository's `httpx` import must be made explicit or ported because SDK 2.0 no longer installs `httpx`.

### PyInstaller probe

- One-folder: 45,346,597 bytes (43.25 MiB), 143 files; three import/start/EOF runs took 1,578 ms, 805 ms, and 853 ms.
- One-file: 22,919,172 bytes (21.86 MiB); three runs took 1,997 ms, 2,577 ms, and 2,631 ms.
- Both returned exit code 0. PyInstaller emitted one non-fatal warning that hidden import `tzdata` was not found.

The final Revit helper needs a real frozen-server conformance test because dynamic imports, package metadata, images/data, and task-extension code can require PyInstaller hooks that the minimal probe did not exercise.

### Embeddable CPython probe

- Official CPython archive: 10.46 MiB.
- Runtime plus MCP SDK 2.0 wheels: 77,042,925 logical bytes (73.47 MiB), 2,817 files; zipped with PowerShell at optimal compression: 31.94 MiB.
- The default `python313._pth` needed explicit `packages`, `packages\\win32`, `packages\\win32\\lib`, and `packages\\pythonwin` entries plus `import site` so the vendored `pywin32` layout could resolve `pywintypes`.
- Three import/start/EOF runs took 720 ms, 695 ms, and 744 ms.

This is viable, but the `pywin32` path adjustment demonstrates why the bundle must be built and tested as an application rather than populated by running `pip` on the user's machine.

### Bundled `uv` probe

- Official release ZIP: 19,013,455 bytes (18.13 MiB); extracted `uv.exe`: 48,024,064 bytes (45.80 MiB).
- With isolated `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR`, a cold `uv run --managed-python --python 3.13 --with mcp==2.0.0` downloaded CPython and packages, completed the import in 16.2 s, and accumulated 194.56 MiB of logical state.
- A persistent locked project later measured a 43.62 MiB logical virtual environment, 185.33 MiB of logical managed-Python/cache data, and a 1.16 s warm import.
- One project provisioning attempt failed while updating a generated Windows PE launcher with `Access is denied`; an immediate retry succeeded. The experiment does not identify the locking process, but it is a concrete reason to require retry/recovery and enterprise endpoint-security testing if this route is chosen.

`uv` uses hardlinks and deduplication, so sums of file lengths can overstate allocated disk space. They still describe the visible application material and show that bundled `uv` is a bootstrap strategy, not a smaller self-contained runtime.

## Revit and pyRevit compatibility

The helper remains a separate Windows process. Consequently, Python 3.10+/MCP SDK compatibility is not coupled to pyRevit's IronPython or CPython engine, and none of the packaging options requires loading MCP packages inside Revit. The Revit-facing half of this repository is a normal pyRevit startup extension that registers `routes.API("revit_mcp")`; its manifest currently declares no extension dependencies. [Current startup module](https://github.com/NateZwainleskPLA/pyrevit-mcp/blob/51b4829655b5a9822da16e13644158722e060f84/startup.py), [current extension manifest](https://github.com/NateZwainleskPLA/pyrevit-mcp/blob/51b4829655b5a9822da16e13644158722e060f84/extension.json)

pyRevit's current source documents separate builds for Revit 2017–2027, and its Routes API exposes `routes/sisters` specifically to enumerate other servers on the same machine. That establishes architectural compatibility with multi-instance discovery, not that this extension has been tested across every such Revit release. [pyRevit supported-version source](https://github.com/pyrevitlabs/pyRevit/blob/develop/CLAUDE.md#supported-revit-versions), [pyRevit Routes sisters API](https://docs.pyrevitlabs.io/reference/pyrevit/routes/api/#get_sisters)

The packaging decision should therefore impose **no new Revit-version floor**. The specification should name a tested pyRevit/Revit matrix separately and require a pyRevit version that actually provides the Routes behavior used by the implementation. This research did not establish the oldest released pyRevit version with all required Routes semantics, so it should not invent one. At minimum, packaging CI should test the latest supported pyRevit release and each Revit year the project explicitly promises.

## Recommended specification decision

1. Ship the helper as a project-built, Authenticode-signed Windows-x64 PyInstaller executable inside the pyRevit extension; let the MCP host launch it on demand over stdio. Start production work in one-folder mode for diagnosability, then ship one-file if full conformance and endpoint-security tests pass. Keep one-folder as the fallback artifact.
2. Require no user-managed Python, `pip`, or `uv` in the preferred path, but keep a documented `uv run --locked` developer/support path as the gelatinous escape hatch.
3. Do not bundle `uv` merely to avoid telling the user to install it. Choose it only if automatic online provisioning and its larger mutable user cache are consciously preferred over a release-built binary.
4. Port and pin MCP SDK 2.x before packaging. Drop `[cli]` from the production dependency set, migrate the helper's HTTP client to `httpx2` or declare `httpx` directly, and lock all Windows-x64 dependencies.
5. Build on Windows CI, record hashes/SBOM, sign and timestamp the final executable, then test it on a clean supported Windows machine with no Python or `uv` installed. The smoke test must cover process launch, stdio MCP discovery/tool listing, one routed no-op call, clean shutdown, and the temporary-directory/crash behavior of one-file mode.
6. Treat the helper binary as part of the extension release. Do not self-update it independently; extension rollback must restore matching helper and Revit-route code.

## Remaining facts for later decisions

- Which code-signing identity/service the project will use.
- Whether the pyRevit extension distribution channel tolerates a roughly 22 MiB binary and how it handles delta updates/history.
- The explicit pyRevit/Revit acceptance matrix and oldest Routes implementation the project promises.
- Whether Codex's MCP configuration can point directly to an executable stored under the installed extension path on every supported installation scope.
- Whether the finished SDK 2.x helper freezes without extra hooks once Tasks, routing, document targeting, and image responses are included.
