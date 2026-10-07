"""Read-only endpoint discovery: successful metadata and ownership, no binding."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from revit_mcp.identity import IdentityError, endpoint_url, validate_snapshot


def registration_directory():
    override = os.environ.get("REVIT_MCP_REGISTRATION_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA", Path.home() / ".local/share")) / "pyRevit/RevitMCP/registrations"


def configured_candidates():
    """Extension JSON bridges native registration to CPython without unpickling."""
    candidates = []
    records = []
    for path in registration_directory().glob("*.json"):
        try:
            records.append((path.stat().st_mtime, path))
        except OSError:
            continue
    # Recent live evidence must not be excluded by low stale PID filenames.
    records.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    for _, path in records[:256]:
        try:
            if path.stat().st_size > 65536:
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            endpoint_url(record.get("endpoint"))
            candidates.append(dict(endpoint=record["endpoint"], registration=record,
                                   source="native_registration_json"))
        except (OSError, ValueError, AttributeError):
            continue
    host = os.environ.get("REVIT_HOST", "127.0.0.1")
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    start = int(os.environ.get("REVIT_PORT_SCAN_START", os.environ.get("REVIT_PORT", "48884")))
    count = int(os.environ.get("REVIT_PORT_SCAN_COUNT", "6"))
    if count < 1 or count > 256 or start < 1 or start + count - 1 > 65535:
        raise ValueError("discovery scan must contain 1..256 valid ports")
    candidates.extend(dict(endpoint="http://%s:%s/revit_mcp" % (host, port), source="configured_probe")
                      for port in range(start, start + count))
    return candidates


async def metadata_handshake(endpoint):
    """Only HTTP 200 and validated identity JSON count as a connector."""
    endpoint = endpoint_url(endpoint)
    async with httpx.AsyncClient(timeout=2.0, follow_redirects=False) as client:
        response = await client.get(endpoint + "/metadata/")
        response.raise_for_status()
        if response.status_code != 200:
            raise IdentityError("invalid_metadata", "metadata handshake requires HTTP 200")
        data = response.json()
        validate_snapshot(data)
        return data


def validate_local_ownership(snapshot):
    """Check Windows process start time and TCP listener PID for loopback targets.

    Remote discovery uses its metadata handshake. Local ownership validation on
    other platforms must be supplied explicitly; it never invents local proof.
    """
    parsed = urlsplit(snapshot["endpoint"])
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return
    if os.name != "nt":
        raise IdentityError("ownership_unavailable", "Windows local ownership inspector unavailable")
    from .windows_target_evidence import validate_windows_ownership
    validate_windows_ownership(snapshot)


class TargetDiscovery:
    def __init__(self, directory, candidates=configured_candidates,
                 handshake=metadata_handshake, local_validator=validate_local_ownership):
        self.directory = directory
        self.candidates = candidates
        self.handshake = handshake
        self.local_validator = local_validator

    async def verified_handshake(self, endpoint):
        """Public routing seam: raw metadata plus local process/listener proof."""
        snapshot = await self.handshake(endpoint)
        data = validate_snapshot(snapshot)
        if data["endpoint"] != endpoint_url(endpoint):
            raise IdentityError("endpoint_mismatch", "metadata returned a different endpoint")
        if self.local_validator:
            self.local_validator(data)
        return snapshot

    async def discover(self):
        # Records are discovery hints. Validate each against the same handshake;
        # stale evidence must not veto a matching live record on a reused port.
        candidates = self.candidates() if callable(self.candidates) else self.candidates
        unique = {}
        for candidate in list(candidates)[:512]:
            endpoint = endpoint_url(candidate["endpoint"])
            unique.setdefault(endpoint, []).append(candidate)
        limit = asyncio.Semaphore(16)

        async def probe(endpoint, candidates):
            async with limit:
                try:
                    snapshot = await self.verified_handshake(endpoint)
                    data = validate_snapshot(snapshot)
                    matching, stale = [], []
                    for candidate in candidates:
                        record = candidate.get("registration")
                        if record and any(record[key] != data[key] for key in
                                          ("instance_id", "runtime_id", "process_id", "process_started_at", "endpoint")
                                          if key in record):
                            stale.append(dict(endpoint=endpoint, error_code="stale_registration",
                                              error="Registration no longer matches live endpoint ownership",
                                              process_id=record.get("process_id")))
                        else:
                            matching.append(candidate)
                    # A successful independent metadata/ownership proof remains
                    # usable even if every persisted record is stale.
                    candidate = next((c for c in matching if c.get("registration")),
                                     next(iter(matching), dict(source="metadata_handshake")))
                    result = self.directory.observe(snapshot, expected_endpoint=endpoint,
                                                    registration=candidate.get("registration"))
                    result["discovery_source"] = candidate.get("source", "configured")
                    return result, stale
                except Exception as error:
                    return None, [dict(endpoint=endpoint, error_code=getattr(error, "code", "discovery_failed"),
                                       error=str(error) or type(error).__name__)]

        results = await asyncio.gather(*(probe(endpoint, candidate) for endpoint, candidate in unique.items()))
        return dict(namespace=self.directory.namespace,
                    targets=[target for target, error in results if target is not None],
                    errors=[error for target, errors in results for error in errors])

    async def revalidate(self, target):
        return await self.directory.revalidate(target, self.verified_handshake)
