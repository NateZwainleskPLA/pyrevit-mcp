# -*- coding: utf-8 -*-
"""Opt-in dialog policy primitives; importing this module subscribes nothing.

No built-in Revit dialog IDs are supported. A host must supply an evidence-backed
catalog and retain the subscription state across repeated initialization. This
module neither resolves targets/documents nor owns execution/operation states.
Compatible with IronPython 2.7 and CPython for offline tests.
"""
import copy
import threading
import time

try:
    _string_types = (basestring,)
    _integer_types = (int, long)
except NameError:
    _string_types = (str,)
    _integer_types = (int,)

_EVENT_TYPES = (
    "Autodesk.Revit.UI.Events.DialogBoxShowingEventArgs",
    "Autodesk.Revit.UI.Events.MessageBoxShowingEventArgs",
    "Autodesk.Revit.UI.Events.TaskDialogShowingEventArgs",
)
_STATE_KEY = "revit_mcp.dialog_policy.subscription"


def _text(value, label):
    if not isinstance(value, _string_types) or not value.strip():
        raise ValueError("{} must be a nonempty string".format(label))
    return value


def _error_details(error):
    try:
        message = str(error)[:2000]
    except Exception:
        message = "Exception message unavailable"
    return {"type": type(error).__name__, "message": message}


class DialogPolicy(object):
    """Validate and snapshot an exact-ID catalog and explicit action selections.

    catalog[dialog_id] = {event_type, revit_builds, actions}; actions[name] =
    {result_code, description, evidence}. Evidence must identify the exact
    dialog/button semantics for each listed build, not just generic API docs.
    responses[dialog_id] = action_name. Messages never participate in matching.
    """

    def __init__(self, catalog=None, responses=None, enabled=False):
        if type(enabled) is not bool:
            raise ValueError("enabled must be an explicit boolean")
        catalog = {} if catalog is None else catalog
        responses = {} if responses is None else responses
        if not isinstance(catalog, dict) or not isinstance(responses, dict):
            raise ValueError("catalog and responses must be dictionaries")
        supported = {}
        for dialog_id, spec in catalog.items():
            _text(dialog_id, "dialog_id")
            if not isinstance(spec, dict) or set(spec) != set(
                    ("event_type", "revit_builds", "actions")):
                raise ValueError("dialog spec requires event_type, revit_builds, actions")
            if spec["event_type"] not in _EVENT_TYPES:
                raise ValueError("unsupported dialog event type")
            builds = spec["revit_builds"]
            if not isinstance(builds, (list, tuple)) or not builds:
                raise ValueError("revit_builds must list exact verified build strings")
            for build in builds:
                _text(build, "Revit build")
            actions = spec["actions"]
            if not isinstance(actions, dict) or not actions:
                raise ValueError("actions must document at least one permitted action")
            for name, action in actions.items():
                _text(name, "action name")
                if not isinstance(action, dict) or set(action) != set(
                        ("result_code", "description", "evidence")):
                    raise ValueError("action requires result_code, description, evidence")
                code = action["result_code"]
                if (isinstance(code, bool) or not isinstance(code, _integer_types)
                        or code == 0 or not -2147483648 <= code <= 2147483647):
                    raise ValueError("result_code must be a nonzero Int32")
                _text(action["description"], "action description")
                _text(action["evidence"], "action evidence")
            supported[dialog_id] = copy.deepcopy(spec)
        for dialog_id, action_name in responses.items():
            _text(dialog_id, "response dialog_id")
            _text(action_name, "response action name")
            if dialog_id not in supported:
                raise ValueError("response refers to an unsupported exact dialog ID")
            if action_name not in supported[dialog_id]["actions"]:
                raise ValueError("response is not a documented permitted action")
        self._catalog = supported
        self._responses = dict(responses)
        self._enabled = enabled

    def decide(self, dialog_id, event_type, revit_build):
        """Return (reason, action snapshot); None action means leave untouched."""
        if not self._enabled:
            return "policy_disabled", None
        spec = self._catalog.get(dialog_id)
        if spec is None:
            return "unsupported_dialog", None
        if event_type != spec["event_type"]:
            return "event_type_mismatch", None
        if revit_build not in spec["revit_builds"]:
            return "unverified_revit_build", None
        name = self._responses.get(dialog_id)
        if name is None:
            return "action_not_selected", None
        action = copy.deepcopy(spec["actions"][name])
        action["name"] = name
        return "permitted_action", action


class DialogSubscription(object):
    """One retained delegate with bounded, copied receipts and explicit detach.

    attach/detach operate on that exact delegate. The host calls lifecycle methods
    in a valid API context, serialized with execution. Receipt reads are safe for
    background diagnostics and contain no Revit wrappers. A failed detach leaves
    a disabled subscription retained, so replacement cannot add a second one.
    """

    def __init__(self, policy, revit_build, attach, detach, delegate_factory,
                 receipt_limit=128, clock=time.time):
        if not isinstance(policy, DialogPolicy):
            raise ValueError("policy must be a DialogPolicy")
        _text(revit_build, "loaded Revit build")
        if (isinstance(receipt_limit, bool) or not isinstance(receipt_limit, int)
                or not 1 <= receipt_limit <= 4096):
            raise ValueError("receipt_limit must be between 1 and 4096")
        self._policy = policy
        self._build = revit_build
        self._attach = attach
        self._detach = detach
        self._handler = delegate_factory(self._on_dialog)
        self._limit = receipt_limit
        self._clock = clock
        self._lock = threading.RLock()
        self._receipts = []
        self._sequence = 0
        self._dropped = 0
        self._attached = False
        self._active = False

    def start(self):
        with self._lock:
            if not self._attached:
                self._attach(self._handler)
                self._attached = True
                self._active = True

    def close(self):
        with self._lock:
            self._active = False
            if self._attached:
                self._detach(self._handler)
                self._attached = False

    def snapshot(self):
        with self._lock:
            return {"attached": self._attached, "active": self._active,
                    "dropped_receipts": self._dropped,
                    "receipts": copy.deepcopy(self._receipts)}

    def _on_dialog(self, sender, args):
        # The callback only reads event primitives and optionally overrides once.
        # Never raise through Revit, mutate a document, or retry another action.
        with self._lock:
            receipt = {"dialog_id": None, "event_type": None,
                       "revit_build": self._build, "action": None,
                       "override_attempted": False, "override_accepted": None,
                       "reason": "subscription_inactive", "error": None}
            try:
                receipt["dialog_id"] = getattr(args, "DialogId", None)
                receipt["event_type"] = args.GetType().FullName
                if (not isinstance(receipt["dialog_id"], _string_types)
                        or not isinstance(receipt["event_type"], _string_types)):
                    raise ValueError("dialog identity/type must be strings")
                if self._active:
                    reason, action = self._policy.decide(
                        receipt["dialog_id"], receipt["event_type"], self._build)
                    receipt["reason"] = reason
                    receipt["action"] = action
                    if action is not None:
                        receipt["override_attempted"] = True
                        accepted = args.OverrideResult(action["result_code"])
                        receipt["override_accepted"] = bool(accepted)
                        receipt["reason"] = ("override_accepted" if accepted
                                             else "override_rejected")
            except Exception as error:
                receipt["reason"] = ("override_error" if receipt["override_attempted"]
                                     else "observation_error")
                receipt["error"] = _error_details(error)
            # Logging must also never throw back into Revit. Keep no event wrappers.
            try:
                if not isinstance(receipt["dialog_id"], _string_types):
                    receipt["dialog_id"] = None
                if not isinstance(receipt["event_type"], _string_types):
                    receipt["event_type"] = None
                self._sequence += 1
                receipt["sequence"] = self._sequence
                receipt["observed_at_unix"] = self._clock()
                if len(self._receipts) == self._limit:
                    self._receipts.pop(0)
                    self._dropped += 1
                self._receipts.append(receipt)
            except Exception:
                self._dropped += 1


def replace_subscription(retained_state, policy, revit_build, attach, detach,
                         delegate_factory, receipt_limit=128):
    """Explicit initialization hook, using a host-owned process-retained mapping.

    The mapping must survive module/engine initialization; a fresh {} each time
    cannot prevent duplicate handlers. Replacement detaches before attaching and
    refuses to proceed if detach fails. No module-global singleton is substituted.
    """
    if retained_state is None:
        raise ValueError("a host-retained subscription mapping is required")
    replacement = DialogSubscription(policy, revit_build, attach, detach,
                                     delegate_factory, receipt_limit)
    previous = retained_state.get(_STATE_KEY)
    if previous is not None:
        previous.close()
    retained_state[_STATE_KEY] = replacement
    replacement.start()
    return replacement


def remove_subscription(retained_state):
    """Disable and detach this feature's delegate; retain it if detach fails."""
    previous = retained_state.get(_STATE_KEY)
    if previous is not None:
        previous.close()
        del retained_state[_STATE_KEY]


def initialize_for_uiapplication(uiapp, retained_state, policy=None,
                                 receipt_limit=128):
    """Optional native adapter. Call only in an authorized host/API context.

    This is deliberately not called by startup.py. Native delegate conversion is
    lazy and the actual .NET delegate is retained for exact unsubscription.
    """
    from System import EventHandler
    from Autodesk.Revit.UI.Events import DialogBoxShowingEventArgs

    def attach(handler):
        uiapp.DialogBoxShowing += handler

    def detach(handler):
        uiapp.DialogBoxShowing -= handler

    return replace_subscription(
        retained_state, DialogPolicy() if policy is None else policy,
        uiapp.Application.VersionBuild, attach, detach,
        EventHandler[DialogBoxShowingEventArgs], receipt_limit)
