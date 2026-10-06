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
    result = execute_script("import sys\nsys.stdout.write('partial')", {}, buffer_factory=BrokenBuffer)
    assert result["status"] == "error"
    assert result["partial_output"] == "partial"
    assert (sys.stdout, sys.stderr) == streams


def test_cleanup_does_not_mask_primary_exception():
    class BadClose(StringIO):
        def close(self):
            StringIO.close(self)
            raise RuntimeError("close failed")
    result = execute_script("print('before')\nassert False", {}, buffer_factory=BadClose)
    assert result["error_type"] == "AssertionError"
    assert len(result["cleanup_errors"]) == 2
    assert result["partial_output"] == "before\n"
