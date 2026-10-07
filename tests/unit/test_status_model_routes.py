"""Controlled route tests; these do not establish native Revit thread safety."""
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class CapturedAPI:
    def __init__(self):
        self.handlers = {}

    def route(self, path, methods):
        def register(handler):
            self.handlers[(path, tuple(methods))] = handler
            return handler
        return register


@pytest.fixture
def registered_routes(monkeypatch):
    """Import real handlers with isolated pyRevit/query dependencies."""
    document_reads = []
    global_reads = []

    class GuardedRevit(ModuleType):
        def __getattr__(self, name):
            if name == "doc":
                global_reads.append(name)
                raise AssertionError("Handlers must use the injected document")
            raise AttributeError(name)

    class Collector:
        def __init__(self, doc):
            document_reads.append(doc)

        def OfCategory(self, category):
            return self

        def OfClass(self, cls):
            return self

        def WhereElementIsNotElementType(self):
            return self

        def GetElementCount(self):
            return 2

        def ToElements(self):
            return []

    def project_info(doc):
        document_reads.append(doc)
        return SimpleNamespace(name="Project", number="42", client_name="Client")

    def linked_models(doc):
        document_reads.append(doc)
        return SimpleNamespace(ToElements=lambda: [])

    categories = [
        "Walls", "Floors", "Ceilings", "Roofs", "Doors", "Windows", "Stairs",
        "Railings", "Columns", "StructuralFraming", "Furniture",
        "LightingFixtures", "PlumbingFixtures", "Levels", "Rooms", "Sheets",
    ]
    db_api = SimpleNamespace(
        BuiltInCategory=SimpleNamespace(**{"OST_" + c: c for c in categories}),
        FilteredElementCollector=Collector,
        View=object,
        WarningType=SimpleNamespace(Error="Error"),
    )
    pyrevit = ModuleType("pyrevit")
    pyrevit.__path__ = []
    revit = GuardedRevit("pyrevit.revit")
    revit.__path__ = []
    revit_db = ModuleType("pyrevit.revit.db")
    revit_db.__path__ = []
    revit_db.ProjectInfo = project_info
    query = ModuleType("pyrevit.revit.db.query")
    query.get_linked_model_instances = linked_models
    pyrevit.revit = revit
    pyrevit.DB = db_api
    pyrevit.routes = SimpleNamespace(
        API=lambda name: CapturedAPI(),
        make_response=lambda data, status=200: {"data": data, "status": status}
    )
    # String/name helpers are outside this focused document-injection change.
    utils = ModuleType("revit_mcp.utils")
    utils.normalize_string = lambda value: value.strip()
    utils.get_element_name = lambda element: element.Name
    for name, module in {
        "pyrevit": pyrevit,
        "pyrevit.revit": revit,
        "pyrevit.revit.db": revit_db,
        "pyrevit.revit.db.query": query,
        "revit_mcp.utils": utils,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    api = CapturedAPI()
    source_dir = Path(__file__).resolve().parents[2] / "revit_mcp"
    for name in ("status", "model_info"):
        spec = importlib.util.spec_from_file_location(
            "revit_mcp._test_" + name, source_dir / (name + ".py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, "revit_mcp." + name, module)
        getattr(module, "register_" + name + "_routes")(api)
        if name == "status":
            status_registrar = module.register_status_routes
            module.register_liveness_routes(api)
    assert document_reads == [], "Registration must not query a document"
    yield SimpleNamespace(
        api=api, document_reads=document_reads, status_registrar=status_registrar,
    )
    assert global_reads == [], "Handlers accessed global revit.doc"


@pytest.mark.parametrize("path", ["/status/", "/model_info/"])
def test_registered_handler_requests_routes_api_context(registered_routes, path):
    handler = registered_routes.api.handlers[(path, ("GET",))]
    parameters = inspect.signature(handler).parameters
    assert "doc" in parameters
    assert parameters["doc"].default is inspect.Parameter.empty


def test_liveness_never_requests_document_context(registered_routes):
    handler = registered_routes.api.handlers[("/health/", ("GET",))]
    assert not ({"doc", "uidoc", "uiapp"} & set(inspect.signature(handler).parameters))
    assert handler() == {
        "status": 200, "data": {"status": "alive", "api_name": "revit_mcp"},
    }
    assert registered_routes.document_reads == []


def test_status_registrar_accepts_api_that_disallows_liveness(registered_routes):
    """Targeted model-route wrappers must not acquire an unguarded health route."""
    class StatusOnlyAPI(CapturedAPI):
        def route(self, path, methods):
            assert path == "/status/", "Unknown model route"
            return super().route(path, methods)

    api = StatusOnlyAPI()
    registered_routes.status_registrar(api)
    assert set(api.handlers) == {("/status/", ("GET",))}


def test_legacy_startup_registers_liveness_separately(registered_routes, monkeypatch):
    # This parent-layer test isolates the independent status registration seam.
    # Real successful/degraded identity composition is covered by identity tests.
    monkeypatch.setattr("revit_mcp.target_runtime.initialize_legacy_identity", lambda api: None)
    for name, registrar in {
        "views": "register_views_routes", "placement": "register_placement_routes",
        "colors": "register_color_routes", "code_execution": "register_code_execution_routes",
        "document": "register_document_routes",
    }.items():
        module = ModuleType("revit_mcp." + name)
        setattr(module, registrar, lambda api: None)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    source = Path(__file__).resolve().parents[2] / "startup.py"
    spec = importlib.util.spec_from_file_location("_test_legacy_startup", source)
    startup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(startup)
    assert set(startup.api.handlers) == {
        ("/health/", ("GET",)), ("/status/", ("GET",)), ("/model_info/", ("GET",)),
    }
    assert startup.api.handlers[("/health/", ("GET",))]() == {
        "status": 200, "data": {"status": "alive", "api_name": "revit_mcp"},
    }
    assert registered_routes.document_reads == []


async def test_launch_liveness_bypasses_pending_document_dispatch(registered_routes, monkeypatch):
    """Exercise the real poller and registered routes with API dispatch unavailable."""
    import time
    from unittest.mock import AsyncMock
    from tools.launch_tools import _wait_for_revit_ready
    from tools.revit_transport import RevitTransportResult
    from tools.utils import compatibility_response

    timestamps = iter([0, 0, 0, 10])
    monkeypatch.setattr(time, "time", lambda: next(timestamps, 10))
    sleep = AsyncMock()
    monkeypatch.setattr("tools.launch_tools.anyio.sleep", sleep)
    calls = []

    async def dispatch(path, **kwargs):
        calls.append(path)
        handler = registered_routes.api.handlers[(path, ("GET",))]
        if "doc" in inspect.signature(handler).parameters:
            return "Error: Request timed out waiting for Revit API context"
        response = handler()
        return compatibility_response(RevitTransportResult(
            method="GET", url="http://fixture.invalid" + path,
            status_code=response["status"], body=response["data"], json_received=True,
        ))

    ready, response = await _wait_for_revit_ready(dispatch, ctx=None, timeout=1)
    assert ready is True
    assert response == {"status": "alive", "api_name": "revit_mcp"}
    assert calls == ["/health/"]
    sleep.assert_not_awaited()
    assert registered_routes.document_reads == []


@pytest.mark.parametrize("title", ["Study", "Étude", ""])
def test_status_preserves_success_response(registered_routes, title):
    handler = registered_routes.api.handlers[("/status/", ("GET",))]
    assert handler(doc=SimpleNamespace(Title=title)) == {
        "status": 200,
        "data": {
            "status": "active", "health": "healthy", "revit_available": True,
            "document_title": title or "Untitled", "api_name": "revit_mcp",
        },
    }


@pytest.mark.parametrize("path, expected", [
    ("/status/", {
        "status": "unhealthy", "revit_available": False,
        "error": "No active Revit document", "api_name": "revit_mcp",
    }),
    ("/model_info/", {"error": "No active Revit document"}),
])
def test_no_document_preserves_503_without_queries(registered_routes, path, expected):
    handler = registered_routes.api.handlers[(path, ("GET",))]
    assert handler(doc=None) == {"status": 503, "data": expected}
    assert registered_routes.document_reads == []


def test_model_info_uses_injected_document_for_all_queries(registered_routes):
    doc = SimpleNamespace(Title="Injected study", GetWarnings=lambda: [])
    handler = registered_routes.api.handlers[("/model_info/", ("GET",))]
    response = handler(doc=doc)
    assert response["status"] == 200
    data = response["data"]
    assert set(data) == {
        "status", "project_info", "element_summary", "model_health",
        "spatial_organization", "documentation", "linked_models",
    }
    assert data["status"] == "success"
    assert data["project_info"] == {
        "name": "Project", "number": "42", "client": "Client",
        "file_name": "Injected study",
    }
    assert data["element_summary"]["total_elements"] == 26
    assert len(data["element_summary"]["by_category"]) == 13
    assert set(data["element_summary"]["by_category"].values()) == {2}
    assert data["model_health"] == {
        "total_warnings": 0, "critical_warnings": 0, "unplaced_rooms": 0,
    }
    assert data["spatial_organization"] == {"levels": [], "rooms": [], "room_count": 0}
    assert data["documentation"] == {
        "total_views": 0, "sheets_count": 2,
        "view_breakdown": {
            "floor_plans": 0, "elevations": 0, "sections": 0,
            "3d_views": 0, "schedules": 0,
        },
    }
    assert data["linked_models"] == {"count": 0, "models": []}
    assert registered_routes.document_reads
    assert all(queried is doc for queried in registered_routes.document_reads)


def test_model_info_preserves_project_info_fallback(registered_routes, monkeypatch):
    def unavailable(doc):
        raise RuntimeError("No project information")

    # ProjectInfo was imported during registration; replace that dependency.
    handler = registered_routes.api.handlers[("/model_info/", ("GET",))]
    monkeypatch.setitem(handler.__globals__, "RevitProjectInfo", unavailable)
    doc = SimpleNamespace(Title="Family study", GetWarnings=lambda: [])
    response = handler(doc=doc)
    assert response["status"] == 200
    assert response["data"]["project_info"] == {
        "name": "Family study", "number": "Not Set", "client": "Not Set",
        "file_name": "Family study",
    }


@pytest.mark.parametrize("path, status, expected", [
    ("/status/", 503, {
        "status": "unhealthy", "revit_available": False,
        "error": "Document unavailable", "api_name": "revit_mcp",
    }),
    ("/model_info/", 500, {
        "error": "Failed to retrieve model information: Document unavailable",
    }),
])
def test_document_error_preserves_error_response(registered_routes, path, status, expected):
    class UnavailableDocument:
        @property
        def Title(self):
            raise RuntimeError("Document unavailable")

    handler = registered_routes.api.handlers[(path, ("GET",))]
    assert handler(doc=UnavailableDocument()) == {"status": status, "data": expected}
