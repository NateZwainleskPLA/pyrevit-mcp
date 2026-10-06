"""Exercise selected pyRevit lifecycle methods with inert source-level doubles.

No pyRevit import, socket, worker thread, Revit call, or source edit occurs.
This demonstrates source defects; it cannot reproduce the native outage.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def selected(source, name):
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
                and n.name == name)
    return compile(ast.Module(body=[node], type_ignores=[]), "<lifecycle-source>", "exec")


def audit(root):
    root = Path(root)
    paths = [root / "pyrevitlib/pyrevit/routes/server/server.py",
             root / "pyrevitlib/pyrevit/routes/server/__init__.py"]
    sources = [p.read_text(encoding="utf-8-sig") for p in paths]
    workers = []
    events = []

    class Thread:
        def __init__(self, target):
            self.target = target
            workers.append(self)

        def start(self):
            events.append("start")

        def join(self):
            events.append("join")

    class HTTPServer:
        def __init__(self, address, handler):
            self.socket = type("Socket", (), {"close": lambda s: events.append("socket.close")})()

        def serve_forever(self):
            raise AssertionError("An inert thread must not execute its target")

        def shutdown(self):
            events.append("HTTPServer.shutdown")

    ns = {"ThreadingMixIn": type("ThreadingMixIn", (), {}), "HTTPServer": HTTPServer,
          "threading": type("Threads", (), {"Thread": Thread}), "HttpRequestHandler": object}
    exec(selected(sources[0], "ThreadedHttpServer"), ns)
    exec(selected(sources[0], "RoutesServer"), ns)
    values = {}

    class Env:
        ROUTES_SERVER = "server"
        get_pyrevit_env_var = staticmethod(lambda key: values.get(key))
        set_pyrevit_env_var = staticmethod(lambda key, value: values.update({key: value}))

    ns.update(envvars=Env, server=type("Server", (), {"RoutesServer": ns["RoutesServer"]}),
              serverinfo=type("Info", (), {
                  "register": staticmethod(lambda: type("Record", (), {
                      "server_host": "127.0.0.1", "server_port": 48884})()),
                  "unregister": staticmethod(lambda: None)}),
              mlogger=type("Logger", (), {"error": staticmethod(lambda *args: None)}))
    exec(selected(sources[1], "activate_server"), ns)
    active = ns["activate_server"]()
    if active is None:
        raise RuntimeError("Selected source activation failed in the inert harness")
    first_count = len(workers)
    ns["activate_server"]()
    active.stop()
    return {
        "coverage": "source-level doubles; no native outage reproduction",
        "source_files": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in paths],
        "first_activation_worker_count": first_count,
        "repeat_activation_worker_count": len(workers),
        "retained_worker_count": sum(w is active.server_thread for w in workers),
        "events": events,
        "duplicate_serve_loops": first_count > 1,
        "socket_closed_before_shutdown": "socket.close" in events and
            events.index("socket.close") < events.index("HTTPServer.shutdown"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pyrevit_source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.pyrevit_source)
    body = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(body + "\n", encoding="utf-8")
    print(body)
    return 1 if result["duplicate_serve_loops"] or result["socket_closed_before_shutdown"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
