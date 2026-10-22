# -*- coding: utf-8 -*-
"""Shared-secret check on every revit_mcp Routes request.

pyRevit does not pass HTTP headers to route handlers, so an Authorization
header or a Host check cannot work here. Clients send the secret in the JSON
body instead, GET requests included. A web page cannot read the secret, so it
cannot forge a request, even after DNS rebinding points its hostname at
127.0.0.1.

The secret is a file in the Windows user's LOCALAPPDATA, which other users
cannot read. Processes running as the same user can, and so can already
control Revit; that is the trust boundary. Shared by IronPython (Revit) and
CPython (MCP server), so this module supports IronPython 2.7.
"""
import binascii
import json
import os
import re

from .identity import IdentityError, string_types
from .routing_policy import strip_callback

TOKEN_FIELD = "bridge_token"
TOKEN_ENV = "REVIT_MCP_BRIDGE_TOKEN"
_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_ARGUMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# The connector's own token file is missing or unreadable: not the caller's fault.
SERVER_ERRORS = frozenset(("bridge_token_unavailable", "bridge_token_invalid"))


class BridgeAuthError(IdentityError):
    pass


def token_path():
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise BridgeAuthError("bridge_token_unavailable", "LOCALAPPDATA is not set; cannot locate the bridge token")
    return os.path.join(root, "RevitMCP", "bridge-token")


def require_token(value, source="bridge_token"):
    if not isinstance(value, string_types) or not _TOKEN.match(value):
        raise BridgeAuthError("bridge_unauthorized", "%s must be 64 lowercase hex characters" % source)
    return value


def _read(path):
    try:
        with open(path) as stream:
            value = stream.read().strip()
    except (IOError, OSError):
        if os.path.exists(path):
            raise BridgeAuthError("bridge_token_unavailable", "Cannot read the bridge token at " + path)
        return None
    if not _TOKEN.match(value):
        raise BridgeAuthError("bridge_token_invalid",
                              "%s is not a valid bridge token; delete it and a new one is created" % path)
    return value


def get_or_create_token():
    """Return this user's token, creating it on first use by either side."""
    path = token_path()
    token = _read(path)
    if token is not None:
        return token
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            if not os.path.isdir(directory):
                raise BridgeAuthError("bridge_token_unavailable", "Cannot create " + directory)
    staging = "%s.%s.tmp" % (path, binascii.hexlify(os.urandom(8)).decode("ascii"))
    try:
        with open(staging, "w") as stream:
            stream.write(binascii.hexlify(os.urandom(32)).decode("ascii"))
    except (IOError, OSError):
        raise BridgeAuthError("bridge_token_unavailable", "Cannot write the bridge token in " + directory)
    try:
        # Windows rename fails if the target exists: when Revit and a client
        # create the token at the same time, both end up reading the winner's.
        os.rename(staging, path)
    except OSError:
        try:
            os.remove(staging)
        except OSError:
            pass
    token = _read(path)
    if token is None:
        raise BridgeAuthError("bridge_token_unavailable", "Bridge token was not created at " + path)
    return token


def tokens_equal(supplied, expected):
    """Compare two validated 64-hex tokens without stopping at the first difference."""
    difference = 0
    for left, right in zip(supplied, expected):
        difference |= ord(left) ^ ord(right)
    return difference == 0 and len(supplied) == len(expected)


def take_token(request):
    """Remove and return the token so handlers, receipts and logs never see it."""
    query = getattr(request, "query_params", None)
    if isinstance(query, dict) and TOKEN_FIELD in query:
        query.pop(TOKEN_FIELD, None)
        raise BridgeAuthError("bridge_token_in_url", "Send bridge_token in the JSON body, never in the URL")
    data = getattr(request, "data", None)
    if isinstance(data, (bytes, bytearray)) and not isinstance(data, string_types):
        try:
            data = bytes(data).decode("utf-8")
        except ValueError:
            return None
    if isinstance(data, string_types):
        try:
            data = json.loads(data)
        except ValueError:
            return None
        if isinstance(data, dict):
            request.data = data
    if isinstance(data, dict):
        return data.pop(TOKEN_FIELD, None)
    return None


def check_request(request, expected=get_or_create_token):
    """None when the request carries this user's token, else the BridgeAuthError."""
    try:
        supplied = take_token(request)
        if supplied is None:
            raise BridgeAuthError("bridge_unauthorized", "Missing bridge_token")
        require_token(supplied)
        if not tokens_equal(supplied, expected()):
            raise BridgeAuthError("bridge_unauthorized", "Invalid bridge_token")
    except BridgeAuthError as error:
        return error
    return None


def authorize_request(request, expected=get_or_create_token):
    """Return a denial response, or None when the request may proceed."""
    from pyrevit import routes
    # pyRevit posts the response to callbackUrl after the handler returns;
    # remove it before anything else, including a denial.
    if strip_callback(request):
        return routes.make_response(data={"status": "error", "error_code": "callback_unsupported",
                                          "error": "callbackUrl is not supported", "effects": "none"}, status=409)
    error = check_request(request, expected)
    if error is None:
        return None
    return routes.make_response(data={"status": "error", "error_code": error.code, "error": str(error),
                                      "effects": "none"},
                                status=503 if error.code in SERVER_ERRORS else 401)


def _argument_names(handler):
    code = getattr(handler, "__code__", None) or handler.func_code
    if code.co_flags & 0x0C:  # *args / **kwargs: pyRevit passes named arguments only
        raise ValueError("Route handler %s must use named arguments only" % handler.__name__)
    return list(code.co_varnames[:code.co_argcount])


def _with_arguments(names, call):
    """Build a function whose named arguments are exactly names.

    pyRevit reads a handler's argument names: uiapp/uidoc/doc run it on Revit's
    API thread, and each named argument receives a request value. A guard must
    expose the same names as the handler it wraps, or routing changes.
    """
    for name in names:
        if not _ARGUMENT.match(name):
            raise ValueError("Unsupported route argument name: %r" % (name,))
    source = "def routed(%s):\n    return _call(dict(%s))\n" % (
        ", ".join("%s=None" % name for name in names),
        ", ".join("%s=%s" % (name, name) for name in names))
    scope = {"_call": call}
    exec(compile(source, "<revit_mcp.bridge_auth>", "exec"), scope)
    return scope["routed"]


class AuthenticatedAPI(object):
    """Root Routes API: every handler requires the bridge token before it runs.

    Wrap the real routes.API once in startup, beneath TargetedAPI, DisabledAPI
    and the metadata routes, so no registration path can skip the check.
    """
    def __init__(self, api, authorize=authorize_request):
        self.api = api
        self.authorize = authorize

    def route(self, endpoint, **options):
        register = self.api.route(endpoint, **options)

        def decorate(handler):
            names = _argument_names(handler)
            exposed = names if "request" in names else names + ["request"]

            def call(values):
                denied = self.authorize(values["request"])
                if denied is not None:
                    return denied
                return handler(**dict((name, values[name]) for name in names))

            routed = _with_arguments(exposed, call)
            routed.__name__ = handler.__name__
            routed.__doc__ = handler.__doc__
            return register(routed)
        return decorate
