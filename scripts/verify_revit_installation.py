"""Read-only native installation smoke test; never opens or changes a model."""
import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools.target_directory import TargetDirectory
from tools.target_discovery import TargetDiscovery
from tools.target_router import TargetRouter


async def verify(case, output, versions=None, api_context=False):
    manifest = json.loads((case / "installation.json").read_text())
    source = Path(manifest["source"])
    versions = versions or manifest["versions"]
    directory = TargetDirectory(case.parent / "target-directory.sqlite3")
    discovery = TargetDiscovery(directory)
    discovered = await discovery.discover()
    report = {"verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "deployed_sha": manifest["integration_sha"],
              "source": str(source), "discovery_errors": discovered["errors"],
              "configured_versions": manifest["versions"], "requested_versions": versions,
              "versions": [], "models_opened_or_modified": False}
    router = TargetRouter(directory, discovery.verified_handshake)
    for version in versions:
        candidates = [t for t in discovered["targets"] if t["revit_version"] == version]
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one verification instance for Revit " + version)
        target = candidates[0]
        receipt = json.loads((case / ("loaded-%s.json" % target["process_id"])).read_text())
        if receipt["status"] != "loaded" or receipt["integration_sha"] != manifest["integration_sha"]:
            raise RuntimeError("Native load receipt disagrees with installation")
        actual_files = [p for p in receipt["loaded_modules"].values() if p]
        if not actual_files or not all(Path(p).is_relative_to(source) for p in actual_files):
            raise RuntimeError("A connector module was loaded outside the integration checkout")
        row = {"version": version, "build": target["revit_build"], "pid": target["process_id"],
               "endpoint": target["endpoint"], "target": target["target"],
               "instance_id": target["instance_id"], "runtime_id": target["runtime_id"],
               "documents": target["documents"], "loaded_module_count": len(actual_files),
               "loaded_receipt": str(case / ("loaded-%s.json" % target["process_id"])),
               "api_context_probe": "not requested; cached liveness is not API readiness"}
        # Home/modal states may defer ExternalEvent indefinitely. Never poll an
        # API-context route for installation readiness or retry a timed-out one.
        if api_context:
            with httpx.Client(timeout=5, follow_redirects=False) as client:
                invalid = client.get(target["endpoint"] + "/status/", params={
                    "instance_id": target["instance_id"], "runtime_id": "00000000-0000-0000-0000-000000000000"})
            status = await router.call("GET", "/status/", target=target["target"], timeout=5)
            row.update(foreign_runtime_status=invalid.status_code,
                       foreign_runtime_body=invalid.json(), status_http=status.status_code,
                       status_body=status.body, status_failure_kind=status.failure_kind)
            if invalid.status_code != 409:
                raise RuntimeError("Foreign runtime was not rejected by Revit " + version)
            if status.status_code != 503 or status.body.get("actual_target", {}).get("runtime_id") != target["runtime_id"]:
                raise RuntimeError("Empty-document status/context/identity response failed for " + version)
        report["versions"].append(row)
    directory.close()
    params = StdioServerParameters(command=sys.executable, args=[str(source / "main.py")],
                                  cwd=str(source), env={"REVIT_TARGET_STATE": str(case.parent / "target-directory.sqlite3")})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            targets = await session.call_tool("list_revit_targets", {})
            data = targets.structuredContent
            if data is None:
                for item in targets.content:
                    if item.type == "text":
                        try:
                            candidate = json.loads(item.text)
                            if isinstance(candidate, dict) and "targets" in candidate:
                                data = candidate
                        except ValueError:
                            pass
            if targets.isError or data is None:
                raise RuntimeError("MCP target discovery failed: " + str(targets.content))
            observed = sorted(t["revit_version"] for t in data["targets"])
            if not all(version in observed for version in versions):
                raise RuntimeError("MCP did not discover the expected native versions")
            report["mcp"] = {"server": initialized.serverInfo.name,
                             "tool_count": len(tools.tools), "versions": observed,
                             "target_handles": [t["target"] for t in data["targets"]]}
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output), "versions": [r["version"] for r in report["versions"]],
                      "mcp": report["mcp"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--versions", nargs="+")
    parser.add_argument("--api-context", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify(args.case_dir.resolve(), args.output.resolve(), args.versions, args.api_context))


if __name__ == "__main__":
    main()
