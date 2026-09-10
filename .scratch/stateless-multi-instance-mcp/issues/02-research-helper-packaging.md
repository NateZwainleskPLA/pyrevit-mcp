# Research packaging an on-demand MCP helper within a pyRevit extension

Type: research
Status: resolved
Blocked by: none

## Question

Which technically viable packaging mechanisms can ship and launch the modern-Python MCP helper from one pyRevit extension without a persistent service, and what do primary sources and minimal local experiments establish about their user prerequisites, artifact size, signing and antivirus behavior, dependency compatibility, update burden, and supported Revit/pyRevit versions?

## Answer

[Packaging an on-demand MCP helper inside a pyRevit extension](../../../docs/research/pyrevit-mcp-helper-packaging.md) records the primary-source findings and Windows probes, originally captured on branch `research/pyrevit-helper-packaging` at commit `c46da3ea9edb871d60a5dd1e5ee54bde0493672e` and cherry-picked unchanged onto `master` as `58d7585`.

All three tested mechanisms are viable. Prefer a signed Windows-x64 PyInstaller artifact inside the extension: prove one-folder first, then ship the approximately 22 MiB one-file form if full conformance and endpoint-security tests pass. Embeddable CPython plus vendored wheels is a larger viable fallback. Bundled `uv` hides installation but adds an unsigned approximately 46 MiB launcher, first-run network behavior, and substantial managed runtime/cache state, so retain it as a support or developer escape hatch rather than the default. Porting to MCP Python SDK `2.0.0` is a prerequisite to production packaging.
