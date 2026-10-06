# -*- coding: utf-8 -*-
"""Native registration adapter. Imported only by extension startup in Revit.

Uses pyRevit's native endpoint registration as evidence. It does not activate,
replace, reload or otherwise manage the Routes listener.
"""
import json
import logging
import os
import time

from .target_registry import TargetRegistry, retained_instance_id, set_registry

logger = logging.getLogger(__name__)
PROCESS_SLOT = "revit_mcp.identity.process.v1"
CALLBACK_SLOT = "revit_mcp.identity.callbacks.v1"


def refresh_uiapp(registry, uiapp):
    """Valid API callback only; never use this from a metadata HTTP worker."""
    uidoc = uiapp.ActiveUIDocument
    active = uidoc.Document if uidoc else None
    return registry.refresh_documents(uiapp.Application.Documents, active)


def register_metadata_routes(api, registry):
    from pyrevit import routes

    @api.route('/metadata/', methods=["GET"])
    def metadata():
        # Deliberately no doc/uidoc/uiapp arguments: copied primitives only.
        return routes.make_response(data=registry.snapshot())

    @api.route('/metadata/refresh/', methods=["GET"])
    def refresh_metadata(uiapp, instance_id=None, runtime_id=None):
        from .identity import IdentityError
        try:
            registry.validate_target(instance_id, runtime_id)
            return routes.make_response(data=refresh_uiapp(registry, uiapp))
        except IdentityError as error:
            snapshot = registry.snapshot()
            return routes.make_response(data={"error": str(error), "error_code": error.code,
                                               "actual_target": {k: snapshot[k] for k in
                                                                 ("instance_id", "runtime_id")}}, status=409)
        except Exception as error:
            registry.record_refresh_error(error)
            return routes.make_response(data=registry.snapshot(), status=503)


def publish_registration(snapshot, registration_dir):
    """Atomically replace only this connector's per-process JSON evidence file."""
    from System.IO import File
    if not os.path.isdir(registration_dir):
        try:
            os.makedirs(registration_dir)
        except OSError:
            if not os.path.isdir(registration_dir):
                raise
    path = os.path.join(registration_dir, "%s.json" % snapshot["process_id"])
    temp = path + "." + snapshot["runtime_id"] + ".tmp"
    data = {k: snapshot[k] for k in ("instance_id", "runtime_id", "process_id",
                                     "process_started_at", "revit_version", "endpoint")}
    try:
        with open(temp, "w") as stream:
            json.dump(data, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        if File.Exists(path):
            File.Replace(temp, path, None)
        else:
            File.Move(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return path


def initialize_identity(api):
    """Startup API context only. Retain primitive UUID and owned CLR delegates."""
    from System import AppDomain, String, Object
    from System.Collections.Generic import Dictionary
    from System.Diagnostics import Process
    from pyrevit import HOST_APP, framework, DB, UI
    from pyrevit.routes.server import serverinfo
    from . import __version__

    domain = AppDomain.CurrentDomain
    process = Process.GetCurrentProcess()
    pid = int(process.Id)
    started = str(process.StartTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ"))
    try:
        retained = json.loads(str(domain.GetData(PROCESS_SLOT)))
    except (ValueError, TypeError):
        retained = None
    instance_id = retained_instance_id(pid, started, retained)
    domain.SetData(PROCESS_SLOT, json.dumps(dict(
        instance_id=instance_id, process_id=pid, process_started_at=started)))

    # CLR storage keeps exact delegate instances across IronPython engine reloads.
    # Refuse initialization if safe callback removal fails; never stack callbacks.
    old = domain.GetData(CALLBACK_SLOT)
    if old is not None:
        old["expire"]()
        old["uiapp"].Idling -= old["idling"]
        old["uiapp"].ViewActivated -= old["view"]
        old["app"].DocumentOpened -= old["opened"]
        old["app"].DocumentClosed -= old["closed"]
        domain.SetData(CALLBACK_SLOT, None)

    rsinfo = serverinfo.register()
    if rsinfo is None or int(rsinfo.process_id) != pid:
        raise RuntimeError("pyRevit native registration does not belong to this process")
    host = os.environ.get("REVIT_MCP_ADVERTISED_HOST") or str(rsinfo.server_host)
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    endpoint = "http://%s:%s/revit_mcp" % (host, int(rsinfo.server_port))
    registry = TargetRegistry(pid, started, str(HOST_APP.version), endpoint,
                              instance_id=instance_id,
                              revit_build=str(HOST_APP.app.VersionBuild),
                              connector_version=__version__)
    uiapp = HOST_APP.uiapp
    last_idle = [0.0]

    def collect(sender, args):
        try:
            refresh_uiapp(registry, uiapp)
        except Exception as error:
            registry.record_refresh_error(error)
            logger.warning("Identity document collection failed: %s", str(error))

    def idle(sender, args):
        now = time.time()
        if now - last_idle[0] >= 1.0:
            last_idle[0] = now
            collect(sender, args)

    state = Dictionary[String, Object]()
    state["uiapp"], state["app"] = uiapp, uiapp.Application
    state["expire"] = registry.expire
    state["idling"] = framework.EventHandler[UI.Events.IdlingEventArgs](idle)
    state["view"] = framework.EventHandler[UI.Events.ViewActivatedEventArgs](collect)
    state["opened"] = framework.EventHandler[DB.Events.DocumentOpenedEventArgs](collect)
    state["closed"] = framework.EventHandler[DB.Events.DocumentClosedEventArgs](collect)
    # Store ownership before subscribing, and unwind each successful subscription
    # if any subsequent subscription fails.
    attached = []
    try:
        uiapp.Idling += state["idling"]
        attached.append("idling")
        uiapp.ViewActivated += state["view"]
        attached.append("view")
        uiapp.Application.DocumentOpened += state["opened"]
        attached.append("opened")
        uiapp.Application.DocumentClosed += state["closed"]
        attached.append("closed")
    except Exception:
        registry.expire()
        if "idling" in attached:
            uiapp.Idling -= state["idling"]
        if "view" in attached:
            uiapp.ViewActivated -= state["view"]
        if "opened" in attached:
            uiapp.Application.DocumentOpened -= state["opened"]
        if "closed" in attached:
            uiapp.Application.DocumentClosed -= state["closed"]
        raise
    domain.SetData(CALLBACK_SLOT, state)
    set_registry(registry)
    register_metadata_routes(api, registry)
    if HOST_APP.has_api_context:
        collect(None, None)
    registration_dir = os.environ.get("REVIT_MCP_REGISTRATION_DIR") or os.path.join(
        os.environ["APPDATA"], "pyRevit", "RevitMCP", "registrations")
    try:
        publish_registration(registry.snapshot(), registration_dir)
    except Exception as error:
        # Configured endpoint probing remains usable if local evidence cannot be written.
        logger.warning("Identity registration record unavailable: %s", str(error))
    return registry
