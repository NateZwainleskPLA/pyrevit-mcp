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
    for path in sorted(registration_directory().glob("*.json"))[:256]:
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
        # Registration records take precedence over port-range probes, and cannot
        # be bypassed by a duplicate unregistered candidate at the same endpoint.
        candidates = self.candidates() if callable(self.candidates) else self.candidates
        unique = {}
        for candidate in list(candidates)[:512]:
            endpoint = endpoint_url(candidate["endpoint"])
            existing = unique.get(endpoint)
            if existing is None or (candidate.get("registration") and not existing.get("registration")):
                unique[endpoint] = candidate
        limit = asyncio.Semaphore(16)

        async def probe(endpoint, candidate):
            async with limit:
                try:
                    snapshot = await self.verified_handshake(endpoint)
                    result = self.directory.observe(snapshot, expected_endpoint=endpoint,
                                                    registration=candidate.get("registration"))
                    result["discovery_source"] = candidate.get("source", "configured")
                    return result, None
                except Exception as error:
                    return None, dict(endpoint=endpoint, error_code=getattr(error, "code", "discovery_failed"),
                                      error=str(error) or type(error).__name__)

        results = await asyncio.gather(*(probe(endpoint, candidate) for endpoint, candidate in unique.items()))
        return dict(namespace=self.directory.namespace,
                    targets=[target for target, error in results if target is not None],
                    errors=[error for target, error in results if error is not None])

    async def revalidate(self, target):
        return await self.directory.revalidate(target, self.verified_handshake)
