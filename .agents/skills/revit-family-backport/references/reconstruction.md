# Constraints, nesting and feature-specific reconstruction

These mechanisms require focused API work beyond the current extrusion helper.
Define an adapter's extraction evidence, reference mapping and behavioral checks
before declaring support.

## Constraints and reference mapping

Store sketch plane origin/axes, ordered profile loops including holes, curve
directions and signed offsets. Reacquire actual target sketch/face references
after creation. Map by object role, ownership and geometric evidence, rejecting
ambiguous matches. Record unresolved references explicitly.

Rebuild labeled dimensions, equal-segment constraints and locked alignments.
Angular dimension display geometry may differ from the mechanism's hinge plane.
Create controls in their actual reference frame. Compare unchanged template
infrastructure against an explicit matching baseline rather than discarding
unresolved dimensions as defaults.

Target automatic sketch constraints can attach fixed profiles to moving
references. Diagnose which geometry should move and which relationship causes
the failure. Isolating fixed forms in an editable child family is a possible
structural substitution; preserve associations and retest controls. Document
the changed organization rather than applying isolation to every family.

## Nested families and placement

Inspect the dependency graph and rebuild children before parents. Map target
symbols for type selectors and nested parameter associations. Preserve shared
identity/behavior where required. Detect duplicate identities and unresolved
dependencies rather than identifying every family by display name alone.

Store full placement transforms, host references, mirrors, work-plane flips and
rotation axes. Verify target frames and hosts after creation and after flex.
Neutral bounding boxes cannot prove a correct pivot or nested orientation.

## Geometry and tolerances

Prefer native forms with editable sketches and explicit void/cut relationships.
Query target Application.ShortCurveTolerance. Existing source geometry can
contain a feature that target sketch creation rejects; treat this as a measured
feature-level incompatibility rather than a fixed release-wide tolerance.

Record endpoint adjustments when closing small profile gaps. Choose tolerances
against required dimensions and verify slots/holes survive. Broad snapping can
change small features. A narrowly scoped FreeFormElement/Boolean fallback can
preserve a shape while losing sketch editability or parametric cut behavior;
state and resolve that particular loss before using it.

## Hidden imports and optional content

Inspect visibility across relevant types/views and dependent dimensions,
alignments and constraints. Hidden content can drive geometry or support future
editing. Present an omission choice when its preservation is unresolved, then
record accepted omissions and test affected behavior. Approval for one family
does not apply to other families.

If rebuilding CAD references from planar curves, verify transforms, view-specific
visibility and units. Such reconstruction does not preserve original CAD layers,
colors or file internals. Treat render assets/textures separately from material
names/colors and surface settings.

## Failures and acceptance

Capture severity, definition, text and failing/additional IDs before handling
transaction failures. Roll back resolutions that delete required geometry or
auto-repair the family. Verify transaction status, document validity and required
objects after a failed trial. Avoid classifying failures solely by an English
message substring. Record any suppressed warnings separately from saved warnings.

Test every named type, fresh independent controls and combined changes. For a
bounded control, include neutral, signed inputs, limits and beyond-limit values,
checking the actual formula result. Reopen the saved output and exercise
independent instances in a suitable project/host. Compare solid counts/volumes,
holes/cuts, placement and visuals as appropriate; distinguish functional
acceptance from complete restoration of authoring constraints.
