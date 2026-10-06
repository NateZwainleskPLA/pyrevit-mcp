"""Windows process/listener ownership evidence, separate from UUID identity."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import socket
from urllib.parse import urlsplit

from revit_mcp.identity import IdentityError


def _process_start(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise IdentityError("stale_registration", "registered process is unavailable")
    try:
        creation, exit_time, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                      ctypes.byref(system), ctypes.byref(user)):
            raise IdentityError("ownership_unavailable", "cannot inspect registered process lifetime")
        ticks = creation.dwLowDateTime + (creation.dwHighDateTime << 32)
        return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
    finally:
        kernel.CloseHandle(handle)


def process_started_at(pid):
    """UTC ISO-8601 creation timestamp for a retained Popen PID (read-only)."""
    return _process_start(pid).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _listener_pids(port, ipv6=False):
    iphelper = ctypes.WinDLL("iphlpapi", use_last_error=True)
    function = iphelper.GetExtendedTcpTable
    function.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                         wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    function.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    family = 23 if ipv6 else 2  # AF_INET6 / AF_INET
    # TCP_TABLE_OWNER_PID_LISTENER; only listening sockets are returned.
    result = function(None, ctypes.byref(size), False, family, 3, 0)
    if result not in (0, 122):  # ERROR_INSUFFICIENT_BUFFER
        raise IdentityError("ownership_unavailable", "cannot inspect listener ownership")
    for _ in range(3):  # table may grow between allocation and the second call
        buffer = ctypes.create_string_buffer(size.value)
        result = function(buffer, ctypes.byref(size), False, family, 3, 0)
        if result == 122:
            continue
        if result != 0:
            raise IdentityError("ownership_unavailable", "cannot inspect listener ownership")
        count = int.from_bytes(buffer.raw[:4], "little")
        stride, port_offset, pid_offset = (56, 20, 52) if ipv6 else (24, 8, 20)
        if 4 + count * stride > len(buffer):
            raise IdentityError("ownership_unavailable", "invalid TCP ownership table")
        owners = set()
        for index in range(count):
            offset = 4 + index * stride
            encoded_port = int.from_bytes(buffer.raw[offset + port_offset:offset + port_offset + 4], "little")
            if socket.ntohs(encoded_port & 0xffff) == port:
                owners.add(int.from_bytes(buffer.raw[offset + pid_offset:offset + pid_offset + 4], "little"))
        return owners
    raise IdentityError("ownership_unavailable", "listener ownership changed during inspection")


def validate_windows_ownership(snapshot):
    actual = _process_start(snapshot["process_id"])
    try:
        expected = datetime.fromisoformat(snapshot["process_started_at"].replace("Z", "+00:00"))
    except ValueError:
        raise IdentityError("stale_registration", "invalid process start timestamp")
    if expected.tzinfo is None or expected != actual:
        raise IdentityError("stale_registration", "PID has a different process start time")
    endpoint = urlsplit(snapshot["endpoint"])
    owners = _listener_pids(endpoint.port, ipv6=endpoint.hostname == "::1")
    if endpoint.hostname == "localhost":
        owners |= _listener_pids(endpoint.port, ipv6=True)
    if snapshot["process_id"] not in owners:
        raise IdentityError("stale_registration", "registered process does not own this listener port")
