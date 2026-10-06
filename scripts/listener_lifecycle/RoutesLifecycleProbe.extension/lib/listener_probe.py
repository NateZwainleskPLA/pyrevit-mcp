# -*- coding: utf-8 -*-
"""Disposable-host diagnostic only. No document access or model work."""
import copy
import json
import os
import sys
import threading
import time
import uuid

import System
import pyrevit
from pyrevit import UI, routes
from pyrevit.coreutils import envvars
from pyrevit.routes.server import get_active_server, get_routes, remove_route

KEY = 'MCP_ROUTES_LIFECYCLE_DIAGNOSTIC'
API = 'listener_lifecycle_probe'


def native_listener_snapshot():
    """Inspect Python listener objects, never activate or stop native Routes."""
    active = get_active_server()
    if active is None:
        return {'active': False}
    thread = getattr(active, 'server_thread', None)
    socket = active.server.socket
    result = {'active': True, 'object_id': str(id(active)),
              'retained_thread_id': getattr(thread, 'ident', None),
              'retained_thread_alive': thread.is_alive() if thread else None,
              'python_thread_count': threading.active_count()}
    try:
        result['socket_address'] = list(socket.getsockname())
        result['socket_fileno'] = socket.fileno()
    except Exception as ex:
        result['socket_error'] = str(ex)
    # _target is diagnostic implementation detail, not an ownership contract.
    owners = []
    for candidate in threading.enumerate():
        target = getattr(candidate, '_target', None)
        owner = getattr(target, '__self__', getattr(target, 'im_self', None))
        if owner is active.server:
            owners.append({'name': candidate.name, 'id': candidate.ident})
    result['observable_serve_threads'] = owners
    return result


class Probe(UI.IExternalEventHandler):
    def __init__(self, app, evidence_path):
        self.app = app
        self.path = evidence_path
        self.lock = threading.RLock()
        self.generation = str(uuid.uuid4())  # Diagnostic nonce, not target identity.
        self.stopped = False
        self.cleanup_complete = False
        self.running = False
        self.idle_count = 0
        self.event_count = 0
        self.cached = {}
        self.event = UI.ExternalEvent.Create(self)
        self.idle_delegate = self.on_idle
        self.app.Idling += self.idle_delegate
        try:
            self.capture()
        except Exception:
            self.stop()
            raise

    def capture(self):
        process = System.Diagnostics.Process.GetCurrentProcess()
        value = {
            'diagnostic_generation': self.generation, 'captured_at': time.time(),
            'process_id': process.Id,
            'process_started_at': process.StartTime.ToUniversalTime().ToString('o'),
            'python': sys.version, 'pyrevit_path': pyrevit.__file__,
            'revit_version': self.app.Application.VersionNumber,
            'revit_build': self.app.Application.VersionBuild,
            'clr': str(System.Environment.Version),
            'assemblies': [a.FullName for a in System.AppDomain.CurrentDomain.GetAssemblies()
                           if 'IronPython' in a.FullName or 'pyRevit' in a.FullName],
            'capture_thread': System.Threading.Thread.CurrentThread.ManagedThreadId,
            'listener': native_listener_snapshot(),
        }
        with self.lock:
            self.cached = value
        # Local evidence remains available if all HTTP endpoints stop responding.
        temporary = self.path + '.tmp'
        with open(temporary, 'w') as stream:
            json.dump(self.inspect(), stream, indent=2)
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rename(temporary, self.path)

    def inspect(self):
        with self.lock:
            value = copy.deepcopy(self.cached)
            value.update(stopped=self.stopped, running=self.running,
                         idle_count=self.idle_count, event_count=self.event_count,
                         snapshot_age_seconds=time.time() - value.get('captured_at', time.time()))
            return value

    def on_idle(self, sender, args):
        with self.lock:
            if not self.stopped:
                self.idle_count += 1

    def Execute(self, app):
        with self.lock:
            if self.stopped:
                return
            self.running = True
            self.event_count += 1
        try:
            self.capture()
        finally:
            with self.lock:
                self.running = False

    def GetName(self):
        return 'Read-only Routes lifecycle diagnostic'

    def stop(self):
        with self.lock:
            if self.cleanup_complete:
                return
            if self.stopped:
                raise RuntimeError('Previous diagnostic cleanup failed; replacement refused')
            if self.running or self.event.IsPending:
                raise RuntimeError('Probe event busy; wait before replacing or disposing')
            self.stopped = True
        # Fail visibly if cleanup fails; do not create a replacement after that.
        self.app.Idling -= self.idle_delegate
        self.event.Dispose()
        self.cleanup_complete = True


def initialize(app, path):
    old = envvars.get_pyrevit_env_var(KEY)
    if old is not None:
        old.stop()
    probe = Probe(app, path)
    def state(request):
        # Only copied primitives. No doc/uidoc/uiapp signature or API object access.
        expected = request.query_params.get('generation')
        if expected and expected != probe.generation:
            return routes.make_response({'error': 'stale_diagnostic_generation'}, status=409)
        return probe.inspect()
    try:
        api = routes.API(API)
        api.route('/state', methods=['GET'])(state)
    except Exception:
        # Retain failed cleanup state so the next Start cannot duplicate resources.
        envvars.set_pyrevit_env_var(KEY, probe)
        probe.stop()
        raise
    envvars.set_pyrevit_env_var(KEY, probe)
    return probe


def current():
    probe = envvars.get_pyrevit_env_var(KEY)
    if probe is None:
        raise RuntimeError('Diagnostic is not initialized')
    return probe


def stop():
    probe = current()
    probe.stop()
    # This namespace is exclusively owned by the disposable diagnostic.
    for route, handler in list(get_routes(API).items()):
        if route.pattern == '/state' and route.method == 'GET':
            remove_route(API, route.pattern, route.method)
    envvars.set_pyrevit_env_var(KEY, None)
