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
from scripts.listener_lifecycle.source_audit import audit, selected, main as audit_main

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


@pytest.mark.parametrize('shape', ['missing_definition', 'unobserved_shutdown'])
def test_source_audit_unsupported_shape_is_inconclusive(tmp_path, shape, monkeypatch, capsys):
    server = tmp_path / 'pyrevitlib/pyrevit/routes/server'
    server.mkdir(parents=True)
    (server / 'server.py').write_text('''
class ThreadedHttpServer(ThreadingMixIn, HTTPServer):
    def shutdown(self):
        self.socket.close()
class RoutesServer:
    def __init__(self, host, port):
        self.server = ThreadedHttpServer((host, port), HttpRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.start()
    def stop(self):
        self.server.shutdown()
        self.server_thread.join()
''')
    (server / '__init__.py').write_text('''
def activate_server():
    return server.RoutesServer('127.0.0.1', 48884)
''')
    if shape == 'missing_definition':
        (server / 'server.py').write_text('pass\n')
    result = audit(tmp_path)
    assert result['audit_status'] == 'unsupported_source'
    assert result['duplicate_serve_loops'] is None
    assert result['socket_closed_before_shutdown'] is None
    assert result['error']
    assert all(row['sha256'] for row in result['source_files'])
    output = tmp_path / 'inconclusive.json'
    monkeypatch.setattr(sys, 'argv', ['source_audit', str(tmp_path), '--output', str(output)])
    assert audit_main() == 2
    assert json.loads(output.read_text())['audit_status'] == 'unsupported_source'
    assert json.loads(capsys.readouterr().out)['duplicate_serve_loops'] is None


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


def test_constructor_capture_cleanup_failure_retains_owner(monkeypatch):
    ns, app, _ = host_namespace(monkeypatch)
    created = []
    def create(handler):
        event = SimpleNamespace(IsPending=False)
        def fail_dispose():
            raise RuntimeError('dispose failed')
        event.Dispose = fail_dispose
        created.append(event)
        return event
    ns['UI'].ExternalEvent.Create = create
    def fail_capture(self):
        raise RuntimeError('initial capture failed')
    monkeypatch.setattr(ns['Probe'], 'capture', fail_capture)
    with pytest.raises(RuntimeError, match='dispose failed'):
        ns['initialize'](app, 'unused')
    retained = ns['envvars'].get_pyrevit_env_var(ns['KEY'])
    assert retained is not None and retained.event is created[0]
    assert retained.stopped and not retained.cleanup_complete
    with pytest.raises(RuntimeError, match='Previous diagnostic cleanup failed'):
        ns['initialize'](app, 'unused')
    assert len(created) == 1


def test_failed_initial_capture_cleanup_allows_next_clean_start(monkeypatch):
    ns, app, _ = host_namespace(monkeypatch)
    original_capture = ns['Probe'].capture
    def fail_capture(self):
        raise RuntimeError('initial capture failed')
    monkeypatch.setattr(ns['Probe'], 'capture', fail_capture)
    with pytest.raises(RuntimeError, match='initial capture failed'):
        ns['initialize'](app, 'unused')
    failed = ns['envvars'].get_pyrevit_env_var(ns['KEY'])
    assert failed.cleanup_complete and failed.event.disposed
    assert not app.Idling.callbacks
    monkeypatch.setattr(ns['Probe'], 'capture', original_capture)
    fresh = ns['initialize'](app, 'unused')
    assert app.Idling.callbacks == [fresh.idle_delegate]


def test_partial_subscription_failure_cleans_retained_resources(monkeypatch):
    ns, app, _ = host_namespace(monkeypatch)
    original_attach = type(app.Idling).__iadd__
    def attach_then_fail(self, delegate):
        original_attach(self, delegate)
        raise RuntimeError('subscription failed after attach')
    monkeypatch.setattr(type(app.Idling), '__iadd__', attach_then_fail)
    with pytest.raises(RuntimeError, match='subscription failed after attach'):
        ns['initialize'](app, 'unused')
    failed = ns['envvars'].get_pyrevit_env_var(ns['KEY'])
    assert failed.cleanup_complete and failed.event.disposed
    assert not app.Idling.callbacks


def test_unavailable_retained_delegate_blocks_replacement_without_clearing_owner(monkeypatch):
    ns, app, _ = host_namespace(monkeypatch)
    old = ns['initialize'](app, 'unused')
    def unavailable(self, delegate):
        raise RuntimeError('retained delegate unavailable')
    monkeypatch.setattr(type(app.Idling), '__isub__', unavailable)
    with pytest.raises(RuntimeError, match='retained delegate unavailable'):
        ns['initialize'](app, 'unused')
    assert ns['envvars'].get_pyrevit_env_var(ns['KEY']) is old
    assert old.stopped and not old.cleanup_complete and not old.event.disposed
    old.on_idle(app, None)
    assert old.idle_count == 0
    with pytest.raises(RuntimeError, match='Previous diagnostic cleanup failed'):
        ns['initialize'](app, 'unused')
    assert app.Idling.callbacks == [old.idle_delegate]


def test_reloaded_probe_class_can_retire_old_instance(monkeypatch):
    ns, app, _ = host_namespace(monkeypatch)
    old = ns['initialize'](app, 'unused')
    capture = ns['Probe'].capture
    exec(selected(HOST.read_text(), 'Probe'), ns)
    monkeypatch.setattr(ns['Probe'], 'capture', capture)
    fresh = ns['initialize'](app, 'unused')
    assert type(fresh) is not type(old)
    assert old.cleanup_complete and old.event.disposed
    assert app.Idling.callbacks == [fresh.idle_delegate]


def test_no_automatic_registration_or_context_route_signature():
    tree = ast.parse((ROOT / 'RoutesLifecycleProbe.extension/startup.py').read_text())
    assert not any(isinstance(node, ast.Call) for node in ast.walk(tree))
    state = next(node for node in ast.walk(ast.parse(HOST.read_text()))
                 if isinstance(node, ast.FunctionDef) and node.name == 'state')
    assert [arg.arg for arg in state.args.args] == ['request']


@pytest.mark.parametrize('storage', ['_target', '_Thread__target'])
@pytest.mark.parametrize('wrapped', [False, True])
@pytest.mark.parametrize('method_style', ['py3', 'py2'])
def test_listener_thread_observation_supports_engine_and_server_variants(storage, wrapped, method_style):
    class HTTPServer:
        socket = SimpleNamespace(getsockname=lambda: ('127.0.0.1', 48884), fileno=lambda: 7)
        def serve_forever(self):
            pass
    class RoutesServer:
        server = HTTPServer()
        def _serve_forever(self):
            pass
    active = RoutesServer()
    target = active._serve_forever if wrapped else active.server.serve_forever
    if method_style == 'py2':
        target = SimpleNamespace(im_self=active if wrapped else active.server,
                                 __name__='_serve_forever' if wrapped else 'serve_forever')
    worker = SimpleNamespace(name='listener', ident=17, is_alive=lambda: True)
    setattr(worker, storage, target)
    active.server_thread = worker
    unknown = SimpleNamespace(name='target-unavailable', ident=18)
    ns = dict(get_active_server=lambda: active,
              threading=SimpleNamespace(active_count=lambda: 2, enumerate=lambda: [worker, unknown]))
    exec(selected(HOST.read_text(), 'native_listener_snapshot'), ns)
    result = ns['native_listener_snapshot']()
    assert result['observable_serve_threads'] == [{'name': 'listener', 'id': 17}]
    assert result['unobservable_target_threads'] == [{'name': 'target-unavailable', 'id': 18}]
    assert 'not proof' in result['serve_thread_observation']


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


@pytest.mark.skipif(sys.platform != 'win32', reason='Execute embedded PowerShell with controlled OS doubles')
def test_windows_owner_query_retains_unreadable_owner_row(monkeypatch):
    import scripts.listener_lifecycle.collect as module
    actual_run = module.subprocess.run
    # Exercise the actual embedded script; only its OS data sources are replaced.
    fixture = '''
function Get-NetTCPConnection {
    [CmdletBinding()] param([string]$State, [int]$LocalPort)
    [pscustomobject]@{OwningProcess=17; LocalAddress='0.0.0.0'; LocalPort=$LocalPort}
    [pscustomobject]@{OwningProcess=99; LocalAddress='127.0.0.1'; LocalPort=$LocalPort}
}
function Get-Process {
    [CmdletBinding()] param([int]$Id)
    if ($Id -eq 17) {
        [pscustomobject]@{Id=17; StartTime=[datetime]'2026-10-05T12:00:00Z'}
    } else {
        [pscustomobject]@{Id=$Id; StartTime=$null}
    }
}
'''
    def execute(args, **kwargs):
        args = list(args)
        args[-1] = fixture + args[-1]
        return actual_run(args, **kwargs)
    monkeypatch.setattr(module.subprocess, 'run', execute)
    rows = socket_owner(48884)
    assert len(rows) == 2
    assert rows[1]['process_id'] == 99 and rows[1]['process_started_at'] is None
    assert rows[1]['local_address'] == '127.0.0.1' and rows[1]['local_port'] == 48884
    assert rows[1]['ownership_error']
    assert owner_matches(rows[:1], 17, START)
    assert not owner_matches(rows, 17, START)


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


@pytest.mark.parametrize('phase', ['headers', 'body'])
def test_collector_overall_deadline_bounds_slow_drip(phase):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if phase == 'headers':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Drip: ')
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', '30')
                    self.end_headers()
                for unused in range(30):
                    self.wfile.write(b'x')
                    self.wfile.flush()
                    time.sleep(0.012)
                if phase == 'headers':
                    self.wfile.write(b'\r\nContent-Length: 1\r\n\r\nx')
            except OSError:
                pass  # The bounded diagnostic deliberately closes its socket.
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = observe(server.server_address[1], '/state', 0.06)
        assert result['outcome'] == 'transport_error'
        assert result['error_type'] == 'TimeoutError'
        assert result['elapsed_ms'] < 250
        if phase == 'body':
            assert 0 < result['response_bytes'] < 30
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
