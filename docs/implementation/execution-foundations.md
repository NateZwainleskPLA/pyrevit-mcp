Execution foundations
====================

`execute_payload(data, doc, uidoc)` in `revit_mcp/code_execution.py` returns
`(result, http_status)` for synchronous API-context execution. Routing owns
required target/document handles and full receiver identity validation. This
foundation does not claim the legacy route already meets the targeting contract.

`execute_script(code, namespace, script_name)` in `execution_output.py` restores
stdout and stderr in an outer finally, including SystemExit/KeyboardInterrupt.
Output remains separate from stderr. Failures preserve `partial_output`,
`error_type`, `traceback`, and `script_location` (filename/line/column). A supplied
`script_name` contributes only its basename; it never reads a host file. Empty
output remains an empty string. Capture read/close failures appear separately
in `cleanup_errors` and do not mask the script exception. Execution must be
serialized because Python streams belong to the engine.

Upstream #12 at `43cd36e6e3dceb925bc7868e4277b07b5742f1a3` was inspected.
Its finally references uninitialized output variables for parsing/no-code paths;
this implementation initializes resources before entering capture and closes
only created buffers. Command execution/log scraping is outside this change.

Host-independent tests cover diagnostics and stream/resource errors. Native
IronPython stdout/stderr restoration still needs an explicitly supplied
disposable Revit fixture. No live model or installed extension was changed.
