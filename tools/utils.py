# -*- coding: utf-8 -*-
"""Utility functions for MCP tools"""

import json
from http import HTTPStatus

from .revit_transport import RevitResponse, RevitResponseText, RevitTransportResult


# Statuses that are valid, expected, recoverable outcomes -- NOT errors.
#
# A tool returns one of these when it ran correctly but the result is
# something other than a plain success: an empty query result, a dry-run or
# confirm-gate preview, an unmet precondition the caller can fix, or a lookup
# that did not resolve. They must not be rendered with the
# "=== ERROR DETAILS ===" / "=== TRACEBACK ===" framing -- that misleads
# callers into treating a normal branch as a crash, and the generic
# "Unknown error occurred" fallback discards the structured data these
# responses carry (applied_filters, existing_rooms_on_level, ...).
#
# Only TOP-LEVEL statuses belong here; per-item statuses nested inside a
# results/preview list (e.g. modify_element's per-parameter "read_only") never
# reach format_response().
RECOVERABLE_STATUSES = frozenset({
    # Preview / dry-run outcomes -- confirm-gate previews and --dry_run runs
    "preview", "dry_run", "no_op",
    # Empty-result outcomes -- the tool ran fine, nothing matched the query
    "no_walls", "no_axis_aligned_walls", "no_references_found",
    "no_elements_found", "no_rooms_found", "no_rooms_in_view",
    # Unmet preconditions -- the caller can adjust inputs and retry
    "not_in_enclosed_area", "area_already_occupied", "name_collision",
    "view_not_supported", "no_room_tag_family",
    # Lookup misses -- a supplied id or name did not resolve
    "view_not_found", "level_not_found", "phase_not_found",
    # Revit is running but no document is open
    "active_no_document",
    # Generic non-error signals
    "ok", "warning",
    # Admission/pending outcomes are receipts, not execution failures.
    "accepted", "queued", "running", "waiting_for_user", "canceled",
    "unknown_after_restart",
})


def _format_recoverable(response):
    """Render a recoverable, non-error status without alarming error framing.

    See RECOVERABLE_STATUSES. The human-readable note may live under either
    "message" or "error"; any remaining fields are emitted as a JSON block so
    callers can still consume the structured data the response carries.

    Args:
        response: A dict response whose "status" is in RECOVERABLE_STATUSES.

    Returns:
        str: A neutrally formatted, multi-line summary.
    """
    status = response.get("status", "unknown")
    parts = ["=== {} ===".format(str(status).replace("_", " ").upper())]

    note = response.get("message") or response.get("error") or ""
    if note:
        parts.append(note)

    details = response.get("details", "")
    if details:
        parts.append("Details: {}".format(details))

    extra = {k: v for k, v in response.items()
             if k not in ("status", "message", "error", "details")}
    if extra:
        parts.append("")
        parts.append(json.dumps(extra, indent=2, default=str, sort_keys=True))

    return "\n".join(parts)


def _format_success_value(value, response):
    """Keep concise output while making receiver identity/effects observable."""
    metadata_fields = {
        "actual_target", "target", "document", "instance_id", "runtime_id", "document_id",
        "effects", "operation_id", "state", "partial_output", "traceback",
    }
    metadata = {key: val for key, val in response.items() if key in metadata_fields}
    text = str(value)
    if metadata:
        text += "\n\n=== RESPONSE METADATA ===\n" + json.dumps(
            metadata, indent=2, default=str, ensure_ascii=False, sort_keys=True)
    return text


def compatibility_response(result: RevitTransportResult):
    """Keep dictionary/text consumers compatible without discarding metadata.

    New internal consumers use RevitTransportResult directly. This view exposes
    that result through .transport_result, without adding keys to Revit JSON.
    """
    if result.json_received and isinstance(result.body, dict):
        return RevitResponse(result)
    return RevitResponseText(_format_transport(result), result)


def _format_transport(result):
    if result.failure_kind:
        if result.failure_kind == "timeout":
            message = "Error: Request timed out."
        elif result.failure_kind == "connection_error":
            message = "Error: Connection to Revit failed: {}".format(result.error)
        elif result.failure_kind == "invalid_json":
            message = "Error: Revit endpoint returned a malformed or non-JSON response."
        else:
            message = "Error: Transport failure: {}".format(result.error)
        if result.mutation_outcome_unknown:
            message += (" The mutation outcome is unknown; the operation may still be running in Revit."
                        " Inspect the original operation before submitting again.")
        if result.status_code is not None:
            message += "\nHTTP {}\n{}".format(result.status_code, result.response_text)
        return message

    if isinstance(result.body, dict):
        text = format_response(result.body)
    else:
        text = json.dumps(result.body, indent=2, ensure_ascii=False)
    if result.status_code is not None and result.status_code != 200:
        exception = result.body.get("exception") if isinstance(result.body, dict) else None
        if result.status_code == 408 and isinstance(exception, dict) and "message" in exception:
            return "Error: pyRevit route handler exception (HTTP 408)\n{}".format(text)
        try:
            phrase = HTTPStatus(result.status_code).phrase
        except ValueError:
            phrase = ""
        prefix = "" if result.http_success else "Error: "
        return "{}HTTP {} {}\n{}".format(prefix, result.status_code, phrase, text).strip()
    return text


def format_response(response):
    """Helper function to format API responses consistently for MCP tools.

    Args:
        response: A transport result, compatible view, plain dict, or string

    Returns:
        str: Formatted string response suitable for MCP tool return values
    """
    if isinstance(response, RevitTransportResult):
        return _format_transport(response)
    if isinstance(response, (RevitResponse, RevitResponseText)):
        return _format_transport(response.transport_result)
    if isinstance(response, dict):
        exception = response.get("exception")
        native_exception = isinstance(exception, dict) and "message" in exception
        # Check for different success patterns
        status = str(response.get("status") or "").lower()
        health = str(response.get("health") or "").lower()

        # Success conditions: status="success" OR status="active" with health="healthy"
        is_success = (status in {"success", "succeeded"} or
                     (status == "active" and health == "healthy") or
                     (status == "active" and "revit_available" in response and response["revit_available"]))

        if is_success and not native_exception:
            # For successful responses, return the most relevant data
            if "output" in response:  # Code execution responses
                return _format_success_value(response["output"], response)
            elif "message" in response:
                return _format_success_value(response["message"], response)
            elif "result" in response:
                return _format_success_value(response["result"], response)
            elif "data" in response:
                return _format_success_value(response["data"], response)
            elif status == "active":  # Status check responses
                # Format status response nicely
                status_parts = ["=== REVIT STATUS ==="]
                status_parts.append("Status: {}".format(response.get("status", "Unknown")))
                status_parts.append("Health: {}".format(response.get("health", "Unknown")))

                if "api_name" in response:
                    status_parts.append("API: {}".format(response["api_name"]))
                if "document_title" in response:
                    status_parts.append("Document: {}".format(response["document_title"]))
                if "revit_available" in response:
                    status_parts.append("Revit Available: {}".format(response["revit_available"]))

                # Add any other fields that might be present
                known_fields = {"status", "health", "api_name", "document_title", "revit_available"}
                other_fields = set(response.keys()) - known_fields
                if other_fields:
                    status_parts.append("")
                    for field in sorted(other_fields):
                        status_parts.append("{}: {}".format(field.replace("_", " ").title(), response[field]))

                return "\n".join(status_parts)
            else:
                return json.dumps(response, indent=2)
        elif status in RECOVERABLE_STATUSES and not native_exception:
            # Documented, expected, non-error outcome -- render it neutrally
            # instead of dressing it up as a crash. See RECOVERABLE_STATUSES.
            return _format_recoverable(response)
        elif (not status and not response.get("error") and not response.get("traceback")
              and "exception" not in response):
            # Metadata and operation receipts need not use the legacy status
            # field. Preserve them as JSON rather than invent an error.
            return json.dumps(response, indent=2, default=str, ensure_ascii=False)
        else:
            # Error case - provide verbose debugging information
            error_msg = ((exception.get("message") if native_exception else None) or
                         response.get("error") or
                         response.get("message") or
                         "Unknown error occurred")
            traceback_info = response.get("traceback", "")
            details = response.get("details", "")
            status = response.get("status", "unknown")

            # Build comprehensive error message
            error_parts = ["=== ERROR DETAILS ==="]
            error_parts.append("Status: {}".format(status))
            if native_exception and "source" in exception:
                error_parts.append("Source: {}".format(exception["source"]))
            error_parts.append("Error: {}".format(error_msg))

            if details:
                error_parts.append("Details: {}".format(details))

            if traceback_info:  # Code execution error with traceback
                error_parts.append("\n=== TRACEBACK ===")
                error_parts.append(traceback_info)

            # Add any additional fields that might be helpful for debugging
            debug_fields = ["code_attempted", "endpoint", "request_data", "response_code"]
            for field in debug_fields:
                if field in response:
                    error_parts.append("{}: {}".format(field.replace("_", " ").title(), response[field]))

            # Include full response for debugging if it has unexpected fields
            response_keys = set(response.keys()) - {"error", "message", "traceback", "details", "status", "code_attempted", "endpoint", "request_data", "response_code"}
            if response_keys:
                error_parts.append("\n=== ADDITIONAL RESPONSE DATA ===")
                for key in sorted(response_keys):
                    error_parts.append("{}: {}".format(key, response[key]))

            return "\n".join(error_parts)
    else:
        # If response is already a string (error case from _revit_call)
        return str(response)
