# -*- coding: utf-8 -*-
"""Portable family evidence and compatibility checks (CPython and IronPython 2.7).

No Revit imports: manifests can be reviewed and compared outside Revit.
"""
import math

SCHEMA_VERSION = 1
VISIBILITY_FIELDS = (
    "IsShownInFine", "IsShownInMedium", "IsShownInCoarse",
    "IsShownInLeftRight", "IsShownInFrontBack", "IsShownInTopBottom",
    "IsShownInPlanRCPCut", "IsShownOnlyWhenCut",
)


def check_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported family manifest schema")
    for field in ("source", "parameters", "types", "extrusions", "features", "type_samples"):
        if field not in manifest:
            raise ValueError("Manifest missing {}".format(field))
    for field in ("parameters", "types"):
        names = [item["name"] for item in manifest[field]]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate {} names".format(field))


def compatibility_report(manifest, target_version=2024):
    """Conservative boundaries for the first native-extrusion reconstruction slice.

    An agent may resolve blockers with separate, reviewed API work. A clear
    report is not permission to drop those features or an equivalence proof.
    """
    check_manifest(manifest)
    target_version = int(target_version)
    blockers = []
    notes = []
    if target_version != 2024:
        blockers.append("Only Revit 2024 reconstruction is implemented; 2022 is research-only.")
    if manifest["source"]["version"] not in ("2024", "2025"):
        blockers.append("This reconstruction slice is validated only for 2025 to 2024.")
    if manifest["source"].get("category_id") != -2000151:
        blockers.append("First reconstruction slice requires the Generic Models category.")
    if manifest["source"].get("placement") != "OneLevelBased":
        blockers.append("Hosted, adaptive and other placement modes need a dedicated adapter.")
    if not manifest["types"]:
        blockers.append("No named family types; create and inspect an explicit type first.")
    for issue in manifest.get("inspection_errors", []):
        blockers.append("Incomplete inspection: {}".format(issue))
    features = manifest["features"]
    for key in ("arrays", "dimensions", "nested_instances", "connectors", "lookup_tables",
                "other_forms", "unsupported_elements", "custom_subcategories"):
        if features.get(key):
            blockers.append("{} require agent reconstruction and validation before conversion.".format(key))
    if features.get("arrays") and target_version < 2025:
        notes.append("Zero/one arrays need tested substitutions; hiding members is not quantity equivalence.")
    for parameter in manifest["parameters"]:
        if parameter.get("shared") or parameter.get("reporting"):
            blockers.append("Parameter {} needs shared-GUID/reporting support.".format(parameter["name"]))
        if not parameter.get("builtin") and (parameter.get("storage") == "ElementId" or
                                               not parameter.get("data_type")):
            blockers.append("Parameter {} needs a data-type/reference adapter.".format(parameter["name"]))
        known_associations = set((e["id"], e.get("association_parameter_ids", {}).get(builtin_name))
                                 for e in manifest["extrusions"]
                                 for builtin_name, family_name in e.get("associations", {}).items()
                                 if family_name == parameter["name"])
        if any((a["element_id"], a["parameter_id"]) not in known_associations
               for a in parameter.get("associated_parameters", [])):
            blockers.append("Parameter {} has element associations requiring remapping.".format(parameter["name"]))
    for family_type in manifest["types"]:
        for name, value in family_type["values"].items():
            if value and value.get("storage") == "ElementId" and value.get("value", -1) >= 0:
                blockers.append("Type {} / {} references an element requiring remapping.".format(family_type["name"], name))
    for extrusion in manifest["extrusions"]:
        if not extrusion.get("solid"):
            blockers.append("Void extrusion cuts require a dedicated adapter.")
        if extrusion.get("subcategory"):
            blockers.append("Extrusion subcategories need reconstruction.")
        if extrusion.get("material_id", -1) >= 0:
            blockers.append("Extrusion materials/assets need reconstruction.")
        if any(c["kind"] not in ("Line", "Arc") for loop in extrusion["profile"] for c in loop):
            blockers.append("Extrusion profile contains unsupported curves.")
    # A constrained sketch can have a different evaluated profile in each type.
    # Recreating only the current sketch would freeze that behavior.
    baseline = {e["id"]: (e["plane"], e["profile"]) for e in manifest["extrusions"]}
    sampled = set()
    for sample in manifest["type_samples"]:
        sampled.add(sample["name"])
        shapes = {e["id"]: (e["plane"], e["profile"]) for e in sample["extrusions"]}
        if not _equal(baseline, shapes, 1e-8):
            blockers.append("Sketch geometry changes by type; recreate its driving constraints.")
    if sampled != set(t["name"] for t in manifest["types"]):
        blockers.append("Every named type must be sampled before reconstruction.")
    return {"target_version": target_version, "ready_for_first_slice": not blockers,
            "blockers": sorted(set(blockers)), "notes": notes,
            "validation_scope": "Named types and supported native properties; arbitrary flex is not proven."}


def _equal(a, b, tolerance):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) == type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return not (math.isnan(a) or math.isnan(b) or math.isinf(a) or math.isinf(b)) and abs(a - b) <= tolerance
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(
            _profiles_equal(a[k], b[k], tolerance) if k == "profile" else _equal(a[k], b[k], tolerance) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_equal(x, y, tolerance) for x, y in zip(a, b))
    return a == b


def _profiles_equal(a, b, tolerance):
    """Closed loops have no distinguished first curve; preserve curve direction."""
    if len(a) != len(b):
        return False
    remaining = list(b)
    for loop in a:
        match = next((i for i, candidate in enumerate(remaining) if len(loop) == len(candidate) and
                      any(_equal(loop, candidate[offset:] + candidate[:offset], tolerance)
                          for offset in range(len(candidate)))), None)
        if match is None:
            return False
        remaining.pop(match)
    return True


def _forge_name(value):
    # Match ForgeTypeId.NameEquals: Autodesk's default equality excludes the
    # schema version after the first hyphen. Keep raw TypeIds in the manifest.
    return value.split("-", 1)[0] if value else value


def _extrusion_evidence(extrusion):
    return {k: extrusion.get(k) for k in ("solid", "plane", "profile", "start", "end",
            "visible", "visibility", "subcategory", "associations", "material_id", "volume")}


def compare_manifests(source, target, tolerance=1e-7):
    """Compare evidence, excluding document-specific element ids and titles.

    Differences are explicit. Even matching unsupported families are unverified.
    """
    check_manifest(source)
    check_manifest(target)
    if tolerance <= 0 or math.isnan(tolerance) or math.isinf(tolerance):
        raise ValueError("Tolerance must be finite and positive (Revit internal units)")
    differences = []

    def compare(label, a, b):
        if not _equal(a, b, tolerance):
            differences.append({"field": label, "source": a, "target": b})

    for key in ("category_id", "placement", "family_settings"):
        compare(key, source["source"].get(key), target["source"].get(key))
    keys = ("name", "builtin", "data_type", "group", "instance", "shared", "guid", "formula", "reporting", "storage")
    def parameter_evidence(manifest):
        return [{k: _forge_name(p.get(k)) if k in ("data_type", "group") else p.get(k) for k in keys}
                for p in sorted(manifest["parameters"], key=lambda p: p["name"])]
    compare("parameters", parameter_evidence(source), parameter_evidence(target))
    compare("parameter_order", source.get("parameter_order"), target.get("parameter_order"))
    compare("template_constraints", source.get("template_evidence", {}).get("matched", {}).get("dimensions", []),
            target.get("template_evidence", {}).get("matched", {}).get("dimensions", []))
    compare("types", sorted(source["types"], key=lambda t: t["name"]), sorted(target["types"], key=lambda t: t["name"]))
    def planes(manifest):
        return [{k: v for k, v in p.items() if k != "id"} for p in manifest.get("reference_planes", [])]
    compare("reference_planes", planes(source), planes(target))
    # Use extraction order only for matching identical primitive graphs; ids are never portable.
    compare("extrusions", [_extrusion_evidence(e) for e in source["extrusions"]],
            [_extrusion_evidence(e) for e in target["extrusions"]])
    source_samples = {s["name"]: [_extrusion_evidence(e) for e in s["extrusions"]] for s in source["type_samples"]}
    target_samples = {s["name"]: [_extrusion_evidence(e) for e in s["extrusions"]] for s in target["type_samples"]}
    compare("named_type_geometry", source_samples, target_samples)
    report = compatibility_report(source, int(target["source"]["version"]))
    unverified = sorted(set(report["blockers"] + compatibility_report(target, int(target["source"]["version"]))["blockers"]))
    return {"status": "different" if differences else ("unverified" if unverified else "matched_supported_evidence"),
            "differences": differences, "unverified": unverified,
            "validation_scope": report["validation_scope"], "tolerance_internal_units": tolerance}
