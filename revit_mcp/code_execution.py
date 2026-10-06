# -*- coding: UTF-8 -*-
"""Synchronous IronPython execution in a valid Revit API context."""
import json
import logging

from pyrevit import routes, revit, DB
from .execution_output import execute_script, text_type, string_types
from .execution_helpers import RevitHelpers, build_hints

logger = logging.getLogger(__name__)


def execute_payload(data, doc, uidoc):
    """Return (structured result, HTTP status); caller owns identity validation."""
    try:
        if isinstance(data, string_types):
            data = json.loads(data)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        code = data.get("code")
        if not isinstance(code, string_types) or not code.strip():
            raise ValueError("No code provided (code must be a nonempty string)")
        script_name = data.get("script_name", "<revit-script>")
        if not isinstance(script_name, string_types) or not script_name:
            raise ValueError("script_name must be a nonempty string")
        description = data.get("description", "Code execution")
        if not isinstance(description, string_types):
            raise ValueError("description must be a string")
    except (ValueError, TypeError) as error:
        return {"status": "error", "error": text_type(error),
                "error_type": type(error).__name__}, 400

    namespace = {"doc": doc, "uidoc": uidoc, "DB": DB, "revit": revit,
                 "__builtins__": __builtins__}
    import System
    namespace.update(RevitHelpers(DB, System).namespace())
    result = execute_script(code, namespace, script_name)
    if result["status"] == "error":
        hints = build_hints(result.get("error_type", ""), result.get("error", ""))
        if hints:
            result["hints"] = hints
    result["description"] = description
    result["code_executed" if result["status"] == "success" else "code_attempted"] = code
    return result, 200 if result["status"] == "success" else 500


def register_code_execution_routes(api):
    """Register the synchronous route; targeting is integrated by routing."""
    @api.route("/execute_code/", methods=["POST"])
    def execute_code(doc, uidoc, request):
        result, status = execute_payload(request.data, doc, uidoc)
        return routes.make_response(data=result, status=status)

    logger.info("Code execution routes registered successfully.")
