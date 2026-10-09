"""Regression checks for preservation decisions, independent of Revit."""
import copy
import json
import pytest
from unittest.mock import MagicMock
import inspect
import sys
import types
from revit_mcp.family_backport_contract import compatibility_report, compare_manifests
from revit_mcp.family_backport import inspect_file, transaction_scope, rollback_scope, apply_template_baseline
from revit_mcp import family_backport_rebuild as rebuild
from tools.family_backport_tools import register_family_backport_tools
from tests.unit.test_receiver_target_routing import API, host
from tests.unit.test_target_identity import Document
from revit_mcp.execution_safety import ExecutionSafety
from revit_mcp.target_routing import TargetedAPI


@pytest.fixture
def manifest():
    form = {"id": 10, "solid": True, "plane": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0]},
            "profile": [[{"kind": "Line", "start": [0, 0, 0], "end": [1, 0, 0]}]],
            "start": 0, "end": 1, "volume": 1, "associations": {"EXTRUSION_END_PARAM": "Depth"},
            "visibility": {}, "visible": True, "material_id": -1, "subcategory": None}
    return {"schema_version": 1, "source": {"version": "2025", "category_id": -2000151,
            "placement": "OneLevelBased", "family_settings": {}},
            "parameters": [{"name": "Depth", "builtin": 0, "storage": "Double", "data_type": "length",
                            "formula": None, "group": "geometry", "instance": False}],
            "types": [{"name": "A", "values": {"Depth": {"storage": "Double", "value": 1}}}],
            "reference_planes": [], "extrusions": [form], "features": {}, "inspection_errors": [],
            "type_samples": [{"name": "A", "extrusions": [copy.deepcopy(form)]}]}


def target_of(manifest):
    target = copy.deepcopy(manifest)
    target["source"]["version"] = "2024"
    return target


def test_supported_evidence_matches_without_source_ids(manifest):
    target = target_of(manifest)
    target["extrusions"][0]["id"] = 200
    target["type_samples"][0]["extrusions"][0]["id"] = 200
    assert compare_manifests(manifest, target)["status"] == "matched_supported_evidence"


@pytest.mark.parametrize("feature", ["arrays", "dimensions", "nested_instances", "connectors", "lookup_tables",
                                     "other_forms", "unsupported_elements", "custom_subcategories"])
def test_matching_unsupported_content_is_never_called_verified(manifest, feature):
    manifest["features"][feature] = [{"id": 7}]
    assert compare_manifests(manifest, target_of(manifest))["status"] == "unverified"


def test_type_profile_changes_block_frozen_reconstruction(manifest):
    manifest["type_samples"][0]["extrusions"][0]["profile"][0][0]["end"][0] = 2
    assert any("driving constraints" in s for s in compatibility_report(manifest)["blockers"])


def test_missing_type_sampling_blocks_conversion(manifest):
    manifest["type_samples"] = []
    assert not compatibility_report(manifest)["ready_for_first_slice"]


def test_geometry_parameter_formula_and_association_loss_detected(manifest):
    target = target_of(manifest)
    target["extrusions"][0]["associations"] = {}
    target["parameters"][0]["formula"] = "2 * Width"
    target["type_samples"][0]["extrusions"][0]["volume"] = 2
    report = compare_manifests(manifest, target)
    assert {d["field"] for d in report["differences"]} == {"parameters", "extrusions", "named_type_geometry"}


def test_element_references_and_shared_guids_require_remapping(manifest):
    manifest["parameters"][0]["shared"] = True
    manifest["types"][0]["values"]["Material"] = {"storage": "ElementId", "value": 100}
    report = compatibility_report(manifest)
    assert len(report["blockers"]) == 2


def test_2022_is_explicitly_deferred(manifest):
    assert not compatibility_report(manifest, 2022)["ready_for_first_slice"]


@pytest.mark.parametrize("tolerance", [0, -1, float("nan"), float("inf")])
def test_invalid_tolerance_rejected(manifest, tolerance):
    with pytest.raises(ValueError):
        compare_manifests(manifest, target_of(manifest), tolerance)


async def test_inspection_tool_keeps_full_evidence(mock_mcp, mock_revit_post, manifest):
    response = {"status": "success", "manifest": manifest, "compatibility": compatibility_report(manifest)}
    mock_revit_post.return_value = response
    register_family_backport_tools(mock_mcp, mock_revit_post)
    result = json.loads(await mock_mcp.tools["inspect_family_backport"]("r1", "C:/family.rfa"))
    assert result == response
    mock_revit_post.assert_awaited_once_with("/family_backport/inspect/", {
        "file_path": "C:/family.rfa", "expected_version": 2025, "target_version": 2024}, None, timeout=120.0, target="r1")


async def test_inspection_requires_target_before_transport(mock_mcp, mock_revit_post):
    register_family_backport_tools(mock_mcp, mock_revit_post)
    with pytest.raises(TypeError, match="target"):
        await mock_mcp.tools["inspect_family_backport"](file_path="C:/family.rfa")
    mock_revit_post.assert_not_awaited()


@pytest.fixture
def targeted_inspection(host, manifest, monkeypatch):
    from revit_mcp import family_backport
    registry, _, _, uiapp, ids = host
    uiapp.ActiveUIDocument = None
    uiapp.Application.Documents = []
    sys.modules["pyrevit"].DB = MagicMock()
    reader = MagicMock(return_value=manifest)
    monkeypatch.setattr(family_backport, "inspect_file", reader)
    api, safety = API(), ExecutionSafety()
    family_backport.register_family_backport_routes(TargetedAPI(api, lambda: registry, safety=safety))
    payload = {key: ids[key] for key in ("instance_id", "runtime_id")}
    payload.update(file_path="C:/family.rfa", expected_version=2025)
    return api.handlers["/family_backport/inspect/"], uiapp, payload, safety, reader


def test_targeted_inspection_works_without_open_document(targeted_inspection):
    handler, uiapp, payload, safety, reader = targeted_inspection
    result = handler(uiapp, types.SimpleNamespace(method="POST", data=payload))
    assert result.status == 200 and result.data["status"] == "success"
    assert result.data["actual_target"] == {key: payload[key] for key in ("instance_id", "runtime_id")}
    assert result.data["opened_documents"] == []
    reader.assert_called_once()
    assert not safety.snapshot()["blocked"]


@pytest.mark.parametrize("condition,code", [
    ("blocked", "mutation_blocked"), ("wrong_runtime", "stale_target"),
    ("document_selector", "unexpected_document"), ("foreign_transaction", "modifiable_document")])
def test_targeted_inspection_rejects_before_sampling(targeted_inspection, condition, code):
    handler, uiapp, payload, safety, reader = targeted_inspection
    if condition == "blocked":
        safety.observe({"unsafe": True})
    elif condition == "wrong_runtime":
        payload["runtime_id"] = "00000000-0000-0000-0000-000000000000"
    elif condition == "document_selector":
        payload["document_id"] = "unrelated-document"
    else:
        document = Document(path="existing.rfa")
        document.IsModifiable = True
        uiapp.Application.Documents.append(document)
    result = handler(uiapp, types.SimpleNamespace(method="POST", data=payload))
    assert result.status == 409 and result.data["error_code"] == code
    reader.assert_not_called()


def test_targeted_inspection_leaked_transaction_blocks_later_sampling(targeted_inspection):
    handler, uiapp, payload, safety, reader = targeted_inspection
    def leak(*args, **kwargs):
        document = Document(path="temporary.rfa")
        document.IsModifiable = True
        uiapp.Application.Documents.append(document)
        return {}
    reader.side_effect = leak
    result = handler(uiapp, types.SimpleNamespace(method="POST", data=payload))
    assert result.status == 500 and result.data["unsafe"]
    assert safety.snapshot()["blocked"]
    again = handler(uiapp, types.SimpleNamespace(method="POST", data=payload))
    assert again.status == 409 and again.data["error_code"] == "mutation_blocked"
    reader.assert_called_once()


def test_wrong_endpoint_never_opens_source():
    application = MagicMock(VersionNumber="2024")
    with pytest.raises(ValueError, match="Wrong Revit endpoint"):
        inspect_file(application, "C:/family.rfa", 2025, MagicMock())
    application.OpenDocumentFile.assert_not_called()


def test_inspection_failure_closes_only_owned_document(tmp_path, monkeypatch):
    from revit_mcp import family_backport
    path = tmp_path / "source.rfa"
    path.touch()
    application = MagicMock(VersionNumber="2025", Documents=[])
    DB = MagicMock()
    DB.BasicFileInfo.Extract.return_value.Format = "2025"
    monkeypatch.setattr(family_backport, "inspect_document", MagicMock(side_effect=RuntimeError("geometry failure")))
    with pytest.raises(RuntimeError, match="geometry failure"):
        inspect_file(application, str(path), 2025, DB)
    application.OpenDocumentFile.return_value.Close.assert_called_once_with(False)
    application.OpenDocumentFile.return_value.Save.assert_not_called()
    DB.BasicFileInfo.Extract.return_value.Dispose.assert_called_once()


def test_existing_source_is_not_sampled_or_closed(tmp_path):
    path = tmp_path / "source.rfa"
    path.touch()
    existing = MagicMock(PathName=str(path))
    application = MagicMock(VersionNumber="2025", Documents=[existing])
    DB = MagicMock()
    DB.BasicFileInfo.Extract.return_value.Format = "2025"
    with pytest.raises(ValueError, match="already open"):
        inspect_file(application, str(path), 2025, DB)
    application.OpenDocumentFile.assert_not_called()
    existing.Close.assert_not_called()


def test_rebuild_refuses_overwrite_before_creating_document(manifest, tmp_path):
    template = tmp_path / "template.rft"
    output = tmp_path / "output.rfa"
    template.touch()
    output.write_bytes(b"existing family")
    application = MagicMock(VersionNumber="2024")
    with pytest.raises(ValueError, match="already exists"):
        rebuild.reconstruct_family(application, manifest, str(template), str(output), MagicMock())
    application.NewFamilyDocument.assert_not_called()
    assert output.read_bytes() == b"existing family"


def test_evidence_mismatch_never_saves_and_closes_destination(manifest, tmp_path, monkeypatch):
    template = tmp_path / "template.rft"
    template.touch()
    application = MagicMock(VersionNumber="2024")
    document = application.NewFamilyDocument.return_value
    document.OwnerFamily.FamilyCategory.Id.Value = -2000151
    document.OwnerFamily.FamilyPlacementType = "OneLevelBased"
    DB = MagicMock()
    DB.BasicFileInfo.Extract.return_value.Format = "2024"
    monkeypatch.setattr(rebuild, "_populate", MagicMock())
    target = target_of(manifest)
    target["parameters"][0]["formula"] = "Wrong formula"
    monkeypatch.setattr(rebuild, "inspect_document", MagicMock(return_value=target))
    result = rebuild.reconstruct_family(application, manifest, str(template), str(tmp_path / "output.rfa"), DB)
    assert result["status"] == "validation_failed"
    assert not result["saved"]
    document.SaveAs.assert_not_called()
    document.Close.assert_called_once_with(False)


def test_target_extra_unsupported_content_is_unverified(manifest):
    target = target_of(manifest)
    target["features"]["connectors"] = [{"id": 100}]
    assert compare_manifests(manifest, target)["status"] == "unverified"


def test_native_scope_rolls_back_on_exception():
    DB = MagicMock()
    DB.Transaction.return_value.GetStatus.return_value = DB.TransactionStatus.Started
    with pytest.raises(RuntimeError):
        with transaction_scope(MagicMock(), "trial", DB):
            raise RuntimeError("failure")
    DB.Transaction.return_value.RollBack.assert_called_once()
    DB.Transaction.return_value.Commit.assert_not_called()


def test_sampling_scope_always_rolls_back_group():
    DB = MagicMock()
    with pytest.raises(RuntimeError):
        with rollback_scope(MagicMock(), "sample", DB):
            raise RuntimeError("failure")
    DB.TransactionGroup.return_value.RollBack.assert_called_once()


def test_spec_versions_use_autodesk_name_equality(manifest):
    manifest["parameters"][0]["data_type"] = "autodesk.spec.aec:length-2.0.1"
    target = target_of(manifest)
    target["parameters"][0]["data_type"] = "autodesk.spec.aec:length-2.0.0"
    assert compare_manifests(manifest, target)["status"] == "matched_supported_evidence"
    target["parameters"][0]["data_type"] = "autodesk.spec.aec:area-2.0.0"
    assert compare_manifests(manifest, target)["status"] == "different"


def test_closed_profile_start_curve_is_not_a_geometry_difference(manifest):
    profile = [[{"kind": "Line", "start": [0, 0, 0], "end": [1, 0, 0]},
                {"kind": "Line", "start": [1, 0, 0], "end": [0, 1, 0]},
                {"kind": "Line", "start": [0, 1, 0], "end": [0, 0, 0]}]]
    manifest["extrusions"][0]["profile"] = copy.deepcopy(profile)
    manifest["type_samples"][0]["extrusions"][0]["profile"] = copy.deepcopy(profile)
    target = target_of(manifest)
    for form in (target["extrusions"][0], target["type_samples"][0]["extrusions"][0]):
        loop = form["profile"][0]
        form["profile"][0] = loop[1:] + loop[:1]
    assert compare_manifests(manifest, target)["status"] == "matched_supported_evidence"
    target["extrusions"][0]["profile"][0][0]["end"] = [0, 2, 0]
    assert compare_manifests(manifest, target)["status"] == "different"


def test_template_matching_keeps_changed_and_additional_constraints(manifest):
    constraint = {"id": 1, "locked": True, "label": None, "curve": None,
                  "reference_targets": [{"kind": "ReferencePlane", "name": "Origin"}],
                  "references": [{"element_id": 1}]}
    baseline = copy.deepcopy(manifest)
    baseline["features"] = {"dimensions": [copy.deepcopy(constraint)], "unsupported_elements": []}
    extra = copy.deepcopy(constraint)
    extra["id"] = 200
    manifest["features"]["dimensions"] = [copy.deepcopy(constraint), extra]
    apply_template_baseline(manifest, baseline)
    assert len(manifest["features"]["dimensions"]) == 1
    assert not compatibility_report(manifest)["ready_for_first_slice"]
    changed = copy.deepcopy(baseline)
    changed["features"]["dimensions"][0]["locked"] = False
    apply_template_baseline(changed, baseline)
    assert changed["features"]["dimensions"]
    assert changed["inspection_errors"]


def test_missing_template_alignment_is_a_preservation_blocker(manifest):
    baseline = copy.deepcopy(manifest)
    baseline["features"]["dimensions"] = [{"id": 1, "locked": True, "reference_targets": [], "references": []}]
    apply_template_baseline(manifest, baseline)
    assert not compatibility_report(manifest)["ready_for_first_slice"]


def test_extra_or_changed_internal_elements_remain_blockers(manifest):
    item = {"id": 1, "kind": "Element", "name": "Setting", "parameters": [{"name": "A", "value": 1}]}
    baseline = copy.deepcopy(manifest)
    baseline["features"]["unsupported_elements"] = [copy.deepcopy(item)]
    manifest["features"]["unsupported_elements"] = [copy.deepcopy(item), copy.deepcopy(item)]
    apply_template_baseline(manifest, baseline)
    assert len(manifest["features"]["unsupported_elements"]) == 1


async def test_tool_passes_explicit_template_baseline(mock_mcp, mock_revit_post):
    mock_revit_post.return_value = {"status": "success"}
    register_family_backport_tools(mock_mcp, mock_revit_post)
    await mock_mcp.tools["inspect_family_backport"]("r1", "C:/family.rfa", template_path="C:/template.rft")
    assert mock_revit_post.call_args.args[1]["template_path"] == "C:/template.rft"


def test_additional_association_on_same_form_is_not_silently_lost(manifest):
    form = manifest["extrusions"][0]
    form["association_parameter_ids"] = {"EXTRUSION_END_PARAM": -1001801}
    manifest["parameters"][0]["associated_parameters"] = [
        {"element_id": form["id"], "parameter_id": -1001801}]
    assert compatibility_report(manifest)["ready_for_first_slice"]
    manifest["parameters"][0]["associated_parameters"].append({"element_id": form["id"], "parameter_id": -123})
    assert not compatibility_report(manifest)["ready_for_first_slice"]


def test_route_requests_api_context_without_requiring_active_document(monkeypatch, manifest):
    from revit_mcp import family_backport
    handlers = {}

    class RouteAPI:
        def route(self, path, methods):
            def register(handler):
                handlers[path] = handler
                return handler
            return register

    pyrevit = types.ModuleType("pyrevit")
    pyrevit.DB = MagicMock()
    pyrevit.routes = types.SimpleNamespace(make_response=lambda **kwargs: kwargs)
    monkeypatch.setitem(sys.modules, "pyrevit", pyrevit)
    reader = MagicMock(return_value=manifest)
    monkeypatch.setattr(family_backport, "inspect_file", reader)
    family_backport.register_family_backport_routes(RouteAPI())
    handler = handlers["/family_backport/inspect/"]
    # pyRevit chooses ExternalEvent dispatch from uiapp/doc/uidoc arguments.
    assert "uiapp" in inspect.signature(handler).parameters
    uiapp = MagicMock()
    request = types.SimpleNamespace(data={"file_path": "C:/family.rfa", "expected_version": 2025,
                                          "template_path": "C:/source.rft"})
    response = handler(uiapp, request)
    assert response["data"]["status"] == "success"
    reader.assert_called_once_with(uiapp.Application, "C:/family.rfa", 2025, pyrevit.DB,
                                   template_path="C:/source.rft")
