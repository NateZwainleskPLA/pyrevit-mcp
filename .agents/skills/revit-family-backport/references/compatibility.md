# Release compatibility and array handling

Revit has no supported backward Save As for RFA files. Extract in the source
release and reconstruct/save in the target release. IFC geometry exchange does
not establish native parameter or constraint preservation.
[Autodesk family compatibility](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Is-it-possible-to-use-Revit-Families-created-in-an-Newer-version-in-Old-Version-of-Revit.html)

## Revit 2025 to 2024

Common API mechanisms include native form creation, family parameters and types,
formulas, parameter associations, reference planes, dimensions and alignments.
API availability alone does not establish extraction completeness or successful
reconstruction. Verify signatures and contracts in the installed release's
`RevitAPI.xml` beside its API assembly.

Use ForgeTypeId parameter type/group overloads shared by these releases; older
BuiltInParameterGroup overloads were removed in 2025. Family Type parameters
are category-valued and require target symbols; ordinary scalar parameters
are spec-valued. Preserve shared GUIDs, instance/type scope, formula dependencies
and parameter order where supported.

Inspect dimensional semantics through the common Dimension API: 2025 introduced
LinearDimension, while target 2024 uses common family creation methods. Reacquire
references on recreated target objects. Stable reference strings are document
specific and cannot serve as cross-document identities.

## Zero/one arrays

Revit 2025 introduced counts zero and one for linear and radial arrays in the
Family Editor. [Autodesk feature documentation](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-WhatsNew/files/GUID-97BA5D8B-C737-47B4-9A69-7C7BA27DB19D.htm)

The inspected 2024 API creation contracts permit linear counts 2–200 and radial
counts 3–200. These creation ranges do not establish every later setter or UI
behavior; in particular, radial flex to two requires a target-runtime probe.
In 2025, original/copied member queries can include structural placeholders even
when evaluated geometry is absent. Extract intent from members, labels,
dimensions and constraints, not visible count alone.

A possible substitute retains the public count, clamps a private native array
to its minimum, shows that branch above the minimum threshold and uses separately
constrained branches for smaller counts. This is an unverified pattern, not an
automatic conversion. Preserve existing visibility conditions and the distinction
between fixed spacing and fixed total span.

Before accepting such a substitute, test counts 0, 1, 2, 3 and a larger count;
repeated switching; anchors/sole-member position; spacing/span; independent
dimensions; detail visibility; cuts/hosts; nested/shared scheduling; quantities
and connectors when relevant. Save/reopen and repeat in a project. Hidden excess
members can change quantities or behavior even when appearance matches.

## Other targets

Revit 2022 remains unsupported by the current helper. Its parameter APIs may
permit reuse, but post-2022 features require separate treatment: 3D-family filled
regions, Mechanical Control Devices/Plumbing Equipment categories, connector
rehosting and joinable casework. ElementIds are source-local handles; account for
the 2024 transition to 64-bit storage without truncating or copying identities.
[Autodesk 2023 feature list](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-WhatsNew/files/GUID-2EFF582A-C7A4-42F8-8A3D-16317E08F0E4.htm)

Require an actual target runtime, matching templates, API contract checks and
save/reopen/flex evidence before declaring another release supported. Probe
actual build/runtime when introducing compiled dependencies; a release year
alone does not describe every runtime update.
