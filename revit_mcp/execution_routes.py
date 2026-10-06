# -*- coding: utf-8 -*-
"""Background admission/inspection. No Revit objects or API-context parameters."""
import json

from .operation_store import OperationError


def register_execution_routes(api, runtime, make_response=None):
    if make_response is None:
        from pyrevit import routes
        make_response = routes.make_response

    def respond(action, request):
        try:
            data = request.data
            if not isinstance(data, dict):
                data = json.loads(data)
            if not isinstance(data, dict):
                raise ValueError("Object payload required")
            if action == "submit":
                receipt, created = runtime.submit(data)
                return make_response(data=receipt, status=202 if created else 200)
            runtime.validate_cached(data)
            receipt = runtime.store.inspect(data["operation_id"])
            # Inspection cannot read an operation using another target/document.
            for key in ("target", "document", "identity"):
                if receipt.get(key) != data.get(key):
                    raise OperationError("operation_target_mismatch", "Operation target does not match")
            return make_response(data=receipt, status=200)
        except OperationError as error:
            return make_response(data={"error": str(error), "error_code": error.code}, status=error.status)
        except (ValueError, TypeError, KeyError) as error:
            return make_response(data={"error": str(error), "error_code": "invalid_request"}, status=400)

    @api.route("/operations/submit/", methods=["POST"])
    def submit(request):
        return respond("submit", request)

    @api.route("/operations/inspect/", methods=["POST"])
    def inspect(request):
        return respond("inspect", request)

    return respond
