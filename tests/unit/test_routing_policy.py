import pytest

from revit_mcp.routing_policy import ROUTES, RoutingPolicyError, check_ui_policy, route_policy


def test_all_existing_document_routes_have_document_requirement():
    assert {path for path, policy in ROUTES.items() if not policy[0]} == {
        "/status/", "/open_document/", "/execute_application_code/", "/operations/inspect/", "/operations/cancel/"
    }


def test_export_path_uses_view_policy_and_unknown_route_fails_closed():
    assert route_policy("/get_view/Level%201") == (True, False, False)
    with pytest.raises(RoutingPolicyError, match="No targeting policy"):
        route_policy("/new_mutation/")


@pytest.mark.parametrize("endpoint", ["/current_view_info/", "/current_view_elements/", "/color_splash/", "/clear_colors/"])
@pytest.mark.parametrize("allow", [False, True])
def test_inactive_ui_document_never_activates(endpoint, allow):
    with pytest.raises(RoutingPolicyError):
        check_ui_policy(endpoint, False, allow)


@pytest.mark.parametrize("endpoint", ["/open_document/", "/close_document/"])
def test_explicit_permission_needed_for_ui_changes(endpoint):
    with pytest.raises(RoutingPolicyError) as exc:
        check_ui_policy(endpoint, True)
    assert exc.value.code == "ui_permission_required"
    check_ui_policy(endpoint, True, True)


def test_database_work_can_use_an_inactive_document():
    for endpoint in ("/save_document/", "/list_levels/", "/execute_code/"):
        check_ui_policy(endpoint, False)


def test_truthy_string_is_not_ui_permission():
    with pytest.raises(RoutingPolicyError) as exc:
        check_ui_policy("/open_document/", True, "false")
    assert exc.value.code == "invalid_ui_permission"
