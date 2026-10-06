# -*- coding: utf-8 -*-
"""Root conftest — register markers and shared fixtures."""
import pytest
import os
from unittest.mock import AsyncMock


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires running Revit instance")


def pytest_collection_modifyitems(items):
    # The historical native fixtures can launch Revit and modify documents.
    # A bundled test.rvt is not explicit authorization to use an open session.
    if not os.environ.get("REVIT_MCP_DISPOSABLE_FIXTURE"):
        pending = pytest.mark.skip(reason="Native coverage requires an explicitly supplied disposable fixture")
        for item in items:
            if item.get_closest_marker("integration"):
                item.add_marker(pending)


class MockMCP:
    """Minimal stand-in for FastMCP that captures tool registrations."""

    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


@pytest.fixture
def mock_mcp():
    return MockMCP()


@pytest.fixture
def mock_revit_get():
    return AsyncMock(name="revit_get")


@pytest.fixture
def mock_revit_post():
    return AsyncMock(name="revit_post")


@pytest.fixture
def mock_revit_image():
    return AsyncMock(name="revit_image")
