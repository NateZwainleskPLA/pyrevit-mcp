import hashlib
from unittest.mock import AsyncMock

import pytest

from scripts.execute_revit_file import execute_script_file, read_script_file
from tools.code_execution_tools import register_code_execution_tools


def test_unicode_bom_crlf_basename_and_submitted_content_hash(tmp_path):
    path = tmp_path / "検証.py"
    path.write_bytes(b"\xef\xbb\xbf" + "# café\r\nprint('画像')\r\n".encode("utf-8"))
    payload = read_script_file(path)
    assert payload["code"] == "# café\nprint('画像')\n"
    assert payload["script_name"] == "検証.py"
    assert payload["script_sha256"] == hashlib.sha256(payload["code"].encode("utf-8")).hexdigest()
    assert str(tmp_path) not in str(payload)


async def test_remote_execution_reads_only_local_file_and_uses_normal_targeted_route(tmp_path):
    path = tmp_path / "edit.py"
    path.write_text("print('client-local')", encoding="utf-8")
    router = type("Router", (), {"call": AsyncMock(return_value="receipt")})()
    result = await execute_script_file(router, path, target="remote-runtime", document="d1",
                                       transaction_mode="managed", allow_ui_change=True)
    assert result == "receipt"
    router.call.assert_awaited_once()
    call = router.call.await_args
    assert call.args == ("POST", "/execute_code/")
    assert call.kwargs["target"] == "remote-runtime"
    assert call.kwargs["document"] == "d1"
    assert call.kwargs["data"]["code"] == "print('client-local')"
    assert call.kwargs["data"]["transaction_mode"] == "managed"
    assert "file_path" not in call.kwargs["data"]


@pytest.mark.parametrize("contents", [None, b"\xff\xfe"])
async def test_missing_or_invalid_utf8_never_sends_request(tmp_path, contents):
    path = tmp_path / "bad.py"
    if contents is not None:
        path.write_bytes(contents)
    router = type("Router", (), {"call": AsyncMock()})()
    with pytest.raises((OSError, UnicodeError)):
        await execute_script_file(router, path, target="r1", document="d1")
    router.call.assert_not_awaited()


async def test_mcp_file_tool_preserves_diagnostics_and_targeted_payload(tmp_path, mock_mcp):
    path = tmp_path / "fail.py"
    path.write_text("raise AssertionError('named check')", encoding="utf-8")
    post = AsyncMock(return_value={"status": "error", "error": "AssertionError", "script_location": {"filename": "fail.py", "line": 1},
                                  "partial_output": "before", "actual_target": {"instance_id": "actual"}})
    register_code_execution_tools(mock_mcp, AsyncMock(), post)
    result = await mock_mcp.tools["execute_revit_script_file"](target="r1", document="d1", file_path=str(path))
    assert "fail.py" in result and "before" in result and "actual" in result
    assert post.await_args.kwargs["target"] == "r1"
    assert post.await_args.kwargs["document"] == "d1"
    assert post.await_args.args[1]["script_name"] == "fail.py"
    post.assert_awaited_once()
