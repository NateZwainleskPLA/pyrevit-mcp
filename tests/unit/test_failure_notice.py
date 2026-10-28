"""Notice text and accumulation; the WPF window itself was checked live in Revit 2025.5."""
import datetime

import pytest

from revit_mcp import failure_notice

NOON = datetime.datetime(2026, 10, 28, 12, 0, 5)


def failure(severity="Error", action="rolled_back", description="Cant set parameter", ids=(), transaction="Edit"):
    return {"severity": severity, "description": description, "element_ids": list(ids),
            "transaction": transaction, "action": action}


@pytest.fixture
def shown(monkeypatch):
    monkeypatch.setattr(failure_notice, "_state", {"window": None, "box": None, "entries": [], "count": 0})
    calls = []
    monkeypatch.setattr(failure_notice, "_display", lambda title, text, application: calls.append((title, text)))
    return calls


def test_entries_list_only_rolled_back_errors_with_their_ids():
    entries = failure_notice.notice_entries([
        failure(ids=range(1, 8), transaction="Set marks"),
        failure("Warning", description="Highlighted walls overlap."),
        failure("Warning", "kept", "Line is slightly off axis"),
        failure("DocumentCorruption", description="Corrupt"),
        {"action": "capture_error", "error": "accessor unavailable"},
    ], now=NOON)
    assert entries == [u"12:00:05  Set marks\n    Cant set parameter  (ids 1, 2, 3, 4, 5, ...)",
                       u"12:00:05  Edit\n    Corrupt"]


def test_calls_without_rolled_back_errors_show_nothing(shown):
    failure_notice.notify_rolled_back([failure("Warning", "kept")])
    failure_notice.notify_rolled_back([])
    assert shown == []


def test_errors_collect_newest_first_with_a_running_count(shown):
    failure_notice.notify_rolled_back([failure(transaction="First")])
    failure_notice.notify_rolled_back([failure(transaction="Second"), failure(transaction="Third")])
    assert shown[0][0] == "Revit MCP: 1 agent error rolled back"
    title, text = shown[-1]
    assert title == "Revit MCP: 3 agent errors rolled back"
    assert [line.split("  ", 1)[1] for line in text.split("\n")[::2]] == ["Third", "Second", "First"]


def test_list_is_capped_and_closing_starts_over(shown):
    for index in range(failure_notice.MAX_ENTRIES + 5):
        failure_notice.notify_rolled_back([failure(transaction="T{0}".format(index))])
    assert len(failure_notice._state["entries"]) == failure_notice.MAX_ENTRIES
    assert failure_notice._state["entries"][0].endswith("T{0}\n    Cant set parameter".format(index))
    failure_notice._closed(None, None)
    failure_notice.notify_rolled_back([failure()])
    assert shown[-1][0] == "Revit MCP: 1 agent error rolled back"


def test_notice_never_raises_into_execution(monkeypatch):
    monkeypatch.setattr(failure_notice, "_state", {"window": None, "box": None, "entries": [], "count": 0})
    monkeypatch.setattr(failure_notice, "_display", lambda *args: (_ for _ in ()).throw(RuntimeError("no UI")))
    failure_notice.notify_rolled_back([failure()])
