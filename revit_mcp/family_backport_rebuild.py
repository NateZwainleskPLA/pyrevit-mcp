# -*- coding: utf-8 -*-
"""Agent-invoked native extrusion reconstruction; not an automatic downgrade.

Only the explicitly supported slice is accepted. No source document is edited,
no existing output is overwritten, and evidence is compared before saving.
"""
import os
from .family_backport import inspect_document, apply_template_baseline, transaction_scope, _id, _name
from .family_backport_contract import compatibility_report, compare_manifests, VISIBILITY_FIELDS


def reconstruct_family(application, manifest, template_path, output_path, DB, execution=None):
    report = compatibility_report(manifest, 2024)
    if not report["ready_for_first_slice"]:
        raise ValueError("Reconstruction blocked: {}".format("; ".join(report["blockers"])))
    if application.VersionNumber != "2024":
        raise ValueError("Reconstruction must run inside Revit 2024")
    for path, extension in ((template_path, ".rft"), (output_path, ".rfa")):
        if not os.path.isabs(path) or os.path.splitext(path)[1].lower() != extension:
            raise ValueError("Expected an absolute {} path".format(extension))
    if not os.path.isfile(template_path):
        raise ValueError("Target-version template does not exist")
    if os.path.exists(output_path):
        raise ValueError("Output already exists; choose a new filename")
    if not os.path.isdir(os.path.dirname(output_path)):
        raise ValueError("Output directory does not exist")
    info = DB.BasicFileInfo.Extract(template_path)
    try:
        if info.Format != "2024":
            raise ValueError("Use a Revit 2024 family template")
    finally:
        info.Dispose()
    document = application.NewFamilyDocument(template_path)
    try:
        if _id(document.OwnerFamily.FamilyCategory.Id) != manifest["source"]["category_id"] or str(document.OwnerFamily.FamilyPlacementType) != manifest["source"]["placement"]:
            raise ValueError("Template category/hosting does not match source")
        baseline = inspect_document(document, DB, sample_types=False)
        _populate(document, manifest, DB, execution)
        target = inspect_document(document, DB, execution=execution)
        apply_template_baseline(target, baseline)
        comparison = compare_manifests(manifest, target)
        if comparison["status"] != "matched_supported_evidence":
            # Return evidence for the agent to diagnose; no degraded RFA is saved.
            return {"status": "validation_failed", "comparison": comparison, "manifest": target, "saved": False}
        options = DB.SaveAsOptions()
        options.OverwriteExistingFile = False
        document.SaveAs(output_path, options)
        return {"status": "success", "output_path": output_path, "comparison": comparison,
                "saved": True, "revit_version": application.VersionNumber}
    finally:
        document.Close(False)


def _populate(document, manifest, DB, execution=None):
    from System import Enum
    from System.Collections.Generic import List

    def builtin(value):
        return Enum.ToObject(DB.BuiltInParameter, value)

    def xyz(value):
        return DB.XYZ(*value)

    manager = document.FamilyManager
    with transaction_scope(document, "Reconstruct back-port native family", DB, execution):
        for name, value in manifest["source"]["family_settings"].items():
            p = document.OwnerFamily.get_Parameter(getattr(DB.BuiltInParameter, name))
            if not p or (p.AsInteger() != value and not p.Set(value)):
                raise ValueError("Cannot preserve family setting {}".format(name))
        parameters = {}
        for definition in manifest["parameters"]:
            if definition["builtin"]:
                p = manager.get_Parameter(builtin(definition["builtin"]))
                if p is None:
                    raise ValueError("Template lacks built-in parameter {}".format(definition["name"]))
            else:
                p = manager.get_Parameter(definition["name"])
                if p is None:
                    p = manager.AddParameter(definition["name"], DB.ForgeTypeId(definition["group"]),
                                             DB.ForgeTypeId(definition["data_type"]), definition["instance"])
            parameters[definition["name"]] = p
        if manifest.get("parameter_order"):
            manager.ReorderParameters(List[DB.FamilyParameter]([parameters[name] for name in manifest["parameter_order"]]))
        types = {}
        for source_type in manifest["types"]:
            existing = next((t for t in manager.Types if t.Name == source_type["name"]), None)
            family_type = existing or manager.NewType(source_type["name"])
            types[source_type["name"]] = family_type
            manager.CurrentType = family_type
            for name, value in source_type["values"].items():
                p = parameters[name]
                definition = next(d for d in manifest["parameters"] if d["name"] == name)
                if value is None or definition["formula"] or p.IsReadOnly:
                    continue
                if value["storage"] == "ElementId":
                    manager.Set(p, DB.ElementId(value["value"]))
                elif value["storage"] == "String" and value["value"] is None:
                    continue
                else:
                    manager.Set(p, value["value"])
        for definition in manifest["parameters"]:
            if definition["formula"]:
                manager.SetFormula(parameters[definition["name"]], definition["formula"])
        manager.CurrentType = types[manifest["current_type"] or manifest["types"][0]["name"]]
        document.Regenerate()
        # Reference-plane identities belong to this document, never to source ids.
        view = next(v for v in DB.FilteredElementCollector(document).OfClass(DB.ViewPlan) if not v.IsTemplate)
        for source_plane in manifest["reference_planes"]:
            existing = next((p for p in DB.FilteredElementCollector(document).OfClass(DB.ReferencePlane)
                             if _name(p, DB) == source_plane["name"] and
                             p.BubbleEnd.IsAlmostEqualTo(xyz(source_plane["bubble"])) and
                             p.FreeEnd.IsAlmostEqualTo(xyz(source_plane["free"]))), None)
            p = existing or document.FamilyCreate.NewReferencePlane(
                xyz(source_plane["bubble"]), xyz(source_plane["free"]),
                (xyz(source_plane["free"]) - xyz(source_plane["bubble"])).CrossProduct(xyz(source_plane["normal"])).Normalize(), view)
            p.Name = source_plane["name"]
            for name, value in source_plane["settings"].items():
                setting = p.get_Parameter(getattr(DB.BuiltInParameter, name))
                if setting.AsInteger() != value:
                    setting.Set(value)
        for source_form in manifest["extrusions"]:
            plane = source_form["plane"]
            sketch_plane = DB.SketchPlane.Create(document, DB.Plane.CreateByOriginAndBasis(
                xyz(plane["origin"]), xyz(plane["x"]), xyz(plane["y"])))
            profile = DB.CurveArrArray()
            for source_loop in source_form["profile"]:
                loop = DB.CurveArray()
                for curve in source_loop:
                    if curve["kind"] == "Line":
                        loop.Append(DB.Line.CreateBound(xyz(curve["start"]), xyz(curve["end"])))
                    else:
                        loop.Append(DB.Arc.Create(xyz(curve["start"]), xyz(curve["end"]), xyz(curve["mid"])))
                profile.Append(loop)
            form = document.FamilyCreate.NewExtrusion(True, profile, sketch_plane, source_form["end"] - source_form["start"])
            form.StartOffset = source_form["start"]
            form.EndOffset = source_form["end"]
            form.get_Parameter(DB.BuiltInParameter.IS_VISIBLE_PARAM).Set(int(source_form["visible"]))
            visibility = form.GetVisibility()
            for field in VISIBILITY_FIELDS:
                if getattr(visibility, field) != source_form["visibility"][field]:
                    setattr(visibility, field, source_form["visibility"][field])
            form.SetVisibility(visibility)
            for name, family_name in source_form["associations"].items():
                manager.AssociateElementParameterToFamilyParameter(
                    form.get_Parameter(getattr(DB.BuiltInParameter, name)), parameters[family_name])
        document.Regenerate()
