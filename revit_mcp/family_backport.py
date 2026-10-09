# -*- coding: utf-8 -*-
"""Family API evidence and a deliberately small native reconstruction seam.

IronPython 2.7 compatible. Importing this module does not require Revit.
Call inside Revit's API context; source RFAs are opened in the background.
"""
import os
import json
from contextlib import contextmanager
from .family_backport_contract import SCHEMA_VERSION, VISIBILITY_FIELDS, compatibility_report, compare_manifests


def _id(value):
    return int(value.Value) if hasattr(value, "Value") else int(value.IntegerValue)


def _name(value, DB):
    try:
        return value.Name
    except AttributeError:
        return DB.Element.Name.__get__(value)


def _xyz(point):
    return [point.X, point.Y, point.Z]


def _curve(curve, DB):
    if isinstance(curve, DB.Line) and curve.IsBound:
        return {"kind": "Line", "start": _xyz(curve.GetEndPoint(0)), "end": _xyz(curve.GetEndPoint(1))}
    if isinstance(curve, DB.Arc) and curve.IsBound:
        return {"kind": "Arc", "start": _xyz(curve.GetEndPoint(0)), "end": _xyz(curve.GetEndPoint(1)),
                "mid": _xyz(curve.Evaluate(0.5, True))}
    return {"kind": curve.GetType().Name}


def _builtin_values(element, names, DB):
    values = {}
    for name in names:
        parameter = element.get_Parameter(getattr(DB.BuiltInParameter, name))
        if parameter:
            values[name] = parameter.AsInteger()
    return values


def _reference_target(element, DB):
    """Semantic reference evidence; source ids remain diagnostic only."""
    result = {"kind": element.GetType().Name, "name": _name(element, DB)}
    if isinstance(element, DB.ReferencePlane):
        result.update({"bubble": _xyz(element.BubbleEnd), "free": _xyz(element.FreeEnd),
                       "normal": _xyz(element.Normal)})
    elif isinstance(element, DB.Level):
        result["elevation"] = element.Elevation
    return result


def _unsupported_evidence(element, document, DB):
    values = []
    for p in element.Parameters:
        storage = str(p.StorageType)
        value = None
        if p.HasValue:
            if storage == "Double":
                value = p.AsDouble()
            elif storage == "Integer":
                value = p.AsInteger()
            elif storage == "String":
                value = p.AsString()
            elif storage == "ElementId":
                reference = document.GetElement(p.AsElementId())
                value = _reference_target(reference, DB) if reference else _id(p.AsElementId())
        values.append({"name": p.Definition.Name, "storage": storage, "value": value})
    return {"id": _id(element.Id), "kind": element.GetType().Name, "name": _name(element, DB),
            "category_id": _id(element.Category.Id) if element.Category else None,
            "parameters": sorted(values, key=lambda v: (v["name"], v["storage"]))}


def _template_signature(item):
    if "references" in item:
        return {k: v for k, v in item.items() if k not in ("id", "references")}
    return {k: v for k, v in item.items() if k != "id"}


def apply_template_baseline(manifest, baseline):
    """Distinguish unchanged template settings/constraints from authored content.

    Multiset matching retains extra or changed elements as blockers. Baseline
    items stay in the evidence; this does not validate arbitrary document settings.
    """
    manifest["template_evidence"] = {"version": baseline["source"]["version"], "matched": {}}
    for key in ("dimensions", "unsupported_elements"):
        remaining = list(baseline["features"].get(key, []))
        authored = []
        matched = []
        for item in manifest["features"].get(key, []):
            signature = _template_signature(item)
            index = next((i for i, candidate in enumerate(remaining) if _template_signature(candidate) == signature), None)
            if index is None:
                authored.append(item)
            else:
                matched.append(signature)
                remaining.pop(index)
        manifest["features"][key] = authored
        manifest["template_evidence"]["matched"][key] = sorted(matched, key=lambda v: json.dumps(v, sort_keys=True))
        # Missing template constraints are meaningful: the destination template
        # must not silently reintroduce something the source author removed.
        if key == "dimensions" and remaining:
            manifest["inspection_errors"].append("Source lacks constraints present in the supplied template baseline")
    return manifest


FAMILY_SETTINGS = ("FAMILY_SHARED", "FAMILY_WORK_PLANE_BASED", "FAMILY_ALWAYS_VERTICAL",
                   "FAMILY_CAN_HOST_REBAR", "FAMILY_ALLOW_CUT_WITH_VOIDS")
FORM_PARAMETERS = ("EXTRUSION_START_PARAM", "EXTRUSION_END_PARAM", "IS_VISIBLE_PARAM", "MATERIAL_ID_PARAM")


@contextmanager
def transaction_scope(document, title, DB, execution=None):
    """Use connector-owned scopes when the host exposes execution helpers."""
    if execution is not None:
        with execution.transaction(document, title):
            yield
        return
    transaction = DB.Transaction(document, title)
    transaction.Start()
    try:
        yield
        if transaction.Commit() != DB.TransactionStatus.Committed:
            raise RuntimeError("Transaction did not commit")
    finally:
        if transaction.GetStatus() == DB.TransactionStatus.Started:
            transaction.RollBack()


@contextmanager
def rollback_scope(document, title, DB, execution=None):
    if execution is not None:
        with execution.rollback_scope(document, title):
            yield
        return
    group = DB.TransactionGroup(document, title)
    group.Start()
    try:
        yield
    finally:
        group.RollBack()


def _extrusion(element, manager, DB):
    plane = element.Sketch.SketchPlane.GetPlane()
    associations = {}
    association_parameter_ids = {}
    for name in FORM_PARAMETERS:
        parameter = element.get_Parameter(getattr(DB.BuiltInParameter, name))
        family_parameter = manager.GetAssociatedFamilyParameter(parameter) if parameter else None
        if family_parameter:
            associations[name] = family_parameter.Definition.Name
            association_parameter_ids[name] = _id(parameter.Id)
    visibility = element.GetVisibility()
    material = element.get_Parameter(DB.BuiltInParameter.MATERIAL_ID_PARAM)
    volume = 0.0
    for geometry in element.get_Geometry(DB.Options()):
        if isinstance(geometry, DB.Solid):
            volume += geometry.Volume
    return {"id": _id(element.Id), "solid": element.IsSolid, "start": element.StartOffset,
            "end": element.EndOffset, "visible": element.Visible,
            "plane": {"origin": _xyz(plane.Origin), "x": _xyz(plane.XVec), "y": _xyz(plane.YVec)},
            "profile": [[_curve(c, DB) for c in loop] for loop in element.Sketch.Profile],
            "subcategory": _name(element.Subcategory, DB) if element.Subcategory else None,
            "material_id": _id(material.AsElementId()) if material else -1,
            "visibility": {k: bool(getattr(visibility, k)) for k in VISIBILITY_FIELDS},
            "associations": associations, "association_parameter_ids": association_parameter_ids, "volume": volume}


def _parameter_value(family_type, parameter):
    if not family_type.HasValue(parameter):
        return None
    storage = str(parameter.StorageType)
    methods = {"Double": "AsDouble", "Integer": "AsInteger", "String": "AsString", "ElementId": "AsElementId"}
    if storage not in methods:
        return None
    value = getattr(family_type, methods[storage])(parameter)
    return {"storage": storage, "value": _id(value) if storage == "ElementId" else value}


def inspect_document(document, DB, sample_types=True, execution=None):
    """Extract native definitions plus a rollback-only sample of each named type.

    Sampling requires a writable family and no enclosing transaction; every
    transaction is contained in an explicitly rolled-back group. Failures are
    evidence gaps, never silently treated as preserved features.
    """
    if not document.IsFamilyDocument:
        raise ValueError("Expected a loadable family document")
    manager = document.FamilyManager
    parameters = list(manager.Parameters)
    family_types = list(manager.Types)
    elements = list(DB.FilteredElementCollector(document).WhereElementIsNotElementType())
    extrusions = sorted([e for e in elements if isinstance(e, DB.Extrusion)], key=lambda e: _id(e.Id))
    errors = []
    result = {
        "schema_version": SCHEMA_VERSION,
        "units": "Revit internal units: feet, radians and internal spec units; no display-string conversion",
        "source": {"version": document.Application.VersionNumber, "build": document.Application.VersionBuild,
                   "path": document.PathName, "title": document.Title,
                   "category_id": _id(document.OwnerFamily.FamilyCategory.Id),
                   "category": _name(document.OwnerFamily.FamilyCategory, DB),
                   "placement": str(document.OwnerFamily.FamilyPlacementType),
                   "family_settings": _builtin_values(document.OwnerFamily, FAMILY_SETTINGS, DB)},
        "current_type": manager.CurrentType.Name if manager.CurrentType else None,
        "parameters": [], "parameter_order": [p.Definition.Name for p in manager.GetParameters()],
        "types": [], "extrusions": [], "type_samples": [],
        "reference_planes": [], "features": {}, "inventory": {}, "inspection_errors": errors,
    }
    for p in sorted(parameters, key=lambda p: p.Definition.Name):
        definition = p.Definition
        result["parameters"].append({
            "name": definition.Name, "id": _id(p.Id),
            "builtin": (int(definition.BuiltInParameter) if hasattr(definition, "BuiltInParameter")
                        and definition.BuiltInParameter != DB.BuiltInParameter.INVALID else 0),
            "data_type": definition.GetDataType().TypeId, "group": definition.GetGroupTypeId().TypeId,
            "instance": p.IsInstance, "shared": p.IsShared, "guid": str(p.GUID) if p.IsShared else None,
            "formula": p.Formula, "reporting": p.IsReporting, "read_only": p.IsReadOnly,
            "storage": str(p.StorageType),
            "associated_parameters": [{"element_id": _id(a.Element.Id), "parameter_id": _id(a.Id),
                                       "name": a.Definition.Name} for a in p.AssociatedParameters],
        })
    for family_type in sorted(family_types, key=lambda t: t.Name):
        result["types"].append({"name": family_type.Name,
                                "values": {p.Definition.Name: _parameter_value(family_type, p) for p in parameters}})
    sketch_members = set()
    for extrusion in extrusions:
        try:
            result["extrusions"].append(_extrusion(extrusion, manager, DB))
            sketch_members.update(_id(i) for i in extrusion.Sketch.GetAllElements())
        except Exception as exc:
            errors.append("Extrusion {}: {}".format(_id(extrusion.Id), exc))
    features = {key: [] for key in ("arrays", "dimensions", "nested_instances", "connectors", "lookup_tables",
                                   "other_forms", "unsupported_elements", "custom_subcategories")}
    result["features"] = features
    # Template/application infrastructure is recorded but does not define modeled content.
    infrastructure = set(("ViewPlan", "ViewSection", "View3D", "ViewSchedule", "ViewSheet", "ViewDrafting",
                          "SketchPlane", "Sketch", "Material", "AppearanceAssetElement", "PropertySetElement",
                          "GraphicsStyle", "Level", "ProjectInfo", "Family", "ParameterElement",
                          "SharedParameterElement", "DataStorage", "SunAndShadowSettings", "InternalOrigin"))
    for element in elements:
        class_name = element.GetType().Name
        result["inventory"][class_name] = result["inventory"].get(class_name, 0) + 1
        eid = _id(element.Id)
        if isinstance(element, DB.ReferencePlane):
            result["reference_planes"].append({"id": eid, "name": _name(element, DB), "bubble": _xyz(element.BubbleEnd),
                "free": _xyz(element.FreeEnd), "normal": _xyz(element.Normal),
                "settings": _builtin_values(element, ("ELEM_IS_REFERENCE", "DATUM_PLANE_DEFINES_ORIGIN"), DB)})
        elif isinstance(element, DB.BaseArray):
            features["arrays"].append({"id": eid, "kind": class_name, "count": element.NumMembers,
                "label": element.Label.Definition.Name if element.Label else None,
                "original_member_ids": [_id(i) for i in element.GetOriginalMemberIds()],
                "copied_member_ids": [_id(i) for i in element.GetCopiedMemberIds()]})
        elif isinstance(element, DB.Dimension):
            try:
                label = element.FamilyLabel
            except Exception:
                label = None
            features["dimensions"].append({"id": eid, "locked": element.IsLocked,
                "label": label.Definition.Name if label else None,
                "reference_targets": [_reference_target(document.GetElement(r.ElementId), DB) for r in element.References],
                "curve": _curve(element.Curve, DB) if element.Curve else None,
                "references": [{"element_id": _id(r.ElementId), "source_stable_reference": r.ConvertToStableRepresentation(document)} for r in element.References]})
        elif isinstance(element, DB.FamilyInstance):
            features["nested_instances"].append({"id": eid, "family": _name(element.Symbol.Family, DB),
                "type": _name(element.Symbol, DB), "shared": element.Symbol.Family.IsShared,
                "host_id": _id(element.Host.Id) if element.Host else None})
        elif isinstance(element, DB.ConnectorElement):
            features["connectors"].append({"id": eid, "kind": class_name})
        elif isinstance(element, DB.GenericForm) and not isinstance(element, DB.Extrusion):
            features["other_forms"].append({"id": eid, "kind": class_name})
        elif isinstance(element, DB.Extrusion) or eid in sketch_members or class_name in infrastructure:
            pass
        else:
            features["unsupported_elements"].append(_unsupported_evidence(element, document, DB))
    result["reference_planes"].sort(key=lambda p: (p["name"], p["bubble"]))
    category = document.OwnerFamily.FamilyCategory
    features["custom_subcategories"] = sorted(_name(c, DB) for c in category.SubCategories if _id(c.Id) >= 0)
    try:
        tables = DB.FamilySizeTableManager.GetFamilySizeTableManager(document, document.OwnerFamily.Id)
        if tables:
            features["lookup_tables"] = list(tables.GetAllSizeTableNames())
    except Exception as exc:
        errors.append("Lookup tables: {}".format(exc))
    if sample_types and family_types:
        with rollback_scope(document, "Back-port type inspection (rollback)", DB, execution):
            for family_type in sorted(family_types, key=lambda t: t.Name):
                with transaction_scope(document, "Sample family type", DB, execution):
                    manager.CurrentType = family_type
                    document.Regenerate()
                    result["type_samples"].append({"name": family_type.Name,
                        "extrusions": [_extrusion(e, manager, DB) for e in extrusions]})
    return result


def inspect_file(application, file_path, expected_version, DB, execution=None, template_path=None):
    """Open an RFA in the background, inspect, close without saving or UI changes."""
    if str(expected_version) != application.VersionNumber:
        raise ValueError("Wrong Revit endpoint: expected {}, received {}".format(expected_version, application.VersionNumber))
    if not os.path.isabs(file_path) or os.path.splitext(file_path)[1].lower() != ".rfa":
        raise ValueError("Provide an absolute .rfa path on the Revit machine")
    if not os.path.isfile(file_path):
        raise ValueError("RFA does not exist on the Revit machine")
    info = DB.BasicFileInfo.Extract(file_path)
    try:
        if info.Format != str(expected_version):
            raise ValueError("RFA format {} differs from expected {}; inspection never upgrades a file".format(info.Format, expected_version))
    finally:
        info.Dispose()
    normalized = os.path.normcase(os.path.realpath(file_path))
    for existing in application.Documents:
        if existing.PathName and os.path.normcase(os.path.realpath(existing.PathName)) == normalized:
            raise ValueError("RFA is already open; inspect an on-disk copy to avoid sampling the user's document")
    document = application.OpenDocumentFile(file_path)
    try:
        manifest = inspect_document(document, DB, execution=execution)
        if template_path:
            baseline = inspect_template(application, template_path, expected_version, DB)
            apply_template_baseline(manifest, baseline)
        return manifest
    finally:
        document.Close(False)


def inspect_template(application, template_path, expected_version, DB):
    if not os.path.isabs(template_path) or not os.path.isfile(template_path) or os.path.splitext(template_path)[1].lower() != ".rft":
        raise ValueError("Provide an existing absolute source-version .rft template")
    info = DB.BasicFileInfo.Extract(template_path)
    try:
        if info.Format != str(expected_version) or application.VersionNumber != str(expected_version):
            raise ValueError("Template baseline must belong to the running Revit version")
    finally:
        info.Dispose()
    baseline = application.NewFamilyDocument(template_path)
    try:
        return inspect_document(baseline, DB, sample_types=False)
    finally:
        baseline.Close(False)


def register_family_backport_routes(api):
    from pyrevit import routes, DB
    import json

    @api.route("/family_backport/inspect/", methods=["POST"])
    def inspect_family_backport(uiapp, request):
        # uiapp is also the pyRevit Routes marker that marshals this handler
        # through ExternalEvent. It works with no active document.
        try:
            data = json.loads(request.data) if isinstance(request.data, str) else request.data
            manifest = inspect_file(uiapp.Application, data["file_path"], data["expected_version"], DB,
                                    template_path=data.get("template_path"))
            return routes.make_response(data={"status": "success", "manifest": manifest,
                "compatibility": compatibility_report(manifest, data.get("target_version", 2024))})
        except Exception as exc:
            return routes.make_response(data={"status": "error", "error": str(exc)})
