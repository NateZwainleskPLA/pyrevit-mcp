"""Read a local Python file and execute its contents through explicit routing."""
import argparse
import hashlib
import os
from pathlib import Path


def read_script_file(file_path):
    path = Path(file_path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        code = stream.read().replace("\r\n", "\n")
    return {"code": code, "script_name": path.name,
            "script_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest()}


async def execute_script_file(router, file_path, *, target, document,
                              description="Script file execution", transaction_mode="script",
                              allow_ui_change=False):
    if transaction_mode not in ("script", "managed"):
        raise ValueError("transaction_mode must be script or managed")
    payload = read_script_file(file_path)
    payload.update(description=description, transaction_mode=transaction_mode)
    return await router.call("POST", "/execute_code/", target=target, document=document,
                             data=payload, allow_ui_change=allow_ui_change, timeout=60.0)


async def _run(args):
    from tools.target_directory import TargetDirectory
    from tools.target_discovery import TargetDiscovery
    from tools.target_router import TargetRouter
    directory = TargetDirectory(args.state)
    try:
        discovery = TargetDiscovery(directory)
        router = TargetRouter(directory, discovery.verified_handshake)
        return await execute_script_file(router, args.file, target=args.target, document=args.document,
                                          description=args.description, transaction_mode=args.transaction_mode,
                                          allow_ui_change=args.allow_ui_change)
    finally:
        directory.close()


def main(argv=None):
    import anyio
    from tools.utils import format_response
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="UTF-8 Python file on this client machine")
    parser.add_argument("--target", required=True)
    parser.add_argument("--document", required=True)
    parser.add_argument("--state", default=os.environ.get("REVIT_TARGET_STATE"),
                        help="Existing SQLite handle directory shared with the MCP server")
    parser.add_argument("--description", default="Script file execution")
    parser.add_argument("--transaction-mode", choices=("script", "managed"), default="script")
    parser.add_argument("--allow-ui-change", action="store_true")
    args = parser.parse_args(argv)
    if not args.state or not Path(args.state).is_file():
        parser.error("--state or REVIT_TARGET_STATE must name the existing shared handle directory")
    try:
        result = anyio.run(_run, args)
        print(format_response(result))
        return 0 if result.http_success and not result.revit_error and not result.failure_kind else 1
    except (OSError, ValueError) as error:
        parser.exit(1, "Error: {}\n".format(error))


if __name__ == "__main__":
    raise SystemExit(main())
