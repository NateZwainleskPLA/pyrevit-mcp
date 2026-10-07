"""Host-independent behavioral tests; these do not validate native Revit."""
import sys
from io import StringIO
from types import SimpleNamespace

import pytest

from revit_mcp.execution_output import execute_script


@pytest.fixture
def execution_route(monkeypatch):
    import importlib
    monkeypatch.setitem(sys.modules, "pyrevit", SimpleNamespace(
        DB=SimpleNamespace(), revit=SimpleNamespace(), routes=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace())
    sys.modules.pop("revit_mcp.code_execution", None)
    return importlib.import_module("revit_mcp.code_execution")


def test_unicode_stdout_stderr_and_restoration():
    streams = sys.stdout, sys.stderr
    result = execute_script("import sys\nprint(u'café 雪')\nsys.stderr.write(u'erreur é')", {})
    assert result["output"] == "café 雪\n"
    assert result["stderr"] == "erreur é"
    assert (sys.stdout, sys.stderr) == streams


@pytest.mark.parametrize("failure", ["assert False", "raise SystemExit(3)", "raise KeyboardInterrupt()"])
def test_partial_output_and_script_line(failure):
    streams = sys.stdout, sys.stderr
    result = execute_script("print('before')\n" + failure, {}, "C:\\local\\trial.py")
    assert result["status"] == "error"
    assert result["partial_output"] == "before\n"
    assert result["script_location"] == {"filename": "trial.py", "line": 2, "column": None}
    assert result["error_type"] in result["traceback"]
    assert (sys.stdout, sys.stderr) == streams


def test_syntax_error_location():
    result = execute_script("x =", {}, "bad.py")
    assert result["error_type"] == "SyntaxError"
    assert result["script_location"]["line"] == 1


@pytest.mark.parametrize("payload", ["{bad", None, [], {"code": ""}, {"code": 4}, {"code": " \n"}])
def test_malformed_or_empty_payload_restores_streams(execution_route, payload):
    streams = sys.stdout, sys.stderr
    result, status = execution_route.execute_payload(payload, None, None)
    assert status == 400
    assert result["status"] == "error"
    assert (sys.stdout, sys.stderr) == streams


def test_json_unicode_payload(execution_route):
    result, status = execution_route.execute_payload('{"code": "print(u\'雪\')"}', None, None)
    assert status == 200
    assert result["output"] == "雪\n"


def test_second_buffer_initialization_failure_closes_first():
    buffers = []
    def factory():
        if buffers:
            raise RuntimeError("init failed")
        buffers.append(StringIO())
        return buffers[0]
    streams = sys.stdout, sys.stderr
    result = execute_script("raise AssertionError('must not run')", {}, buffer_factory=factory)
    assert result["error"] == "RuntimeError: init failed"
    assert buffers[0].closed
    assert (sys.stdout, sys.stderr) == streams


@pytest.mark.parametrize("method", ["write", "getvalue", "close"])
def test_output_failures_preserve_output_and_restore(method):
    class BrokenBuffer(StringIO):
        pass
    def fail(self, *args):
        if method == "close":
            StringIO.close(self)
        raise IOError("capture failed")
    setattr(BrokenBuffer, method, fail)
    streams = sys.stdout, sys.stderr
    namespace = {"effects": []}
    result = execute_script("import sys\nsys.stdout.write('partial')\neffects.append('continued')", namespace, buffer_factory=BrokenBuffer)
    assert result["status"] == "error"
    assert result["partial_output"] == "partial"
    assert namespace["effects"] == ["continued"]
    assert result["cleanup_errors"][0]["stage"] == "output_" + ("read" if method == "getvalue" else method)
    assert (sys.stdout, sys.stderr) == streams


def test_writelines_closed_and_bounded_unicode_capture():
    namespace = {"streams": []}
    code = "import sys\nassert not sys.stdout.closed\nsys.stdout.writelines([u'café', u'雪'])\nstreams.append(sys.stdout)"
    result = execute_script(code, namespace, output_limit_chars=4)
    assert result["status"] == "success"
    assert result["output"] == "café" and result["output_truncated"]
    assert namespace["streams"][0].closed


def test_default_capture_has_no_redundant_backing_buffer():
    namespace = {"streams": []}
    result = execute_script("import sys\nstreams.append(sys.stdout)\nprint('ok')", namespace)
    assert result["status"] == "success" and result["output"] == "ok\n"
    assert namespace["streams"][0].buffer is None


def test_optional_sink_write_failure_does_not_abort_raw_edits_or_primary_error():
    class BrokenWrite(StringIO):
        def write(self, value):
            raise IOError("sink failed")
    namespace = {"effects": []}
    code = "effects.append(1)\nprint('first')\neffects.append(2)\nprint('second')\nassert False"
    result = execute_script(code, namespace, buffer_factory=BrokenWrite)
    assert namespace["effects"] == [1, 2]
    assert result["error_type"] == "AssertionError"
    assert result["partial_output"] == "first\nsecond\n"
    assert result["cleanup_errors"] == [{"stage": "output_write", "error": "sink failed"}]


def test_stream_close_and_file_descriptor_contract():
    from revit_mcp.execution_output import CaptureBudget, CaptureStream
    stream = CaptureStream(None, CaptureBudget(5))
    assert stream.closed is False
    with pytest.raises(IOError):
        stream.fileno()
    stream.writelines(["a", "b"])
    stream.close()
    stream.close()
    assert stream.closed is True
    with pytest.raises(ValueError, match="closed"):
        stream.write("c")
    with pytest.raises(ValueError, match="closed"):
        stream.flush()


def test_injected_write_and_flush_failures_are_latched_without_interrupting_work():
    calls = {"write": 0, "flush": 0}
    class BrokenSink(StringIO):
        def write(self, value):
            calls["write"] += 1
            raise IOError("write failed")
        def flush(self):
            calls["flush"] += 1
            raise IOError("flush failed")
    code = "import sys\nfor idx in range(100):\n    print('ok')\n    sys.stdout.flush()"
    result = execute_script(code, {}, buffer_factory=BrokenSink)
    assert result["error_type"] == "OutputCleanupError"
    assert calls == {"write": 1, "flush": 1}
    assert result["partial_output"] == "ok\n" * 100
    assert [error["stage"] for error in result["cleanup_errors"]] == ["output_write", "output_flush"]


def test_diagnostic_sink_error_preserves_completed_managed_effects():
    from revit_mcp.execution_context import ExecutionContext
    from tests.unit.test_execution_context import Document, FakeDB
    class BrokenSink(StringIO):
        def write(self, value):
            raise IOError("write failed")
    doc = Document()
    execution = ExecutionContext(FakeDB(), doc, "managed")
    result = execute_script("doc.value = 1\nprint('step')\ndoc.value = 2", {"doc": doc},
                            buffer_factory=BrokenSink, runner=execution.run)
    assert doc.value == 2 and execution.summary()["effects"] == "committed"
    assert not execution.summary()["unsafe"]
    assert result["error_type"] == "OutputCleanupError"


def test_cleanup_does_not_mask_primary_exception():
    class BadClose(StringIO):
        def close(self):
            StringIO.close(self)
            raise RuntimeError("close failed")
    result = execute_script("print('before')\nassert False", {}, buffer_factory=BadClose)
    assert result["error_type"] == "AssertionError"
    assert len(result["cleanup_errors"]) == 2
    assert result["partial_output"] == "before\n"
