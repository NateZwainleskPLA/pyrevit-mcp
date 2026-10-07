import sys
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pytest

from revit_mcp.execution_output import CaptureBudget, CaptureStream, execute_script
from tests.unit.test_execution_output import execution_route
from tests.unit.test_execution_context import FakeDB, Document


def test_shared_stdout_stderr_limit_preserves_order_and_dropped_counts():
    code = "import sys\nsys.stdout.write(u'ab雪')\nsys.stderr.write(u'éXYZ')\nsys.stdout.write('last')"
    result = execute_script(code, {}, output_limit_chars=5)
    assert result["status"] == "success"
    assert result["output"] == "ab雪"
    assert result["stderr"] == "éX"
    assert result["output_truncated"] and result["stderr_truncated"]
    assert result["output_capture"] == {"limit_chars": 5, "retained_chars": 5,
                                        "stdout_dropped_chars": 4, "stderr_dropped_chars": 2}


@pytest.mark.parametrize("write_size", [1, 10000])
def test_retained_memory_does_not_grow_after_cap(write_size):
    class MeteredBuffer(StringIO):
        def write(self, value):
            assert len(value) <= 7
            return super().write(value)
    budget = CaptureBudget(7)
    stdout = CaptureStream(MeteredBuffer, budget)
    stderr = CaptureStream(MeteredBuffer, budget)
    for _ in range(2000):
        stdout.write("x" * write_size)
        stderr.write("y" * write_size)
        stdout.write("")
    assert budget.retained == 7
    assert len(stdout.parts) + len(stderr.parts) <= 7
    assert len(stdout.buffer.getvalue()) + len(stderr.buffer.getvalue()) == 7
    assert stdout.dropped + stderr.dropped == 4000 * write_size - 7


def test_zero_limit_discards_output_but_does_not_skip_execution():
    namespace = {"effects": []}
    result = execute_script("print('dropped')\neffects.append('executed')", namespace, output_limit_chars=0)
    assert namespace["effects"] == ["executed"]
    assert result["status"] == "success" and result["output"] == ""
    assert result["output_truncated"] and result["output_capture"]["retained_chars"] == 0


def test_exception_after_overflow_preserves_prefix_and_streams():
    streams = sys.stdout, sys.stderr
    result = execute_script("print('0123456789')\nassert False", {}, output_limit_chars=4)
    assert result["error_type"] == "AssertionError"
    assert result["partial_output"] == "0123"
    assert result["output_truncated"]
    assert (sys.stdout, sys.stderr) == streams


def test_shared_cap_is_atomic_for_concurrent_stream_writes():
    budget = CaptureBudget(13)
    stdout = CaptureStream(StringIO, budget)
    stderr = CaptureStream(StringIO, budget)
    def write(index):
        (stdout if index % 2 else stderr).write("x" * 5)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(200)))
    assert budget.retained == 13
    assert len(stdout.buffer.getvalue()) + len(stderr.buffer.getvalue()) == 13
    assert stdout.dropped + stderr.dropped == 1000 - 13


@pytest.mark.parametrize("limit", [-1, True, None, 2.5, "5"])
def test_invalid_limit_fails_before_code_and_has_structured_payload_error(execution_route, limit):
    with pytest.raises(ValueError, match="output_limit_chars"):
        execute_script("raise AssertionError('must not run')", {}, output_limit_chars=limit)
    result, status = execution_route.execute_payload({"code": "pass"}, None, None, output_limit_chars=limit)
    assert status == 400 and result["effects"] == "none"


def test_execution_owner_injects_limit_and_overflow_does_not_change_commit(execution_route):
    execution_route.DB = FakeDB()
    doc = Document()
    result, status = execution_route.execute_payload(
        {"code": "print('0123456789')\ndoc.value = 5", "transaction_mode": "managed"}, doc, None,
        output_limit_chars=3)
    assert status == 200 and result["effects"] == "committed"
    assert result["output"] == "012" and result["output_truncated"]
    assert doc.value == 5
