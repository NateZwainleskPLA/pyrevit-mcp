# -*- coding: utf-8 -*-
"""Execute in Revit 2025 via execute_revit_application_code, in script transaction mode.

Set BACKPORT_REPO to this checkout, BACKPORT_TEMPLATE to an installed Revit 2025
Generic Model RFT and BACKPORT_FIXTURE_DIR to a new absolute directory. Creates
only a disposable background family. Never modifies the provided doc/uidoc.
"""
import os
import imp

loader = imp.load_source("backport_fixture_loader", os.path.join(
    BACKPORT_REPO, ".agents", "skills", "revit-family-backport", "scripts", "load_api.py"))
api = loader.load_api(BACKPORT_REPO)

if app.VersionNumber != "2025":
    raise ValueError("Fixture creation requires Revit 2025")
template_path = globals().get("BACKPORT_TEMPLATE")
if not template_path or not os.path.isabs(template_path) or not os.path.isfile(template_path):
    raise ValueError("Set BACKPORT_TEMPLATE to an absolute Revit 2025 Generic Model RFT path")
if not os.path.isabs(BACKPORT_FIXTURE_DIR):
    raise ValueError("Set an absolute BACKPORT_FIXTURE_DIR")
if not os.path.isdir(BACKPORT_FIXTURE_DIR):
    os.makedirs(BACKPORT_FIXTURE_DIR)
extended = globals().get("BACKPORT_FIXTURE_VARIANT") == "extended"
constraint = globals().get("BACKPORT_FIXTURE_VARIANT") == "constraint"
filename = "AuthoredConstraint-R25.rfa" if constraint else ("ExtendedExtrusions-R25.rfa" if extended else "ParametricExtrusion-R25.rfa")
fixture_path = os.path.join(BACKPORT_FIXTURE_DIR, filename)
if os.path.exists(fixture_path):
    raise ValueError("Fixture already exists")
family = app.NewFamilyDocument(template_path)
try:
    with api.transaction_scope(family, "Create disposable family back-port fixture", DB,
                               globals().get("execution")):
        manager = family.FamilyManager
        depth = manager.AddParameter("Depth", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
        end_depth = manager.AddParameter("End Depth", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
        visible = manager.AddParameter("Show Geometry", DB.GroupTypeId.Graphics, DB.SpecTypeId.Boolean.YesNo, True)
        for name, value in (("Short", 1.0), ("Tall", 2.0)):
            manager.NewType(name)
            manager.Set(depth, value)
            manager.Set(visible, 1)
        manager.SetFormula(end_depth, "Depth * 2")
        plane = DB.SketchPlane.Create(family, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Zero))
        points = [DB.XYZ(0, 0, 0), DB.XYZ(2, 0, 0), DB.XYZ(2, 3, 0), DB.XYZ(0, 3, 0)]
        loop = DB.CurveArray()
        for i in range(4):
            loop.Append(DB.Line.CreateBound(points[i], points[(i + 1) % 4]))
        loops = DB.CurveArrArray()
        loops.Append(loop)
        form = family.FamilyCreate.NewExtrusion(True, loops, plane, 4.0)
        manager.AssociateElementParameterToFamilyParameter(form.get_Parameter(DB.BuiltInParameter.EXTRUSION_END_PARAM), end_depth)
        manager.AssociateElementParameterToFamilyParameter(form.get_Parameter(DB.BuiltInParameter.IS_VISIBLE_PARAM), visible)
        if extended:
            form.StartOffset = 0.25
            visibility = form.GetVisibility()
            visibility.IsShownInFine = False
            visibility.IsShownInCoarse = False
            form.SetVisibility(visibility)
            curved = DB.CurveArray()
            curved.Append(DB.Arc.Create(DB.XYZ(5, 0, 0), DB.XYZ(7, 0, 0), DB.XYZ(6, 1, 0)))
            curved.Append(DB.Arc.Create(DB.XYZ(7, 0, 0), DB.XYZ(5, 0, 0), DB.XYZ(6, -1, 0)))
            curved_profile = DB.CurveArrArray()
            curved_profile.Append(curved)
            oriented = DB.SketchPlane.Create(family, DB.Plane.CreateByOriginAndBasis(
                DB.XYZ.Zero, DB.XYZ.BasisY, -DB.XYZ.BasisX))
            family.FamilyCreate.NewExtrusion(True, curved_profile, oriented, 1.5)
            view = next(v for v in DB.FilteredElementCollector(family).OfClass(DB.ViewPlan) if not v.IsTemplate)
            reference = family.FamilyCreate.NewReferencePlane(DB.XYZ(8, -5, 0), DB.XYZ(8, 5, 0), DB.XYZ.BasisZ, view)
            reference.Name = "Backport Test Plane"
        if constraint:
            view = next(v for v in DB.FilteredElementCollector(family).OfClass(DB.ViewPlan)
                        if v.ViewType == DB.ViewType.FloorPlan and not v.IsTemplate)
            a = family.FamilyCreate.NewReferencePlane(DB.XYZ(0, -5, 0), DB.XYZ(0, 5, 0), DB.XYZ.BasisZ, view)
            a.Name = "Acceptance Width Left"
            b = family.FamilyCreate.NewReferencePlane(DB.XYZ(2, -5, 0), DB.XYZ(2, 5, 0), DB.XYZ.BasisZ, view)
            b.Name = "Acceptance Width Right"
            family.Regenerate()  # Native references must be ready before dimension creation.
            references = DB.ReferenceArray()
            references.Append(a.GetReference())
            references.Append(b.GetReference())
            family.FamilyCreate.NewLinearDimension(view, DB.Line.CreateBound(DB.XYZ(0, 4, 0), DB.XYZ(2, 4, 0)), references)
        family.Regenerate()
    family.SaveAs(fixture_path)
    print("Created " + fixture_path)
finally:
    family.Close(False)
