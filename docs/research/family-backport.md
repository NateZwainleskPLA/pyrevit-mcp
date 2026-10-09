# Family Back Port: feasibility and API research

Research date: 2026-10-07. Initial tested-version goal: Revit 2025 source to Revit 2024 target. This note is based on Autodesk documentation and a comparison of the installed Autodesk `RevitAPI.xml` files. No live reconstruction or model mutation was performed for this research; documented API availability is not evidence of a successful round trip.

## Product scope

The desired output is an editable native RFA that retains parametric behavior as far as possible. Begin with one simple, non-nested family. Add nested families later. Revit 2022 is a deferred extension, not part of the first milestone. An agent should inspect, plan, reconstruct, and verify through focused tools, rather than invoke a universal one-shot converter. Verified substitutions that preserve behavior may run automatically; substitutions that lose behavior require a user decision.

## Feasibility

Autodesk confirms that newer RFAs cannot be opened in older Revit releases. Its documented IFC workaround can make content available in an older release, but the article does not establish preservation of native parametric geometry, formulas, constraints, reference semantics, or MEP behavior. It therefore does not satisfy this project's acceptance criterion by itself. [Autodesk backward-family compatibility](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Is-it-possible-to-use-Revit-Families-created-in-an-Newer-version-in-Old-Version-of-Revit.html)

A supported reconstruction route exists: extract supported objects and relationships while running the source Revit API, create a new family using a target-version template in target Revit, rebuild the supported objects, and save using target Revit. `Application.NewFamilyDocument(templateFileName)` creates the destination document; Autodesk's family creation labs demonstrate native extrusions, alignments, dimensions, types, formulas, materials, and parameter associations. This is a feasible architecture for an explicitly supported subset, not proof that arbitrary families can be serialized and recreated losslessly. [NewFamilyDocument](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/bc292c96-bc2b-04ab-726b-575d92be61fd.htm), [Autodesk family API labs](https://blog.autodesk.io/revit-family-creation-api-labs/)

The central difficulty is reconstructing the dependency graph. A solid with the right shape and a list of matching parameters may still have lost the constraints that connect those parameters to its sketch. Geometry, types, references, labeled dimensions, locked alignments, element parameter associations, and formulas must be compared separately.

The first native extrusion slice has now passed live 2025-to-2024 fixture tests;
see [the validation record](family-backport-validation.md) for builds, geometry,
formula flex, instance visibility and remaining limits. This changes the evidence
for that supported subset, not the unresolved coverage for general families.

A separate agent rebuilt a nested tilt assembly in 2024. Its recorded
flex/placement evidence, reference and nesting mechanisms, targeted structural
substitutions, and warning-handling limitations are reviewed in
[the nested assembly case](family-backport-case-study.md). This supplies design
evidence for later complex fixtures; the repository helper's supported subset
remains unchanged.

Live inspection confirmed that the stock Generic Model template already contains
a locked level/reference-plane alignment and internal settings elements. The
implementation compares these against an explicit same-version template baseline
instead of treating them as authored content. It retains changed or extra
relationships as blockers. Template-wide settings are outside the validated
cross-version preservation scope.

For parameter spec/group comparison, Autodesk's default `ForgeTypeId` equality is
`NameEquals`, which compares the type ID up to the first hyphen and excludes its
schema version. Thus built-in Length IDs ending in `2.0.0` and `2.0.1` can be
semantically equal; the raw IDs remain recorded in the manifests. Revit 2024 API XML (Installed Autodesk equality contract)

## API evidence

Primary API evidence comes from Autodesk's release-specific `RevitAPI.xml`
documentation shipped beside `RevitAPI.dll`. Locate these files in the source
and target installations rather than assuming an installation drive or path.
The matrix identifies the members to inspect; XML citation labels below refer
to the 2024/2025 files reviewed for this research. Public Autodesk links provide
additional portable references. Installed builds may differ, so verify contracts
against the runtime used for reconstruction.

## 2025 to 2024 compatibility matrix

| Capability | Extraction in 2025 | Reconstruction in 2024 | Finding and required verification |
| --- | --- | --- | --- |
| Parameter list and order | `FamilyManager.GetParameters()` | `GetParameters()`, `ReorderParameters(...)` | Present in both. Lists include invisible and built-in parameters; UI order is grouped. Do not recreate every returned parameter as a user-defined parameter. Revit 2025 API XML (2025 list), Revit 2024 API XML (2024 order) |
| Parameter group and data type | `Definition.GetGroupTypeId()`, `GetDataType()` | `AddParameter(string, ForgeTypeId, ForgeTypeId, bool)` | Common ForgeTypeId APIs exist in both. Data type can be a spec, a category for Family Type parameters, or empty for special built-ins. A category must use the category overload; an empty ID is not an ordinary parameter type. Revit 2025 API XML (2025 definition), Revit 2024 API XML (2024 creation) |
| Shared parameter identity | `FamilyParameter.IsShared`, `GUID`, definition metadata | `ExternalDefinitionCreationOptions.GUID`, shared `AddParameter(ExternalDefinition, ForgeTypeId, bool)` | APIs exist in both. Preserve GUID explicitly; creation otherwise generates a new GUID. Shared definition recreation and metadata preservation need a fixture. Revit 2025 API XML (2025 GUID), Revit 2025 API XML (definition GUID) |
| Types and scalar values | `FamilyManager.Types`, `FamilyType.AsDouble/AsInteger/AsString/AsElementId` | `NewType`, `CurrentType`, `Set` overloads | Present in both. Values must be interpreted by StorageType and preserved in internal units. ElementId values require a destination-object mapping, not numeric copying. Parameter values cannot be set without a current type. Revit 2025 API XML (2025 values), Revit 2024 API XML (2024 setters), Revit 2024 API XML (2024 current type) |
| Formulas | `FamilyParameter.Formula`, `CanAssignFormula`, `IsDeterminedByFormula` | `FamilyManager.SetFormula` | Present in both. Create referenced parameters and at least one family type first. Circular dependencies and parameters that cannot receive formulas can fail. Successful assignment must be followed by flex testing. Revit 2024 API XML (2024 formula contract) |
| Element-to-family parameter associations | `GetAssociatedFamilyParameter(Parameter)`; `FamilyParameter.AssociatedParameters` | `CanElementParameterBeAssociated`, `AssociateElementParameterToFamilyParameter` | Present in both. Preserve which target element parameter is driven by which family parameter. Matching by displayed parameter name alone is ambiguous. Type compatibility and association support must be checked. Revit 2025 API XML (2025 read), Revit 2024 API XML (2024 write) |
| Reference planes | `BubbleEnd`, `FreeEnd`, `Normal`, `Direction`, `Name`, `GetReference()` | `FamilyCreate.NewReferencePlane` / `NewReferencePlane2` | Present in both. Recreate geometric orientation and preserve relevant element parameters such as reference strength and origin behavior where supported; positional similarity alone is insufficient. Revit 2025 API XML (2025 reference), Revit 2025 API XML (2025 creation contract, also present in 2024) |
| Native extrusion | `Extrusion.Sketch`, `StartOffset`, `EndOffset`, `GenericForm.IsSolid` | `FamilyCreate.NewExtrusion(bool, CurveArrArray, SketchPlane, double)`, offsets | Present in both. Preserve profile loops, plane orientation, solid/void state, signed offsets, material and visibility associations. Closed coplanar nonintersecting loops are required. Creation can split full circles/ellipses; index-for-index curve matching is unsafe. Revit 2025 API XML (2025 offsets/sketch), Revit 2025 API XML (creation contract) |
| Sketch-owned elements | `Sketch.Profile`, `Sketch.GetAllElements()`, profile `Curve.Reference.ElementId` | Enumerate target sketch elements after native creation | Both expose sketch model curves, reference planes, and dimensions. Autodesk explicitly documents matching a profile curve to its ModelCurve through `Curve.Reference.ElementId`. This is a useful extraction seam; target references still need geometric/semantic remapping. Revit 2025 API XML (2025 sketch members), Revit 2024 API XML (2024 counterpart) |
| Dimensions and labels | `Dimension.References`, `FamilyLabel`, geometry, lock/equality properties | `FamilyCreate.NewLinearDimension(...)`, `Dimension.FamilyLabel`; other dimensional forms need adapters | Common family linear-dimension creation exists in both. References must be rebuilt in target geometry. Reporting parameters drive from dimension values; ordinary parameters drive dimensions. Multi-segment reporting labels are unsupported. Revit 2025 API XML (2025 references), Revit 2024 API XML (2024 labels), Revit 2025 API XML (common family constructor) |
| Locked alignment | Dimensions/references and constraint inspection | `FamilyCreate.NewAlignment(view, reference1, reference2)` | Present in both through ItemFactoryBase. References must already be geometrically aligned; this method does not move them into alignment. Creation success does not prove all original constraints were found. Revit 2024 API XML (2024 contract) |
| 2025 linear-dimension class | `LinearDimension` is new and derives from `Dimension` | Use common family creation API returning Dimension | `LinearDimension.Create` is absent in 2024. Inspect through the base Dimension type rather than require exact source runtime class equality. Revit 2025 API XML (2025 new class/method), [Autodesk API change notes](https://help.autodesk.com/view/RVT/2025/ENU/?caas=caas%2Fblog%2Fthebuildingcoder.typepad.com%2Fblog%2F2024%2F04%2Fwhats-new-in-the-revit-2025-api.html) |
| Arrays and count labels | `BaseArray.Label`, `NumMembers`, original/copied IDs; 2025 placeholder-aware methods | `LinearArray.Create`, `RadialArray.Create`, `BaseArray.Label` | Core arrays exist in both, but 2025 family counts 0/1 need substitutions in 2024. API creation ranges and placeholder semantics differ; see below. Revit 2025 API XML (2025 label), Revit 2024 API XML (2024 label) |
| Embedded lookup tables | `FamilySizeTableManager`, table names/data or CSV export | Manager creation and `ImportSizeTable` | Present in both. Preserve table names, headers, units, and formulas referencing them. Treat import Boolean/error information as verification inputs. A table and a type catalog are different artifacts. Revit 2025 API XML (2025 export), Revit 2025 API XML (import), Revit 2024 API XML (2024 manager) |

The local diff also confirms removal in 2025 of old `BuiltInParameterGroup` overloads for family parameter creation/replacement and the `Definition.ParameterGroup` property. Use `GetGroupTypeId()` and the ForgeTypeId overloads shared by 2024 and 2025. This is an adapter issue, not a reason to translate groups to localized display names.

## References and missing extraction fidelity

Stable reference strings are documented for restoration where the **same document** is present, including across sessions. They are based on internal Revit structure and are not a portable schema for a recreated family. Do not copy source reference strings into a new target document and assume they still identify equivalent faces or curves. Revit 2025 API XML (Stable representation contract)

`Curve.Reference` may be null for curves created, copied, or transformed by the API, and for non-referenceable geometry. Save source element identity and sketch ownership while the original reference is available; reacquire real target references after creation. Revit 2025 API XML (Curve reference contract)

The first extractor should inventory relationships, even when the first reconstructor cannot yet recreate them. Specifically:

- Dimensions and locked alignments involving sketch model curves, reference planes, faces, or edges.
- Parameter associations for extrusion start/end/depth, material, visibility, and other element properties.
- Reference plane semantics and template-origin relationships.
- All family types and formulas, plus a documented range of instance-parameter flex samples.
- Unsupported forms, imported geometry, cutters/cut relationships, hosted components, annotation labels, connectors, and nested families.

A feature that is not extracted cannot be called preserved because the output looks similar. Unsupported or unresolved relationships must appear in the plan and result report. The agent may use existing focused execution tools to investigate a specific supported API path; it must not infer success from an empty warnings list produced by an incomplete collector.

Annotation text labels require a separate investigation from `Dimension.FamilyLabel`. Public API label editing has historically had gaps; Autodesk's developer blog describes configuring label behavior through an appropriate template/tag family. This older evidence is a reason for a dedicated capability spike, not a definitive claim that every current release lacks the same functionality. Annotation/tag/titleblock families are outside the first extrusion milestone. [Autodesk developer discussion](https://blog.autodesk.io/detach-workset-and-taskdialog-command-link-order/)

## Zero/one arrays: documented differences and candidate substitutions

Autodesk introduced zero/one counts for both linear and radial arrays in the Revit 2025 Family Editor. [Feature documentation](https://help.autodesk.com/cloudhelp/2025/ENU/Revit-WhatsNew/files/GUID-97BA5D8B-C737-47B4-9A69-7C7BA27DB19D.htm)

The installed API docs give a more specific compatibility boundary:

| Contract | Revit 2024 | Revit 2025 |
| --- | --- | --- |
| Linear API creation / validity | `IsValidArraySize(int)` and Create docs specify 2–200. | `IsValidNumberOfMembers(int, Document)` allows 0–200 in families, 2–200 in projects. |
| Radial API creation / validity | `IsValidArraySize(int)` and Create docs specify 3–200. | `IsValidNumberOfMembers(int, Document)` allows 0–200 in families, 3–200 in projects. |
| Minimum query | No document-sensitive `GetMinimumSize(Document)`. | Returns 0 for a family; 2 for project linear arrays, 3 for project radial arrays. |
| Placeholder query | No `GetNumberOfMembersIncludingPlaceholders()`. | Includes placeholders; `NumMembers` excludes them. |

Sources: Revit 2024 API XML (2024 linear validity), Revit 2024 API XML (2024 radial validity), Revit 2025 API XML (2025 linear additions), Revit 2025 API XML (2025 radial additions), Revit 2025 API XML (2025 count remarks).

The 2024 radial minimum above is the documented public API **creation contract**. Its `NumMembers` setter does not document a range in the inspected file. This research has not established whether a radial array created at three can later flex to two in the older Family Editor/API. Test that separately before deciding whether count two needs a substitution.

2025 `GetOriginalMemberIds()` returns original placeholders even at zero. `GetCopiedMemberIds()` returns copied placeholders for linear counts zero/one and radial counts below three. Extract array definitions from those structural members, not only from visible evaluated geometry. Revit 2025 API XML (Linear placeholders), Revit 2025 API XML (radial placeholders)

The inspected LinearArray, RadialArray, and BaseArray member lists expose creation inputs for anchor, translation, axis, and angle, but do not expose corresponding direct getters for those inputs. Recovering the original design intent therefore requires a separate investigation of members, element parameters, and associated dimensions/constraints. Inferring spacing from one evaluated configuration cannot by itself distinguish fixed-spacing from fixed-total-span behavior. Until this extraction path is verified, an array inventory is a compatibility detector rather than a complete portable array definition.

A candidate linear substitution is:

- Keep the public requested-count parameter.
- Drive a private native-array count with `if(RequestedCount < 2, 2, RequestedCount)`.
- Show that array branch when requested count is greater than one.
- Show a separately constrained single-member branch when requested count is one.
- Show neither branch when requested count is zero.

This requires a member whose visibility can actually be controlled without introducing forbidden nesting or changing behavior. Adding a visibility formula must preserve any existing visibility condition rather than replace it. If a radial array cannot flex to two using the 2024 API, it would need a minimum-three array branch plus separately constrained count-one/count-two branches. These are design hypotheses, not verified automatic conversions.

Before promoting an array adapter to preserving/automatic, verify:

- Counts zero, one, two, minimum native creation count, and representative larger counts; invalid values and the documented 200-member limit.
- Second-member versus last-member anchors, spacing/total-span formulas, radial axes/angles, and the position of the sole member.
- Constraint and formula behavior while switching counts repeatedly and changing independent dimensions.
- Existing visibility and detail-level settings, material/subcategory assignments, and host/cut behavior.
- Any relevant connectors, nested/shared scheduling, quantities, and loaded-project behavior. A hidden branch may differ semantically from a native zero/one array; this must be measured rather than assumed.
- Save, close, reopen in Revit 2024, reload into a 2024 project, and repeat the flex samples.

If only appearance is equivalent, or if unsupported shared instances/connectors/cuts remain, label the substitution as lossy and request the user's choice. Do not silently clamp the public count to two or delete the original formula.

## What Revit 2022 adds

Revit 2023 introduced filled regions directly in 3D families, new Mechanical Control Devices and Plumbing Equipment categories, MEP connector rehosting, and joinable casework geometry. A 2022 target therefore needs additional feature-specific analysis, including possible nested detail-item substitutes for filled regions and explicit decisions where category or join behavior changes. Those substitutions have not been validated. [Autodesk 2023 feature list](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-WhatsNew/files/GUID-2EFF582A-C7A4-42F8-8A3D-16317E08F0E4.htm)

Revit 2022 already introduced ForgeTypeId family parameter overloads, so it is reasonable to investigate reuse of the parameter representation. Autodesk's explanation distinguishes spec-valued parameters from category-valued Family Type parameters. Presence of these overloads does not verify all 2024 calls or all 2025 data types in 2022. [Autodesk API explanation](https://forums.autodesk.com/t5/revit-api-forum/revit-2022-parametertype-text-to-forgetypeid/td-p/10225741)

Revit 2024 changed ElementId storage to 64-bit. The portable representation must treat IDs as source-local handles and remap them to target elements, including when targeting a 32-bit-ID release; never truncate them or preserve them as destination identity. [Autodesk developer explanation](https://blog.autodesk.io/configuring-rvtsamples-2024/)

No installed 2022 API documentation was inspected for this note. A 2022 capability matrix, target templates, an actual running 2022 test environment, and equivalent reopening/flex tests are prerequisites for claiming support. Keep 2022 outside the first supported-version declaration.

## Runtime and version detection

Revit 2024 and earlier use .NET Framework 4.8; Revit 2025 originally moved to .NET 8. Revit 2025.5 and 2026.5 move to .NET 10, so year alone is insufficient when selecting compiled custom-tool dependencies. Probe installed/running build and runtime; retain version adapters at the Revit boundary. This does not change the need to execute source extraction and target reconstruction in their respective Revit processes. [Autodesk 2025 migration guide](https://help.autodesk.com/view/RVT/2025/ENU/?caas=caas%2Fblog%2Fthebuildingcoder.typepad.com%2Fblog%2F2024%2F04%2Fmigrating-from-net-48-to-net-core-8.html), [Autodesk runtime updates](https://blog.autodesk.io/autodesk-desktop-products-2025-2026-net-10-updates/)

## Staged agent-driven plan

1. **Inspect and establish the contract.** Identify source/target process and versions, inspect one RFA, classify its element and relationship inventory, and record preserving, lossy, unsupported, and unresolved features. Choose a matching target-version template. The agent presents material loss choices before dependent reconstruction.
2. **Native extrusion and parameter spike.** Rebuild a small supported profile as a native extrusion with types, user/shared parameters, scalar values, formulas, and supported element parameter associations. Preserve offsets, visibility, and material only where mapping is complete. Report unresolved profile constraints explicitly; this stage alone does not establish general parametric equivalence.
3. **Constraints and reference spike.** Recreate reference planes, sketch reference mappings, labeled dimensions, equality constraints, and locked alignments for representative simple families. Compare reference roles and relationships, not source/target element IDs.
4. **Flex and persist.** Compare each type and selected instance-parameter samples using parameter/formula/association records and geometry measurements; include constraints and errors. Save separately, reopen in target Revit, load into a target project, and repeat. Agent inspection/comparison tools should report unsupported evidence and measured differences.
5. **Array adapter spike.** Implement and test a narrow zero/one-array pattern with the invariants above. Keep unverified patterns as unresolved; approve automatic conversion only for demonstrated preserving patterns.
6. **Expand supported forms.** Add individual handlers for symbolic/model curves, further forms, lookup tables, materials, and hosting/void behavior. Each handler needs extraction completeness and persistence/flex evidence.
7. **Nested families later.** Add recursive dependency inspection, independently ported child families, target symbol mapping, shared behavior, parameter associations, and cycle/identity handling.
8. **Evaluate 2022 separately.** Diff its API against the implemented calls, identify category/filled-region/ID differences, and establish a 2022 fixture run before changing supported targets.

Suggested first acceptance fixtures are an unconstrained extrusion, an extrusion whose depth is associated to a formula-driven parameter, and a rectangular extrusion whose labeled dimensions/reference constraints control its profile. A successful first fixture must not be reported as evidence for the third. Preserve original RFAs; each output and report should state tested version/build, supported features, substitutions, losses, unresolved relationships, flex samples, and whether reopening/reloading was verified.
