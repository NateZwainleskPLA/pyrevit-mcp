# -*- coding: utf-8 -*-
"""Launch and discovery tools for Revit instances"""

import os
import subprocess
import json
import anyio
from mcp.server.fastmcp import Context
from .utils import format_response


def _find_revit_installations():
    """Scan the system for installed Revit versions.

    Checks Windows Registry and common filesystem paths.
    Returns a list of {"year": str, "path": str} sorted newest-first.
    """
    found = {}

    # Strategy 1: Windows Registry
    try:
        import winreg

        base_key_path = r"SOFTWARE\Autodesk\Revit"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                base_key = winreg.OpenKey(hive, base_key_path)
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(base_key, i)
                        i += 1
                        # Subkeys are often like "Autodesk Revit 2025"
                        # Extract the year from the subkey name
                        year = None
                        for token in subkey_name.split():
                            if token.isdigit() and len(token) == 4:
                                year = token
                                break

                        if not year:
                            continue

                        subkey = winreg.OpenKey(base_key, subkey_name)
                        # Try common value names for install path
                        for value_name in (
                            "InstallationLocation",
                            "InstallPath",
                            "",
                        ):
                            try:
                                val, _ = winreg.QueryValueEx(
                                    subkey, value_name
                                )
                                if val and os.path.isdir(val):
                                    exe = os.path.join(val, "Revit.exe")
                                    if os.path.isfile(exe):
                                        found[year] = exe
                                    break
                            except OSError:
                                continue
                        winreg.CloseKey(subkey)
                    except OSError:
                        break
                winreg.CloseKey(base_key)
            except OSError:
                continue
    except ImportError:
        pass  # Not on Windows

    # Strategy 2: Filesystem fallback
    program_files = os.environ.get(
        "ProgramFiles", r"C:\Program Files"
    )
    for year in range(2027, 2019, -1):
        year_str = str(year)
        if year_str in found:
            continue
        exe = os.path.join(
            program_files, "Autodesk", "Revit {}".format(year_str), "Revit.exe"
        )
        if os.path.isfile(exe):
            found[year_str] = exe

    # Sort newest-first
    installations = [
        {"year": y, "path": p}
        for y, p in sorted(found.items(), key=lambda x: x[0], reverse=True)
    ]
    return installations


def _select_revit(installations, version=None):
    """Pick a Revit installation by version year, or the latest available."""
    if not installations:
        return None
    if version:
        for inst in installations:
            if inst["year"] == str(version):
                return inst
        return None
    return installations[0]


def _build_launch_command(revit_path, file_path=None, language=None):
    """Construct the subprocess argument list for launching Revit."""
    args = [revit_path]
    if language:
        args.extend(["/language", language])
    if file_path:
        args.append(file_path)
    return args


async def _wait_for_revit_ready(discovery, process, started_at, ctx, timeout,
                                expected_version, poll_interval=1, clock=None):
    """Wait for the retained child process's own verified runtime registration."""
    import time
    from urllib.parse import urlsplit
    from revit_mcp.identity import validate_snapshot

    clock = clock or time.monotonic
    deadline = clock() + timeout
    last_error = None
    while clock() < deadline:
        if process.poll() is not None:
            return False, {"error_code": "launched_process_exited", "process_id": process.pid,
                           "exit_code": process.returncode}
        if ctx:
            await ctx.info("Waiting for launched Revit PID {} registration...".format(process.pid))
        try:
            with anyio.fail_after(max(0.001, deadline - clock())):
                listing = await discovery.discover()
                for target in listing.get("targets", []):
                    # A local launch cannot bind a remote host with coincident PID.
                    if urlsplit(target.get("endpoint", "")).hostname not in ("localhost", "127.0.0.1", "::1"):
                        continue
                    if (target.get("process_id") != process.pid or
                            target.get("process_started_at") != started_at or
                            target.get("revit_version") != expected_version):
                        continue
                    validate_snapshot(target)
                    if target.get("runtime_available") is False or not target.get("target"):
                        continue
                    if not target.get("documents_known"):
                        continue  # API-context snapshot initialization still pending
                    await discovery.revalidate(target["target"])
                    # Read the refreshed descriptor; do not accept a superseded generation.
                    fresh = next(item for item in discovery.directory.targets()
                                 if item["target"] == target["target"])
                    if any(fresh.get(key) != target.get(key) for key in
                           ("instance_id", "runtime_id", "process_id", "process_started_at")):
                        continue
                    if process.poll() is None:
                        return True, fresh
                    return False, {"error_code": "launched_process_exited", "process_id": process.pid}
        except Exception as error:
            last_error = str(error) or type(error).__name__
        remaining = deadline - clock()
        if remaining > 0:
            await anyio.sleep(min(poll_interval, remaining))
    return False, {"error_code": "launch_verification_timeout", "process_id": process.pid,
                   "process_started_at": started_at, "verification_error": last_error}


def register_launch_tools(mcp, revit_get=None, discovery=None):
    """Register launch tools; discovery and its handle directory are injected."""

    @mcp.tool()
    async def list_revit_installations(ctx: Context) -> str:
        """Discover all Revit versions installed on this system.

        Returns a list of installed Revit versions with their executable paths.
        Use this to check what's available before calling launch_revit.
        """
        try:
            installations = _find_revit_installations()
        except Exception as e:
            return json.dumps(
                {"status": "error", "error": str(e)}, indent=2
            )

        if not installations:
            return json.dumps(
                {
                    "status": "success",
                    "installations": [],
                    "message": "No Revit installations found. "
                    "Checked Windows Registry and common install paths.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "status": "success",
                "installations": installations,
                "count": len(installations),
            },
            indent=2,
        )

    @mcp.tool()
    async def launch_revit(
        ctx: Context,
        file_path: str = None,
        version: str = None,
        language: str = None,
        timeout: int = 120,
    ) -> str:
        """Launch Revit on this machine, optionally opening a file.

        Finds installed Revit versions automatically. Retains the child PID and
        process start time, then waits for its own verified runtime registration.
        Returns that runtime's target handle. Cached registration does not prove
        that a native dialog has closed or a requested file finished opening.

        For workshared (central model) files, Revit will show its native
        worksharing dialog on open. Use the open_document tool after launch
        for more control over worksharing options like detach from central.

        Args:
            file_path: Path to a .rvt, .rfa, or .rte file to open. Optional.
            version: Revit version year (e.g. "2025"). Uses latest if omitted.
            language: Language code (e.g. "ENU", "FRA"). Optional.
            timeout: Seconds to wait for Revit readiness (default 120).
        """
        # Validate file path if provided
        if file_path:
            if not os.path.isfile(file_path):
                return json.dumps(
                    {
                        "status": "error",
                        "error": "File not found: {}".format(file_path),
                    },
                    indent=2,
                )
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in (".rvt", ".rfa", ".rte"):
                return json.dumps(
                    {
                        "status": "error",
                        "error": "Unsupported file type '{}'. "
                        "Expected .rvt, .rfa, or .rte".format(ext),
                    },
                    indent=2,
                )

        # Find installations
        try:
            installations = _find_revit_installations()
        except Exception as e:
            return json.dumps(
                {
                    "status": "error",
                    "error": "Failed to scan for Revit installations: {}".format(
                        str(e)
                    ),
                },
                indent=2,
            )

        if not installations:
            return json.dumps(
                {
                    "status": "error",
                    "error": "No Revit installations found on this system.",
                },
                indent=2,
            )

        # Select version
        selected = _select_revit(installations, version)
        if not selected:
            available = ", ".join(i["year"] for i in installations)
            return json.dumps(
                {
                    "status": "error",
                    "error": "Revit {} not found. Available versions: {}".format(
                        version, available
                    ),
                },
                indent=2,
            )

        if discovery is None:
            return json.dumps({"status": "error", "error": "Launch verification requires the shared target discovery service"})

        # Build and launch
        cmd = _build_launch_command(
            selected["path"], file_path, language
        )

        try:
            process = subprocess.Popen(cmd)
        except OSError as e:
            return json.dumps(
                {
                    "status": "error",
                    "error": "Failed to launch Revit: {}".format(str(e)),
                    "attempted_path": selected["path"],
                },
                indent=2,
            )
        try:
            from .windows_target_evidence import process_started_at
            started_at = process_started_at(process.pid)
        except (OSError, ValueError) as error:
            return json.dumps({"status": "launched_unverified", "revit_ready": False,
                               "process_id": process.pid, "error_code": "process_identity_unavailable",
                               "error": str(error)}, indent=2)

        if ctx:
            await ctx.info(
                "Revit {} launched. Waiting for pyRevit Routes to become available...".format(
                    selected["year"]
                )
            )

        ready, status_response = await _wait_for_revit_ready(
            discovery, process, started_at, ctx, timeout, selected["year"])


        result = {
            "status": "success" if ready else "launched_unverified",
            "revit_version": selected["year"],
            "revit_path": selected["path"],
            "requested_file": file_path,
            "process_id": process.pid,
            "process_started_at": started_at,
            "revit_ready": ready,
        }

        if ready:
            result["target"] = status_response["target"]
            result["actual_target"] = {key: status_response[key] for key in ("instance_id", "runtime_id")}
            result["documents"] = status_response["documents"]
            result["file_open_verified"] = bool(file_path and any(
                os.path.normcase(os.path.abspath(item["path"])) == os.path.normcase(os.path.abspath(file_path))
                for item in status_response["documents"] if item["path"]))
            result["message"] = (
                "Revit {} is running and pyRevit Routes is active.".format(
                    selected["year"]
                )
            )
            if status_response:
                result["revit_status"] = status_response
        else:
            result["verification"] = status_response
            result["message"] = (
                "Revit {} was launched but did not respond within {} seconds. "
                "Ensure pyRevit is installed and Routes Server is enabled in "
                "pyRevit Settings.".format(selected["year"], timeout)
            )

        if file_path:
            result["worksharing_note"] = (
                "If this is a workshared (central) file, Revit will show its "
                "native dialog for creating a local copy. For programmatic "
                "control over worksharing options (detach, audit), use the "
                "open_document tool after Revit is ready."
            )

        return json.dumps(result, indent=2)
