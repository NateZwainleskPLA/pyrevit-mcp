# -*- coding: utf-8 -*-
"""Background admission/inspection. No Revit objects or API-context parameters."""
import json

from .operation_store import OperationError
from .execution_output import safe_text


def register_execution_routes(api, runtime, make_response=None):
    if make_response is None:
        from pyrevit import routes
        make_response = routes.make_response

    def respond(action, request):
        def response(body, status):
            adapter = getattr(runtime, "adapter", None)
            if adapter is not None:
                snapshot = adapter.registry.snapshot()
                body.setdefault("actual_target", dict((key, snapshot[key]) for key in ("instance_id", "runtime_id")))
            return make_response(data=body, status=status)
        try:
            data = request.data
            if not isinstance(data, dict):
                data = json.loads(data)
            if not isinstance(data, dict):
                raise ValueError("Object payload required")
            if action == "submit":
                receipt, created = runtime.submit(data)
                return response(receipt, 202 if created else 200)
            adapter = getattr(runtime, "adapter", None)
            if adapter is not None:
                adapter.validate_operation_cached(data)
            else:
                runtime.validate_cached(data)
            receipt = runtime.store.inspect(data["operation_id"])
            # Inspection cannot read an operation using another target/document.
            for key in ("target", "identity", "instance_id", "runtime_id"):
                if receipt.get(key) != data.get(key):
                    raise OperationError("operation_target_mismatch", "Operation target does not match")
            for key in ("document", "document_id"):
                if key in data and receipt.get(key) != data[key]:
                    raise OperationError("operation_target_mismatch", "Supplied historical document does not match")
            if action == "cancel":
                receipt = runtime.store.cancel(data["operation_id"])
            return response(receipt, 200)
        except OperationError as error:
            body = {"error": safe_text(error), "error_code": error.code}
            if action == "submit":
                # Admission failed before a new execution was made visible.
                body["effects"] = "none"
            return response(body, error.status)
        except (ValueError, TypeError, KeyError) as error:
            return response({"error": safe_text(error), "error_code": "invalid_request"}, 400)

    @api.route("/operations/submit/", methods=["POST"])
    def submit(request):
        return respond("submit", request)

    @api.route("/operations/inspect/", methods=["POST"])
    def inspect(request):
        return respond("inspect", request)

    @api.route("/operations/cancel/", methods=["POST"])
    def cancel(request):
        return respond("cancel", request)

    return respond
