---
name: revit-family-backport
description: Reconstruct a loadable Revit family in an earlier release using pyrevit-mcp, preserving native editability and testing parameter behavior. Use for RFA back-porting and compatibility assessment.
---

Produce a new RFA saved by the target Revit release, with evidence of preserved
geometry, parameter behavior and authoring editability. Native reconstruction
requires access to both source and target Revit runtimes.

The current helper supports a limited Revit 2025-to-2024 subset. Read
[tooling.md](references/tooling.md) for available tools, setup, inputs and helper
limits. General reconstruction guidance also applies to features requiring
focused API work; it does not expand the helper's supported content.

## Establish the preservation requirements

Identify the source family, target release, new output location and required
behavior. Resolve paths on the Revit host. Discover running versions/builds and
available templates from the actual installation; template names, units,
languages, locations and connector capabilities vary.

Separate three acceptance dimensions: geometry/appearance, behavior in families
and projects, and future authoring editability. Record required controls,
placement/hosting, nested/shared behavior, quantities and optional drafting or
rendering content where relevant. Apply demonstrated preserving substitutions
within the requested scope. Present concrete losses for a decision when the
existing requirements do not resolve them.

## Inspect the source

Inspect a saved disposable copy when the source is open. Preserve the original
file and user-owned documents. Verify returned document identity, path and
ownership before mutation; close only documents owned by the operation.

Use `inspect_family_backport` and retain the complete manifest. Supply a matching
source template baseline when known to distinguish unchanged infrastructure
from authored constraints. Assess with `assess_family_backport`. Extraction
errors, missing samples and unsupported relationships remain unresolved work.
Source IDs and stable references identify source evidence, not target objects.

For arrays, version differences or a release outside the supported pair, read
[compatibility.md](references/compatibility.md). For constraints, nested content,
voids, hidden imports or profile-tolerance failures, read
[reconstruction.md](references/reconstruction.md).

## Reconstruct and test

Use the supported helper when its assessment passes. Otherwise investigate
bounded native API adapters, retaining source-to-target object and reference
maps. Keep unsupported features in the assessment; editing the manifest to
remove blockers does not establish preservation.

Create child dependencies before parents, parameters before formulas, geometry
before its target references, and references before dimensions/alignments.
Preserve full sketch/placement frames and hosting. Verify substitutions through
behavioral tests before treating them as preserving.

Use the connector's documented transaction contract and owned rollback scopes
for disposable trials. Honor recovery-required execution blocks. Before flexing
new constraints, capture failures and roll back geometry-deleting or family
auto-repair resolutions. Record warnings before justified suppression.

Compare corresponding source/target types and fresh parameter inputs. Exercise
independent controls, combinations, boundaries and relevant project placement.
Measure holes/cuts, component placement and quantities where required; matching
outer bounds alone is insufficient. Keep suppressed warnings and unresolved
authoring relationships visible in the evidence.

## Deliver

Save separately, close the owned build document, reopen in the advertised target
release and repeat the relevant comparisons. `compare_family_backport` returning
`matched_supported_evidence` covers only its collected supported evidence.

Deliver the RFA and a report containing actual builds, tested inputs/results,
object maps, measured differences/tolerances, substitutions, approved omissions,
warning handling, editability limits and unverified behavior. State acceptance
for each preservation dimension; claim completion only for the agreed scope.
