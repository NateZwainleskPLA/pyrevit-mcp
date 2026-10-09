# Family Back Port validation

Status on 2026-10-07: the first native reconstruction slice passed live Revit
2025-to-2024 tests. Tested source build: `25.5.0.57`; target: `24.3.50.51`.
This validates the fixture cases below, not arbitrary family conversion.

## Live results

Both positive fixtures were created in background 2025 family documents,
inspected, reconstructed into new 2024 templates, saved as RFAs, closed, reopened
in 2024 and compared. Neither comparison reported differences or unresolved
features within the supported slice. SHA256 checks confirmed that source RFAs
were unchanged by inspection, and output RFAs were unchanged by inspection and
rollback-only trials. All test documents were owned disposable documents; user
families/projects were not changed.

- **ParametricExtrusion:** rectangular native extrusion; Short/Tall named types;
  ordinary scalar parameters; `End Depth = Depth * 2`; instance visibility
  association; parameter group/order; reference planes and inherited template
  constraint. Named-type solid volumes matched at 12 and 24 cubic feet.
- **Fresh flex:** in the reopened target family, setting Depth to 1.75 feet
  produced End Depth and extrusion end 3.5 feet, with volume 21 cubic feet.
  Setting Show Geometry to zero made the extrusion invisible. The trial rolled
  back, and the saved RFA's hash remained unchanged.
- **Project placement:** the target loaded into a disposable 2024 project and
  placed successfully. Its instance Show Geometry parameter was writable.
  Toggling 1 → 0 → 1 changed visible solid volume 12 → 0 → 12 cubic feet.
  The project was closed without saving.
- **ExtendedExtrusions:** two native extrusions, a two-arc circular profile,
  an oriented sketch plane, start offset 0.25 feet, nondefault fine/coarse
  visibility flags and an additional reference plane. The target reopened with
  two extrusions/four reference planes and matched the source evidence, including
  reference-plane normal orientation.
- **Authored constraint rejection:** a copied fixture with an extra authored
  linear dimension retained exactly that dimension as an unresolved feature,
  while the inherited template alignment matched its baseline. Assessment
  rejected reconstruction with the dimension blocker.
- **HTTP inspection route:** the real pyRevit Routes handler returned HTTP 200
  with a compatible manifest for the saved source fixture. Its `uiapp` argument
  triggers Revit ExternalEvent dispatch, including when no document is active.
  The source file hash remained unchanged. The isolated temporary validation
  route was removed after the check.

The previous recovery-required connector state was resolved by restarted Revit
sessions before these tests. No recovery block was bypassed. Failed development
trials rolled back owned transactions and closed background documents; the
connector reported `unsafe: false` with no cleanup errors for those failures.

## Artifacts and reproduction

The development run produced the following artifacts in a disposable output
directory. They are not distributed with the repository. Generate new artifacts
in `BACKPORT_FIXTURE_DIR` when reproducing the checks:

- `ParametricExtrusion-R25.rfa` / `ParametricExtrusion-R24.rfa`
- `ExtendedExtrusions-R25.rfa` / `ExtendedExtrusions-R24.rfa`
- `source-manifest.json` / `ParametricExtrusion-target-manifest.json`
- `extended-source-manifest.json` / `ExtendedExtrusions-target-manifest.json`
- `final-comparison-results.json`, `validation-result.json`,
  `placement-validation-result.json`, `extended-validation-result.json`, and
  `unsupported-validation-result.json`

These disposable artifacts are outside the tracked implementation. The source
fixture recipe is `tests/integration/family_backport_fixture.py`. Execute it in
2025 script transaction mode with `BACKPORT_REPO` set to this checkout and a fresh
absolute `BACKPORT_FIXTURE_DIR`. Set `BACKPORT_TEMPLATE` to an installed 2025
Generic Model RFT appropriate to the test installation. The default variant creates the parametric
fixture; `BACKPORT_FIXTURE_VARIANT='extended'` creates the extended case;
`'constraint'` creates the rejected authored-dimension case.

Inspect with the matching 2025 template baseline. Invoke reconstruction in 2024
using its Generic Model template and a new output filename. Inspect the saved
output with the matching 2024 baseline, compare manifests, and run fresh flex
and placement trials on disposable documents. On the integration-based branch,
use `execute_revit_application_code` with the source/target runtime's explicit
`target` handle and `transaction_mode='script'`. Use the agent skill for the API
loader and connector-owned transaction/rollback scopes.

## Offline checks

`uv run --extra test pytest tests/unit -q`: **109 passed**. Compilation, skill
validation, isolated API loader, MCP tool registration and diff whitespace checks
also passed.

Regression coverage includes source/output ownership, overwrite refusal, rollback,
validation-gated saving, unsupported content on either side, exact association
coverage, missing type samples, changed type geometry, closed-loop cyclic order,
ForgeTypeId name equality, and distinguishing unchanged template infrastructure
from changed/additional/missing constraints.

## Remaining scope

Authored sketch-driving dimensions/alignments, void cuts, shared/reporting
parameters, material assets, custom subcategories, lookup tables, connectors,
arrays and nested assemblies require additional reconstruction adapters. Their
presence remains explicit unresolved work; they were not silently simplified.
Revit 2022 is research-only. Arbitrary flex, application to other categories,
locales/templates, type catalogs and template-wide settings are not established
by these tests.
