"""Client side of the bridge token: whether one request may carry it."""
import os
from urllib.parse import urlsplit

from revit_mcp.bridge_auth import TOKEN_ENV, get_or_create_token, require_token
from revit_mcp.identity import IdentityError

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def token_for(url):
    """Return the token to send to url, or raise IdentityError before anything is sent.

    Loopback: only when every listener on the port belongs to this Windows user.
    Other hosts: only an explicit REVIT_MCP_BRIDGE_TOKEN; this machine's own
    token never leaves it.
    """
    parsed = urlsplit(url)
    explicit = os.environ.get(TOKEN_ENV)
    if parsed.hostname not in LOOPBACK:
        if not explicit:
            raise IdentityError("bridge_token_unavailable",
                                "%s is not loopback; set %s to the Revit machine's bridge token"
                                % (parsed.hostname, TOKEN_ENV))
        return require_token(explicit, TOKEN_ENV)
    if os.name == "nt":
        from .windows_target_evidence import require_current_user_listeners
        require_current_user_listeners(parsed.port or (443 if parsed.scheme == "https" else 80))
    return require_token(explicit, TOKEN_ENV) if explicit else get_or_create_token()
