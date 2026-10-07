"""Bounded, sequential GET-only observation of an explicitly supplied local host.

No install, reload, listener stop/restart, operation submission, or model access.
"""
import argparse
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.parse import quote


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Process start time requires an explicit timezone')
    return parsed.astimezone(timezone.utc)


def same_instant(left, right):
    try:
        return instant(left) == instant(right)
    except (AttributeError, TypeError, ValueError):
        return False


def socket_owner(port):
    # Fixed script plus validated integer; no user text is interpolated as shell code.
    script = """$ErrorActionPreference = 'Stop'
$rows = @(Get-NetTCPConnection -State Listen -LocalPort PORT -ErrorAction Stop |
    ForEach-Object {
        $row = @{process_id=[int]$_.OwningProcess; process_started_at=$null;
            local_address=$_.LocalAddress; local_port=[int]$_.LocalPort}
        try {
            $p = Get-Process -Id $_.OwningProcess -ErrorAction Stop
            $started = $p.StartTime
            if ($null -eq $started) { throw 'Process start time unavailable' }
            $row.process_started_at = $started.ToUniversalTime().ToString('o')
        } catch {
            $row.ownership_error = $_.Exception.Message
        }
        $row
    })
ConvertTo-Json -InputObject $rows -Compress
""".replace('PORT', str(int(port)))
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


def owner_matches(rows, pid, started_at):
    return bool(rows) and all(isinstance(row, dict) and
                             not row.get('ownership_error') and row.get('process_id') == pid and
                             same_instant(row.get('process_started_at'), started_at)
                             for row in rows)


def observe(port, path, timeout):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    start = time.monotonic()
    expired = threading.Event()
    timer = None
    response = None
    row = {'path': path, 'response_bytes': 0}
    try:
        connection.connect()
        transport = connection.sock
        def expire():
            expired.set()
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError('Overall diagnostic request deadline exceeded')
        # Socket timeouts alone renew on each read, including drip-fed headers.
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        connection.request('GET', path, headers={'Connection': 'close'})
        response = connection.getresponse()
        row['status'] = response.status
        chunks = []
        # Preserve received byte count even if a truncated response stalls later.
        while True:
            if expired.is_set():
                raise TimeoutError('Overall diagnostic request deadline exceeded')
            chunk = response.read1(4096)
            if not chunk:
                break
            row['response_bytes'] += len(chunk)
            if row['response_bytes'] > 1024 * 1024:
                raise ValueError('Diagnostic response exceeded 1 MiB limit')
            chunks.append(chunk)
        if expired.is_set() or time.monotonic() - start >= timeout:
            raise TimeoutError('Overall diagnostic request deadline exceeded')
        body = b''.join(chunks).decode('utf-8')
        try:
            row['body'] = json.loads(body)
        except ValueError:
            row['body'] = body
        row['outcome'] = 'http_response'
    except Exception as ex:
        if expired.is_set():
            ex = TimeoutError('Overall diagnostic request deadline exceeded')
        row.update(outcome='transport_error', error_type=type(ex).__name__, error=str(ex))
    finally:
        if timer is not None:
            timer.cancel()
        if response is not None:
            response.close()
        row['elapsed_ms'] = round((time.monotonic() - start) * 1000, 2)
        connection.close()
    return row


def evaluate(rows, pid, started_at, previous_generation=None):
    by_path = {row['path']: row for row in rows if '?' not in row['path']}
    state = by_path['/listener_lifecycle_probe/state']
    native = by_path['/routes/sisters']
    unknown = by_path['/listener_lifecycle_probe/does-not-exist']
    body = state.get('body', {})
    state_ok = (state.get('status') == 200 and isinstance(body, dict) and
                body.get('process_id') == pid and
                body.get('process_started_at') is not None and
                same_instant(body['process_started_at'], started_at) and
                not body.get('stopped', True))
    stale = next((r for r in rows if '?generation=' in r['path']), None)
    counts = [len(row[key]) for row in rows
              for key in ('socket_owners_before', 'socket_owners_after') if key in row]
    pid_counts = [len(set(owner['process_id'] for owner in row[key])) for row in rows
                  for key in ('socket_owners_before', 'socket_owners_after') if key in row]
    return {
        'diagnostic_ready': state_ok,
        'native_sisters_responded': native.get('status') == 200 and isinstance(native.get('body'), list),
        'unknown_route_responded': unknown.get('outcome') == 'http_response' and
            400 <= unknown.get('status', 0) < 600,
        'generation_changed': None if previous_generation is None else
            state_ok and body.get('diagnostic_generation') != previous_generation,
        'stale_diagnostic_rejected': None if previous_generation is None else
            stale is not None and stale.get('status') == 409 and
            stale.get('body') == {'error': 'stale_diagnostic_generation'},
        'native_acceptance': 'not established by HTTP observations alone',
        'listen_socket_count': max(counts) if counts else None,
        'unique_owner_process_count': max(pid_counts) if pid_counts else None,
    }


def checks_pass(checks):
    required = ('diagnostic_ready', 'native_sisters_responded', 'unknown_route_responded')
    optional = ('generation_changed', 'stale_diagnostic_rejected')
    return (all(checks.get(name) is True for name in required) and
            all(checks.get(name) is True for name in optional if checks.get(name) is not None))


def collect(port, pid, started_at, phase, output, previous_generation=None, timeout=3):
    receipt = {'phase': phase, 'process_id': pid, 'process_started_at': started_at,
               'endpoint': 'http://127.0.0.1:%s' % port, 'observations': []}
    def save():
        Path(output).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    paths = ['/listener_lifecycle_probe/state', '/routes/sisters',
             '/listener_lifecycle_probe/does-not-exist']
    if previous_generation:
        paths.append('/listener_lifecycle_probe/state?generation=' + quote(previous_generation, safe=''))
    for path in paths:
        try:
            owners = socket_owner(port)
        except Exception as ex:
            receipt['error'] = 'socket_owner_unavailable; no request sent: ' + str(ex)
            save()
            return receipt
        receipt['last_socket_owners'] = owners
        receipt['listen_socket_count'] = max(receipt.get('listen_socket_count', 0), len(owners))
        receipt['unique_owner_process_count'] = max(
            receipt.get('unique_owner_process_count', 0), len(set(owner['process_id'] for owner in owners)))
        receipt['listen_socket_count_interpretation'] = (
            'Maximum observed Listen row count, not unique PID count; '
            'multiple same-PID sockets are a hypothesis, not an established outage cause')
        if not owner_matches(owners, pid, started_at):
            receipt['error'] = 'socket_owner_mismatch; no request sent to the observed owner'
            save()
            return receipt
        row = observe(port, path, timeout)
        row['socket_owners_before'] = owners
        receipt['observations'].append(row)
        try:
            row['socket_owners_after'] = socket_owner(port)
            receipt['listen_socket_count'] = max(receipt['listen_socket_count'],
                                                len(row['socket_owners_after']))
            receipt['unique_owner_process_count'] = max(
                receipt['unique_owner_process_count'],
                len(set(owner['process_id'] for owner in row['socket_owners_after'])))
        except Exception as ex:
            receipt['error'] = 'socket_owner_unavailable_after_response: ' + str(ex)
            save()
            return receipt
        save()
        if not owner_matches(row['socket_owners_after'], pid, started_at):
            receipt['error'] = 'socket_owner_changed; response not accepted as target evidence'
            save()
            return receipt
    receipt['checks'] = evaluate(receipt['observations'], pid, started_at, previous_generation)
    save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--started-at', required=True)
    parser.add_argument('--phase', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--previous-generation')
    parser.add_argument('--timeout', default=3, type=float)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.pid <= 0 or not 0 < args.timeout <= 10:
        parser.error('Require valid port/PID and timeout in (0, 10] seconds')
    instant(args.started_at)
    receipt = collect(args.port, args.pid, args.started_at, args.phase, args.output,
                      args.previous_generation, args.timeout)
    print(json.dumps(receipt, indent=2))
    checks = receipt.get('checks', {})
    return 0 if checks_pass(checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
