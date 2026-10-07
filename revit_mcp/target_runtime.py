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
from .identity import full_uuid, validate_snapshot

logger = logging.getLogger(__name__)
PROCESS_SLOT = "revit_mcp.identity.process.v1"
CALLBACK_SLOT = "revit_mcp.identity.callbacks.v1"


def advertised_endpoint(server_host, port, override=None):
    """Bind wildcards are not destinations. Default discovery uses IPv4 loopback.

    An IPv6-only listener can explicitly advertise ::1 through the override.
    pyRevit's default HTTPServer uses IPv4; no listener is activated here.
    """
    host = override or str(server_host)
    if not override and host in ("", "0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return "http://%s:%s/revit_mcp" % (host, int(port))


def format_process_start(start_time):
    from System.Globalization import CultureInfo
    return str(start_time.ToUniversalTime().ToString(
        "yyyy-MM-ddTHH:mm:ss.ffffffZ", CultureInfo.InvariantCulture))


def remove_owned_callbacks(domain):
    """Disable before detach; retain exact remaining delegates on any failure."""
    old = domain.GetData(CALLBACK_SLOT)
    if old is None:
        return
    old["enabled"] = False
    errors = []
    for key in ("idling", "view", "opened", "closed"):
        if key not in old:
            continue
        try:
            if key == "idling":
                old["uiapp"].Idling -= old[key]
            elif key == "view":
                old["uiapp"].ViewActivated -= old[key]
            elif key == "opened":
                old["app"].DocumentOpened -= old[key]
            else:
                old["app"].DocumentClosed -= old[key]
            if hasattr(old, "Remove"):
                old.Remove(key)
            else:
                del old[key]
        except Exception as error:
            errors.append(key)
            logger.warning("Identity callback detach failed (%s): %s", key, str(error))
    try:
        old["expire"]()
    except Exception as error:
        logger.warning("Previous identity expiration unavailable: %s", str(error))
    if errors:
        # The slot still owns every delegate whose detach failed. No replacement
        # may be installed; a subsequent initialization can retry those removals.
        raise RuntimeError("Identity callback detach incomplete: " + ", ".join(errors))
    domain.SetData(CALLBACK_SLOT, None)


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


def initialize_legacy_identity(api):
    """Legacy-only degraded startup; directed composition must use strict init."""
    try:
        return initialize_identity(api)
    except Exception as error:
        logger.error("Connector identity unavailable; independent legacy routes remain: %s", str(error))
        try:
            from System import AppDomain
            remove_owned_callbacks(AppDomain.CurrentDomain)
        except Exception as cleanup_error:
            # Failed detach keeps exact ownership in the disabled retained slot.
            logger.warning("Identity cleanup remains incomplete: %s", str(cleanup_error))
        try:
            set_registry(None)  # Invalidate even a partially installed generation.
        except Exception as expiration_error:
            logger.warning("Installed identity expiration failed: %s", str(expiration_error))
        from pyrevit import routes
        diagnostic = dict(api_name="revit_mcp", runtime_available=False,
                          error_code="runtime_unavailable", error=str(error))

        # Replace normal metadata handlers even if registration failed halfway.
        # No UUIDs, documents, API-context arguments, or API object reads.
        def unavailable_metadata():
            return routes.make_response(data=dict(diagnostic), status=503)
        api.route('/metadata/', methods=["GET"])(unavailable_metadata)
        api.route('/metadata/refresh/', methods=["GET"])(unavailable_metadata)
        return None


def native_process_started_at(pid):
    """Return a live process's start; None means proven absent, exceptions unknown."""
    from System import ArgumentException
    from System.Diagnostics import Process
    try:
        process = Process.GetProcessById(pid)
    except ArgumentException:
        return None
    try:
        return None if process.HasExited else format_process_start(process.StartTime)
    finally:
        process.Dispose()


def prune_registration_records(registration_dir, process_id, runtime_id,
                               inspect_start=None):
    """Under publication lock, prune only proved-stale connector-owned files.

    Inaccessible/invalid records are retained. Never recursively delete, follow
    another directory, or delete a live registration based on a failed inspection.
    """
    inspect_start = inspect_start or native_process_started_at
    for name in os.listdir(registration_dir):
        path = os.path.join(registration_dir, name)
        if name.endswith(".json") and name[:-5].isdigit():
            try:
                if os.path.getsize(path) > 65536:
                    continue
                with open(path, "r") as stream:
                    record = json.load(stream)
                pid = record["process_id"]
                if str(pid) != name[:-5] or not record.get("process_started_at"):
                    continue
                full_uuid(record.get("instance_id"), "instance_id")
                full_uuid(record.get("runtime_id"), "runtime_id")
                actual = inspect_start(pid)
                if actual is None or actual != record["process_started_at"]:
                    os.remove(path)
            except Exception:
                continue  # No reliable proof of stale ownership.
        elif name.startswith("%s.json." % process_id) and name.endswith(".tmp"):
            token = name[len("%s.json." % process_id):-4]
            try:
                full_uuid(token, "runtime_id")
                if token != runtime_id:
                    os.remove(path)
            except Exception:
                continue


def publish_registration(snapshot, registration_dir):
    """Atomically replace only this connector's per-process JSON evidence file."""
    from System.IO import File, FileStream, FileMode, FileAccess, FileShare
    snapshot = validate_snapshot(snapshot)
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
    # FileShare.None serializes native publishers/pruners across processes and
    # Windows sessions. Contention fails this publication instead of waiting on
    # Revit's API thread; configured metadata discovery remains available.
    lease = FileStream(os.path.join(registration_dir, ".registration.lock"),
                       FileMode.OpenOrCreate, FileAccess.ReadWrite, getattr(FileShare, "None"))
    try:
        prune_registration_records(registration_dir, snapshot["process_id"], snapshot["runtime_id"])
        with open(temp, "w") as stream:
            json.dump(data, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        if File.Exists(path):
            File.Replace(temp, path, None)
        else:
            File.Move(temp, path)
    finally:
        try:
            if os.path.exists(temp):
                os.remove(temp)
        finally:
            lease.Dispose()
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
    started = format_process_start(process.StartTime)
    try:
        retained = json.loads(str(domain.GetData(PROCESS_SLOT)))
    except (ValueError, TypeError):
        retained = None
    instance_id = retained_instance_id(pid, started, retained)
    domain.SetData(PROCESS_SLOT, json.dumps(dict(
        instance_id=instance_id, process_id=pid, process_started_at=started)))

    # CLR storage keeps exact delegate instances across IronPython engine reloads.
    # Refuse initialization if safe callback removal fails; never stack callbacks.
    remove_owned_callbacks(domain)

    rsinfo = serverinfo.register()
    if rsinfo is None or int(rsinfo.process_id) != pid:
        raise RuntimeError("pyRevit native registration does not belong to this process")
    endpoint = advertised_endpoint(rsinfo.server_host, rsinfo.server_port,
                                   os.environ.get("REVIT_MCP_ADVERTISED_HOST"))
    registry = TargetRegistry(pid, started, str(HOST_APP.version), endpoint,
                              instance_id=instance_id,
                              revit_build=str(HOST_APP.app.VersionBuild),
                              connector_version=__version__)
    uiapp = HOST_APP.uiapp
    last_idle = [0.0]

    def collect(sender, args):
        if not state["enabled"]:
            return
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
    state["enabled"] = True
    state["uiapp"], state["app"] = uiapp, uiapp.Application
    state["expire"] = registry.expire
    state["idling"] = framework.EventHandler[UI.Events.IdlingEventArgs](idle)
    state["view"] = framework.EventHandler[UI.Events.ViewActivatedEventArgs](collect)
    state["opened"] = framework.EventHandler[DB.Events.DocumentOpenedEventArgs](collect)
    state["closed"] = framework.EventHandler[DB.Events.DocumentClosedEventArgs](collect)
    # Retain exact delegates before the first subscription, including partial
    # attachment failure. Native removal of an unattached delegate is a no-op.
    domain.SetData(CALLBACK_SLOT, state)
    try:
        uiapp.Idling += state["idling"]
        uiapp.ViewActivated += state["view"]
        uiapp.Application.DocumentOpened += state["opened"]
        uiapp.Application.DocumentClosed += state["closed"]
    except Exception:
        try:
            remove_owned_callbacks(domain)
        except Exception as error:
            logger.warning("Partial identity attachment cleanup incomplete: %s", str(error))
        raise
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
