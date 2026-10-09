# Nested tilt assembly: reconstruction lessons

Reviewed 2026-10-08. This retrospective covers a separate agent-driven
2025-to-2024 family reconstruction, not a run of the repository helper.

## Evidence and distribution limits

The review examined extraction/rebuild scripts, source/target samples, the final
RFA and machine-readable validation. The delivered RFA's hash matched the
validation record. Tests were not independently rerun during the review.
The original family and detailed run artifacts are not distributed with this
repository. Treat the results as reported case evidence, not a reproducible
public acceptance fixture. Reusable guidance is bundled in the skill's
[reconstruction reference](../../.agents/skills/revit-family-backport/references/reconstruction.md).

## What the case establishes

The reviewed assembly is a nested Specialty Equipment family with
One Level Based placement, native plates/hardware, void cuts, visibility,
type selection and formula-clamped instance tilt. Source build was
Revit 2025 `25.5.0.57`; target build was Revit 2024 `24.3.50.51`.

The validation records four target types and 28 family-editor cases at requested
angles -45, -30, -15, 0, 15, 30 and 45 degrees, with actual tilt clamped to ±30.
It also records 20 independently placed project instances, fresh changes to
length, width, offset and component-span controls individually and together,
and reopening the saved target.

Sampled exterior bounds differed by at most approximately 0.000001164 mm.
Summed API solid volumes differed by approximately 0.00455%–0.00985%, with two
additional solids per assembly. These measurements support close sampled
geometry and functional behavior. They leave exact quantities and complete
authoring equivalence unproven. Some construction dimensions were unresolved;
one rivet lost its editable revolution sketch; render assets were not rebuilt.

The case increases confidence that complex reconstruction is feasible with
focused agent work. It does not expand the repository helper's supported
content or establish arrays, connectors, shared/reporting parameters, lookup
tables, arbitrary hosting, or Revit 2022 support.

## Mechanisms to retain

**Rebuild children before parents.** Preserve a dependency graph, map target
symbols, then wire Family Type parameters and nested instance associations.
Numeric source ElementIds cannot identify target symbols. Record type aliases;
the whitespace-only source type became `Default` in this case.

**Map references by their roles and geometry.** The scripts rebuilt reference
planes and model/reference curves, matched planar faces, and used named nested
instance references where available. They then recreated labeled linear/angular
dimensions, equal-segment constraints and locked alignments. Angular dimension
display geometry needed interpretation in the actual hinge plane. A generic
adapter should require an unambiguous reference match and report unresolved
references; copying stable-reference suffixes or choosing the closest face is
not sufficient proof of portable reference identity.

**Validate full placement frames.** Nested placement restored host references,
work-plane flipping and rotation, then checked target axes against source axes.
A neutral bounding box cannot establish a correct hinge, orientation or host.
Future fixtures should separately exercise mirrors and handedness, which this
case does not establish generally.

**Distinguish fixed geometry from moving geometry.** Target automatic sketch
dimensions attached five fixed upright profiles to moving base reference planes.
The successful workaround isolated those extrusions in an editable nested family,
a fixed-parts child, and retained visibility associations. Treat this as a
diagnosed structural substitution: identify the unintended coupling, document
the changed family organization, and retest the controls. It is not a default
conversion rule.

**Measure tolerances in the target runtime.** A source rivet profile contained a
0.663 mm edge against an observed target ShortCurveTolerance of about 0.780 mm.
That feature used FreeFormElement with a revolved solid and Boolean cut; other
forms retained native sketches. This preserves a limited shape at an explicit
editability cost. The recorded maximum profile endpoint adjustment was about
0.0774 mm. Neither number is a universal repair tolerance; record actual endpoint
movement and confirm holes/cuts survive any repair.

**Inspect hidden imports before rebuilding them.** All 13 CAD imports were hidden,
but the agent rebuilt planar curves as DXF and corrected view-specific visibility.
The user later confirmed omission would have been acceptable here. For another
family, inspect visibility across relevant types/views and dependent dimensions,
alignments or other driving references. Present a concrete omission choice when
the preference is unresolved. Approval for this case does not authorize dropping
hidden content from every family. Preserve the original CAD internals only if
that is part of the agreed result; planar curve reconstruction did not preserve
layers/colors/file internals.

## Failure and document handling to strengthen

Copied-family or nested-edit workflows were reported to return an already-open
document. Verify the returned document's actual path, identity and ownership
before mutation. Close only newly owned documents. Keep user review copies
separate from build/test copies.

The observed constraint dialog offered deletion of elements as a warning
resolution. Capture severity, failure definition, message and failing/additional
ids before handling failures. Roll back geometry-deleting or family auto-repair
failures, and verify transaction status and required geometry after each trial.
Install failure handling before flexing a newly reconstructed constraint graph.

The final builder and family sampler deleted warnings except those selected by
an English message substring. Consequently, zero saved warnings and no reported
test warnings do not establish that no warnings occurred during construction or
flex. Retain the rollback mechanism, but replace broad text-based suppression
with recorded, explicitly classified failure handling. Report observed,
suppressed and unresolved failures separately. This caveat does not invalidate
the recorded geometry comparisons; it limits the warning claim.

## Next adapters and acceptance fixtures

Progress from simple families to assemblies:

1. Reconstruct a labeled rectangular profile using reference planes, sketch
   references, equality constraints and locked alignments. Flex two dimensions
   independently and together, save/reopen and place in a project. This extends
   the existing extrusion slice without relying on a whole assembly.
2. Build a parent with one editable child, a Family Type selector, instance
   associations and a rotated work-plane placement. Compare child identity,
   selection, transform and behavior after save/reopen.
3. Add native blends/revolutions and explicit void/cut maps with independent
   geometry evidence. Use narrowly approved fallbacks only where needed.
4. Exercise a hinge assembly and diagnosed fixed-part isolation. Create a
   redistributable fixture for this pattern; record expected organization,
   editability and quantity differences explicitly.

The scripts contain source IDs, family names, special-case axes and explicit
dimension omissions. Extract individual mechanisms into tested adapters rather
than registering those scripts as a general MCP conversion tool. Zero/one
arrays still need the separate compatibility investigation and fixtures in
[the API research](family-backport.md).
