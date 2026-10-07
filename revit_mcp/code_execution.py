# -*- coding: UTF-8 -*-
"""Synchronous IronPython execution in a valid Revit API context."""
import json
import logging

from pyrevit import routes, revit, DB
from .execution_output import (execute_script, text_type, string_types,
                               validate_output_limit, DEFAULT_OUTPUT_LIMIT_CHARS)
from .execution_helpers import RevitHelpers, build_hints
from .execution_context import ExecutionContext
from .execution_revit import ScopedRevit

logger = logging.getLogger(__name__)


def execute_payload(data, doc, uidoc, cancellation_check=None, revit_context=None,
                    output_limit_chars=DEFAULT_OUTPUT_LIMIT_CHARS, uiapp=None,
                    application_scope=False):
    """Return (structured result, HTTP status); caller owns identity validation."""
    try:
        validate_output_limit(output_limit_chars)
        if isinstance(data, string_types):
            data = json.loads(data)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        if application_scope:
            if uiapp is None or doc is not None or uidoc is not None:
                raise ValueError("Application execution requires supplied UIApplication and no document binding")
            if "document_id" in data or "document" in data:
                raise ValueError("Application execution does not accept a document selector")
        code = data.get("code")
        if not isinstance(code, string_types) or not code.strip():
            raise ValueError("No code provided (code must be a nonempty string)")
        script_name = data.get("script_name", "<revit-script>")
        if not isinstance(script_name, string_types) or not script_name:
            raise ValueError("script_name must be a nonempty string")
        description = data.get("description", "Code execution")
        if not isinstance(description, string_types):
            raise ValueError("description must be a string")
        transaction_mode = data.get("transaction_mode", "script")
        if transaction_mode not in ("script", "managed"):
            raise ValueError("transaction_mode must be 'script' or 'managed'")
        if transaction_mode == "managed" and doc is None:
            raise ValueError("managed mode requires a document")
        allow_ui_change = data.get("allow_ui_change", False)
        if not isinstance(allow_ui_change, bool):
            raise ValueError("allow_ui_change must be a boolean")
    except (ValueError, TypeError) as error:
        return {"status": "error", "error": text_type(error),
                "error_type": type(error).__name__, "effects": "none", "unsafe": False}, 400

    scoped_uidoc = uidoc if allow_ui_change else None
    application = uiapp.Application if uiapp is not None else None
    scoped_uiapp = uiapp if allow_ui_change else None
    scoped_revit = (ScopedRevit(revit, doc, scoped_uidoc, application, scoped_uiapp)
                    if revit_context is None else revit_context)
    namespace = {"doc": doc, "uidoc": scoped_uidoc, "DB": DB, "revit": scoped_revit,
                 "__builtins__": __builtins__}
    namespace.update(app=application, uiapp=scoped_uiapp)
    import System
    namespace.update(RevitHelpers(DB, System).namespace())
    document_provider = (lambda: tuple(application.Documents)) if application_scope else None
    execution = ExecutionContext(DB, doc, transaction_mode, cancellation_check,
                                 document_provider=document_provider)
    namespace["execution"] = execution
    result = execute_script(code, namespace, script_name, runner=execution.run,
                            output_limit_chars=output_limit_chars)
    # Capture/compile may fail before the runner starts. No scope exists then,
    # but close still verifies the selected document's postcondition.
    execution.close()
    summary = execution.summary()
    summary["cleanup_errors"] = result.get("cleanup_errors", []) + summary["cleanup_errors"]
    result.update(summary)
    if result["unsafe"] and result["status"] == "success":
        result.update({"status": "error", "error_type": "UnsafeDocumentError",
                       "error": "Document postcondition is unsafe", "partial_output": result["output"]})
    if result["status"] == "error":
        hints = build_hints(result.get("error_type", ""), result.get("error", ""))
        if hints:
            result["hints"] = hints
    result["description"] = description
    result["code_executed" if result["status"] == "success" else "code_attempted"] = code
    return result, 200 if result["status"] == "success" else 500


def execute_application_payload(data, uiapp, cancellation_check=None,
                                output_limit_chars=DEFAULT_OUTPUT_LIMIT_CHARS):
    """API-context-only application execution, with no implicit document binding."""
    return execute_payload(data, None, None, cancellation_check=cancellation_check,
                           output_limit_chars=output_limit_chars, uiapp=uiapp,
                           application_scope=True)


def register_code_execution_routes(api):
    """Register the synchronous route; targeting is integrated by routing."""
    @api.route("/execute_code/", methods=["POST"])
    def execute_code(uiapp, doc, uidoc, request):
        result, status = execute_payload(request.data, doc, uidoc, uiapp=uiapp)
        return routes.make_response(data=result, status=status)

    @api.route("/execute_application_code/", methods=["POST"])
    def execute_application_code(uiapp, request):
        result, status = execute_application_payload(request.data, uiapp)
        return routes.make_response(data=result, status=status)

    logger.info("Code execution routes registered successfully.")
