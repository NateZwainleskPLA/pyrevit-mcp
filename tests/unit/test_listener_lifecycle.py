import ast
import copy
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from scripts.listener_lifecycle.collect import collect, evaluate, observe, owner_matches, socket_owner
from scripts.listener_lifecycle.source_audit import audit, selected

ROOT = Path(__file__).resolve().parents[2] / 'scripts/listener_lifecycle'
HOST = ROOT / 'RoutesLifecycleProbe.extension/lib/listener_probe.py'
START = '2026-10-05T12:00:00+00:00'


def test_source_audit_exercises_double_start_and_close_order(tmp_path):
    # Minimal source fixture preserves actual inspected lifecycle call sites.
    server = tmp_path / 'pyrevitlib/pyrevit/routes/server'
    server.mkdir(parents=True)
    (server / 'server.py').write_text('''
class ThreadedHttpServer(ThreadingMixIn, HTTPServer):
    def shutdown(self):
        self.socket.close()
        HTTPServer.shutdown(self)
class RoutesServer:
    def __init__(self, host, port):
        self.server = ThreadedHttpServer((host, port), HttpRequestHandler)
        self.start()
    def start(self):
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
    def stop(self):
        self.server.shutdown()
        self.server_thread.join()
''')
    init = server / '__init__.py'
    init.write_text('''
def activate_server():
    active = envvars.get_pyrevit_env_var(envvars.ROUTES_SERVER)
    if not active:
        info = serverinfo.register()
        active = server.RoutesServer(info.server_host, info.server_port)
        active.start()
        envvars.set_pyrevit_env_var(envvars.ROUTES_SERVER, active)
        return active
''')
    before = audit(tmp_path)
    assert before['first_activation_worker_count'] == 2
    assert before['retained_worker_count'] == 1
    assert before['duplicate_serve_loops']
    assert before['socket_closed_before_shutdown']
    # Demonstrates the audit goes green when the duplicate start is removed.
    init.write_text(init.read_text().replace('        active.start()\n', ''))
    assert audit(tmp_path)['first_activation_worker_count'] == 1


def host_namespace(monkeypatch):
    class Hook:
        def __init__(self):
            self.callbacks = []
        def __iadd__(self, callback):
            self.callbacks.append(callback)
            return self
        def __isub__(self, callback):
            self.callbacks.remove(callback)
            return self
    class Event:
        IsPending = False
        disposed = False
        def Dispose(self):
            self.disposed = True
    store, handlers = {}, {}
    def route(pattern, methods):
        def register(fn):
            handlers[pattern] = fn
            return fn
        return register
    ns = dict(copy=copy, threading=threading, time=time,
              uuid=__import__('uuid'), UI=SimpleNamespace(IExternalEventHandler=object,
              ExternalEvent=SimpleNamespace(Create=lambda handler: Event())),
              envvars=SimpleNamespace(get_pyrevit_env_var=store.get,
              set_pyrevit_env_var=lambda key, value: store.update({key: value})),
              routes=SimpleNamespace(API=lambda name: SimpleNamespace(route=route),
              make_response=lambda data, status: {'status': status, 'data': data}),
              KEY='diagnostic', API='listener_lifecycle_probe')
    source = HOST.read_text()
    exec(selected(source, 'Probe'), ns)
    exec(selected(source, 'initialize'), ns)
    def capture(self):
        self.cached = {'captured_at': time.time(), 'diagnostic_generation': self.generation}
    monkeypatch.setattr(ns['Probe'], 'capture', capture)
    return ns, SimpleNamespace(Idling=Hook()), handlers


@pytest.mark.parametrize('busy', ['running', 'pending'])
def test_replace_refuses_busy_event_without_detaching(monkeypatch, busy):
    ns, app, handlers = host_namespace(monkeypatch)
    old = ns['initialize'](app, 'unused')
    if busy == 'running':
        old.running = True
    else:
        old.event.IsPending = True
    with pytest.raises(RuntimeError, match='busy'):
        ns['initialize'](app, 'unused')
    assert app.Idling.callbacks == [old.idle_delegate]
    assert not old.stopped and not old.event.disposed


def test_replacement_detaches_exact_delegate_and_expires_nonce(monkeypatch):
    ns, app, handlers = host_namespace(monkeypatch)
    first = ns['initialize'](app, 'unused')
    old_handler = handlers['/state']
    second = ns['initialize'](app, 'unused')
    assert first.stopped and first.event.disposed
    assert app.Idling.callbacks == [second.idle_delegate]
    assert first.generation != second.generation
    req = SimpleNamespace(query_params={'generation': first.generation})
    assert handlers['/state'](req)['status'] == 409
    # A worker holding an old callback can only receive expired diagnostic data.
    assert old_handler(SimpleNamespace(query_params={}))['stopped']
    # Retired callback cannot execute; inspecting copied state cannot mutate it.
    first.Execute(app)
    assert first.event_count == 0
    state = second.inspect()
    state['stopped'] = True
    assert not second.stopped


def test_cleanup_failure_prevents_replacement(monkeypatch):
    ns, app, handlers = host_namespace(monkeypatch)
    old = ns['initialize'](app, 'unused')
    def fail():
        raise RuntimeError('dispose failed')
    old.event.Dispose = fail
    with pytest.raises(RuntimeError, match='dispose failed'):
        ns['initialize'](app, 'unused')
    with pytest.raises(RuntimeError, match='Previous diagnostic cleanup failed'):
        ns['initialize'](app, 'unused')
    assert old.stopped and not old.cleanup_complete
    assert not app.Idling.callbacks


def test_registration_failure_detaches_new_resources(monkeypatch):
    ns, app, handlers = host_namespace(monkeypatch)
    def fail(name):
        raise RuntimeError('route registration failed')
    ns['routes'].API = fail
    with pytest.raises(RuntimeError, match='route registration failed'):
        ns['initialize'](app, 'unused')
    failed = ns['envvars'].get_pyrevit_env_var(ns['KEY'])
    assert failed.stopped and failed.cleanup_complete and failed.event.disposed
    assert app.Idling.callbacks == []


def test_failed_capture_always_releases_running_flag(monkeypatch):
    ns, app, _ = host_namespace(monkeypatch)
    probe = ns['initialize'](app, 'unused')
    def fail(self):
        raise RuntimeError('snapshot failed')
    monkeypatch.setattr(type(probe), 'capture', fail)
    with pytest.raises(RuntimeError, match='snapshot failed'):
        probe.Execute(app)
    assert not probe.running
    probe.stop()
    assert probe.cleanup_complete


def test_no_automatic_registration_or_context_route_signature():
    tree = ast.parse((ROOT / 'RoutesLifecycleProbe.extension/startup.py').read_text())
    assert not any(isinstance(node, ast.Call) for node in ast.walk(tree))
    state = next(node for node in ast.walk(ast.parse(HOST.read_text()))
                 if isinstance(node, ast.FunctionDef) and node.name == 'state')
    assert [arg.arg for arg in state.args.args] == ['request']


def receipt_rows():
    return [dict(path='/listener_lifecycle_probe/state', status=200,
                 body=dict(process_id=17, process_started_at=START, stopped=False,
                           diagnostic_generation='new')),
            dict(path='/routes/sisters', status=200, body=[]),
            dict(path='/listener_lifecycle_probe/does-not-exist', status=404,
                 outcome='http_response'),
            dict(path='/listener_lifecycle_probe/state?generation=old', status=409,
                 body={'error': 'stale_diagnostic_generation'})]


def test_outage_evaluation_does_not_confuse_probe_and_native_health():
    rows = receipt_rows()
    checks = evaluate(rows, 17, START, 'old')
    assert all(v for k, v in checks.items() if k != 'native_acceptance')
    rows[1] = dict(path='/routes/sisters', outcome='transport_error', response_bytes=0)
    checks = evaluate(rows, 17, START, 'old')
    assert checks['diagnostic_ready'] and not checks['native_sisters_responded']
    assert not evaluate(rows, 18, START)['diagnostic_ready']
    rows[0]['body']['process_started_at'] = 'invalid-start-time'
    assert not evaluate(rows, 17, START)['diagnostic_ready']
    rows[0]['body']['process_started_at'] = '2026-10-05T12:00:00'
    assert not evaluate(rows, 17, START)['diagnostic_ready']


def test_collector_never_sends_request_after_owner_mismatch(monkeypatch, tmp_path):
    import scripts.listener_lifecycle.collect as module
    owners = [{'process_id': 99, 'process_started_at': START}]
    monkeypatch.setattr(module, 'socket_owner', lambda port: owners)
    monkeypatch.setattr(module, 'observe', lambda *args: pytest.fail('wrong owner contacted'))
    output = tmp_path / 'receipt.json'
    result = collect(48884, 17, START, 'baseline', output)
    assert 'socket_owner_mismatch' in result['error']
    assert json.loads(output.read_text())['observations'] == []
    assert not owner_matches([], 17, START)
    assert not owner_matches([{'process_id': 17, 'process_started_at': '2026-10-05T13:00:00Z'}], 17, START)


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows socket ownership query')
def test_windows_socket_owner_query_uses_local_python_fixture():
    # No Revit host: catch embedded PowerShell syntax and actual OS-query errors.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        rows = socket_owner(listener.getsockname()[1])
    assert rows and all(row['process_id'] == os.getpid() for row in rows)
    assert owner_matches(rows, os.getpid(), rows[0]['process_started_at'])


def test_collector_persists_partial_receipt_on_ownership_inspection_failure(monkeypatch, tmp_path):
    import scripts.listener_lifecycle.collect as module
    calls = iter([[{'process_id': 17, 'process_started_at': START}], RuntimeError('OS query failed')])
    def owner(port):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(module, 'socket_owner', owner)
    monkeypatch.setattr(module, 'observe', lambda *args: receipt_rows()[0])
    output = tmp_path / 'partial.json'
    result = collect(48884, 17, START, 'after-reload', output)
    assert 'unavailable_after_response' in result['error']
    assert len(json.loads(output.read_text())['observations']) == 1


def test_collector_rechecks_owner_and_never_falls_back(monkeypatch, tmp_path):
    import scripts.listener_lifecycle.collect as module
    calls = iter([[{'process_id': 17, 'process_started_at': START}],
                  [{'process_id': 99, 'process_started_at': START}]])
    monkeypatch.setattr(module, 'socket_owner', lambda port: next(calls))
    seen = []
    def request(port, path, timeout):
        seen.append(path)
        return receipt_rows()[0]
    monkeypatch.setattr(module, 'observe', request)
    result = collect(48884, 17, START, 'after-reload', tmp_path / 'changed.json')
    assert 'socket_owner_changed' in result['error']
    assert seen == ['/listener_lifecycle_probe/state']


def test_collector_preserves_zero_byte_timeout_from_local_http_fixture():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.1)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = observe(server.server_address[1], '/routes/sisters', 0.02)
        assert result['outcome'] == 'transport_error'
        assert result['response_bytes'] == 0
        assert result['error_type'] == 'TimeoutError'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
