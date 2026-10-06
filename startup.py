# -*- coding: UTF-8 -*-
"""
Revit MCP Extension Startup
Registers all MCP routes and initializes the API
"""

from pyrevit import routes
import logging

logger = logging.getLogger(__name__)

# Initialize the main API
api = routes.API("revit_mcp")


def register_routes(legacy_api_enabled=True):
    """Register all MCP route modules"""
    try:
        from revit_mcp.target_routing import startup_owner_guard
        with startup_owner_guard():
            # Initialize identity after the status API-context correction. The metadata
            # route reads cached primitives; native callbacks own document collection.
            from revit_mcp.target_runtime import initialize_identity

            from revit_mcp.target_routing import DisabledAPI, TargetedAPI, get_process_safety
            metadata_api = api if legacy_api_enabled else DisabledAPI(api, metadata_only=True)
            initialize_identity(metadata_api)
            targeted_api = (TargetedAPI(api, safety=get_process_safety()) if legacy_api_enabled
                            else DisabledAPI(api))

            # Import and register status routes
            from revit_mcp.status import register_status_routes

            register_status_routes(targeted_api)

            from revit_mcp.model_info import register_model_info_routes

            register_model_info_routes(targeted_api)

            from revit_mcp.views import register_views_routes

            register_views_routes(targeted_api)

            from revit_mcp.placement import register_placement_routes

            register_placement_routes(targeted_api)

            from revit_mcp.colors import register_color_routes

            register_color_routes(targeted_api)

            from revit_mcp.code_execution import register_code_execution_routes

            register_code_execution_routes(targeted_api)

            from revit_mcp.document import register_document_routes

            register_document_routes(targeted_api)

            logger.info("All MCP routes registered successfully")
            if not legacy_api_enabled:
                from revit_mcp.routing_policy import ROUTES
                legacy = {path for path in ROUTES if not path.startswith("/operations/")}
                legacy.remove("/get_view/")
                legacy.add("/get_view/<view_name>")
                receipt = targeted_api.assert_excluded(legacy)
                metadata_api.assert_excluded(["/metadata/refresh/"])
                receipt["excluded_routes"].append("/metadata/refresh/")
                return receipt
            return {"legacy_api_excluded": False}

    except Exception as e:
        logger.error("Failed to register MCP routes: %s", str(e))
        raise


# Register all routes when the extension loads
register_routes()
