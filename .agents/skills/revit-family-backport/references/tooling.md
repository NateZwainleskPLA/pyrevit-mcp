# pyrevit-mcp tools and setup

This skill requires a Revit-connected agent with file access and Python API
execution on the Revit host. Its folder can be copied into a skill directory;
keep `references/` and `scripts/` alongside `SKILL.md`. The tools and reconstruction
modules come from a pyrevit-mcp installation or checkout containing this feature.
Copying the skill alone does not install an MCP server or Revit extension.

## Runtime routing

Confirm tool availability and execution semantics before using a connector.
This branch uses explicit runtime handles. Discover sessions with
`list_revit_targets`, then pass the source runtime's `target` handle to inspection
and the target runtime's handle to reconstruction code execution. Application
execution and file inspection need no existing document selector. Document-scoped
execution additionally requires an explicit `document` handle.

The inspection route verifies the actual Revit version against
`expected_version`. New route/tool registration requires reloading the pyRevit
extension and restarting the MCP server.

Use `execute_revit_application_code` for background document creation/save/close
and set `transaction_mode='script'` for the helper's owned transactions. It
provides `app`, `DB`, `revit` and `execution`; there is no selected `doc`/`uidoc`.
Other connectors may expose different tool names or require a disposable document
handle. Use their declared contract; avoid an outer model transaction around
multi-document operations. File inspection uses the same process safety guard
and application document checks as application execution.

## Evidence tools

| Tool | Inputs and result |
| --- | --- |
| `inspect_family_backport` | Source runtime `target`, absolute RFA `file_path`, `expected_version`, `target_version`, optional matching `template_path`. Returns the manifest, feature inventory and assessment without saving the source. |
| `assess_family_backport` | Manifest and `target_version`. Runs outside Revit and reports unsupported or unresolved content. |
| `compare_family_backport` | Source and target manifests; optional numeric tolerance in Revit internal units. Compares supported native evidence and retains unsupported content as unverified. |

The helper currently reconstructs into Revit 2024: unhosted Generic Models with
named types, solid native line/arc-profile extrusions, constant profiles across
types, ordinary scalar parameters/formulas, supported reference planes and
extrusion start/end or visibility associations. Authored dimensions/constraints,
void cuts, nested families, arrays, shared/reporting parameters, materials,
lookup tables, connectors and custom subcategories require additional adapters.
Let the actual assessment decide eligibility; this list is not a substitute for
its checks.

## Helper invocation

`revit_mcp.family_backport_rebuild.reconstruct_family` is an agent-invoked Python
helper, not an MCP conversion tool. It needs a matching target-version template,
an unused absolute output filename and an existing output directory. It creates
and closes its own background document, compares before saving and returns
`validation_failed` / `saved: false` when evidence differs.

For a checkout not installed in the running extension, use the bundled
[loader](../scripts/load_api.py). It isolates imports without replacing the
installed `revit_mcp` package. Set the following paths from the host's installation
and the current task; all are paths accessible to Revit:

```python
import imp
import json
import os

# Set skill_directory, repository_path, manifest_path,
# target_template_path and output_path before executing.
loader = imp.load_source(
    'backport_loader', os.path.join(skill_directory, 'scripts', 'load_api.py'))
api = loader.load_api(repository_path)
with open(manifest_path, 'r') as stream:
    manifest = json.load(stream)
result = api.reconstruct_family(
    app, manifest, target_template_path, output_path, DB,
    execution=globals().get('execution'))
print(json.dumps(result))
```

For direct inspection, the loaded module provides
`inspect_file(application, rfa_path, expected_version, DB, execution=None,
template_path=None)`. Passing connector-owned execution helpers is optional;
otherwise the helper owns its native transactions and rollback groups.

Templates are task inputs: use source/target templates of the correct versions,
category, placement, units and language. Category reassignment alone does not
reproduce hosting infrastructure. Verify availability on the Revit machine
rather than assuming an English template name or a default installation path.
