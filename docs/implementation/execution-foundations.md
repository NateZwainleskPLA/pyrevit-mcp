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

Reusable namespace helpers
--------------------------

`RevitHelpers(DB, System)` in `execution_helpers.py` binds `eid`, `id_of`,
`name_of`, `to_json`, and a local `json` adapter. `namespace()` supplies the
script bindings. Element-ID construction explicitly selects Int64 for numeric
values, while category/parameter enums retain their overload. ID extraction
supports Value and the older IntegerValue property. Name lookup handles the
hidden Element.Name descriptor and preserves Unicode without stripping text.

JSON handles supported .NET numeric/boolean types, ElementId and XYZ. Unknown
objects raise TypeError rather than silently turning into strings. A custom
`default` callback is honored. The process-wide json module is unchanged; a
script's `import json` shadows the adapter, so `to_json` is the explicit helper.

The helper approach came from upstream #63 at
`9a0ebe828d71b8bc259ee58f4419a0d0c58f311a`. Dialog suppression and unrelated
startup changes were not imported. Revit 2025 overload/descriptor behavior and
actual CLR JSON values still require the disposable native fixture.
