# -*- coding: utf-8 -*-
"""Shared synchronous route requirements; no identity allocation or Revit access."""


# (requires an existing document, requires its active UI document,
#  requires explicit permission to change the UI)
ROUTES = {
    "/status/": (False, False, False),
    "/open_document/": (False, False, True),
    "/model_info/": (True, False, False),
    "/execute_code/": (True, False, False),
    "/list_views/": (True, False, False),
    "/get_view/": (True, False, False),
    "/current_view_info/": (True, True, False),
    "/current_view_elements/": (True, True, False),
    "/place_family/": (True, False, False),
    "/list_families/": (True, False, False),
    "/list_family_categories/": (True, False, False),
    "/list_levels/": (True, False, False),
    "/color_splash/": (True, True, False),
    "/clear_colors/": (True, True, False),
    "/list_category_parameters/": (True, False, False),
    "/close_document/": (True, True, True),
    "/save_document/": (True, False, False),
    "/sync_with_central/": (True, False, False),
    "/operations/submit/": (True, False, False),
    "/operations/inspect/": (True, False, False),
    "/operations/cancel/": (True, False, False),
}


class RoutingPolicyError(ValueError):
    def __init__(self, code, message):
        ValueError.__init__(self, message)
        self.code = code


def route_policy(endpoint):
    key = "/get_view/" if endpoint.startswith("/get_view/") else endpoint
    if key not in ROUTES:
        raise RoutingPolicyError("unknown_route", "No targeting policy for this route")
    return ROUTES[key]


def check_ui_policy(endpoint, is_active, allow_ui_change=False):
    """Never activate implicitly, even when the caller permits UI changes.

    Activation itself needs a separately implemented, targeted operation. The
    synchronous routes can currently perform UI work only on an active document.
    """
    _, requires_active, changes_ui = route_policy(endpoint)
    if type(allow_ui_change) is not bool:
        raise RoutingPolicyError("invalid_ui_permission", "allow_ui_change must be a boolean")
    if changes_ui and not allow_ui_change:
        raise RoutingPolicyError("ui_permission_required", "This operation requires allow_ui_change=true")
    if requires_active and not is_active:
        raise RoutingPolicyError("inactive_document", "This UI operation requires the specified document to be active")
