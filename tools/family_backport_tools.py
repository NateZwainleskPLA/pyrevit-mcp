# -*- coding: utf-8 -*-
"""Agent-oriented family evidence tools; reconstruction uses focused Revit code."""
import json
from typing import Any, Dict
from mcp.server.fastmcp import Context
from revit_mcp.family_backport_contract import compatibility_report, compare_manifests


def register_family_backport_tools(mcp, revit_post):
    @mcp.tool()
    async def inspect_family_backport(target: str, file_path: str, expected_version: int = 2025,
                                     target_version: int = 2024, template_path: str = None,
                                     ctx: Context = None) -> str:
        """Inspect one on-disk RFA without saving, upgrading, or changing the UI.

        Path is absolute on the Revit machine selected by the explicit target
        handle. The route rejects a runtime different from expected_version.
        Named-type geometry sampling is rolled back in an owned background doc.
        Returns a portable manifest, feature inventory and compatibility blockers.
        No automatic back-port is performed. Save the manifest for comparison.
        Supply the matching source .rft to distinguish unchanged template
        settings/constraints; extra or changed relationships remain blockers.
        """
        payload = {
            "file_path": file_path, "expected_version": expected_version,
            "target_version": target_version}
        if template_path:
            payload["template_path"] = template_path
        response = await revit_post("/family_backport/inspect/", payload, ctx, timeout=120.0, target=target)
        # Preserve the whole manifest: generic response formatting may discard it.
        return json.dumps(response, indent=2, ensure_ascii=False) if isinstance(response, dict) else str(response)

    @mcp.tool()
    async def assess_family_backport(manifest: Dict[str, Any], target_version: int = 2024) -> str:
        """Assess portable family evidence against the first reconstruction slice.

        Runs outside Revit. Blockers are unresolved preservation work, not a
        license to omit features. Revit 2022 remains research-only.
        """
        return json.dumps(compatibility_report(manifest, target_version), indent=2)

    @mcp.tool()
    async def compare_family_backport(source_manifest: Dict[str, Any], target_manifest: Dict[str, Any],
                                     tolerance: float = 1e-7) -> str:
        """Compare parameter/type/native geometry evidence across Revit versions.

        Tolerance uses Revit internal units. Matching sampled types does not
        prove arbitrary flex, host, cut, connector or nested-family equivalence.
        Unsupported content remains unverified even if sampled evidence matches.
        """
        return json.dumps(compare_manifests(source_manifest, target_manifest, tolerance), indent=2)
