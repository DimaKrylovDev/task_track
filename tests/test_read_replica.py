from fastapi.routing import APIRoute

from app.api.deps import get_read_uow
from app.api.routers.tasks import router
from app.db.session import replica_session_factory


def test_read_uow_uses_replica_session_factory() -> None:
    assert get_read_uow().session_factory is replica_session_factory


def test_only_task_list_routes_depend_on_read_uow() -> None:
    replica_routes = {
        (route.path, method)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if any(dependency.call is get_read_uow for dependency in route.dependant.dependencies)
    }
    assert replica_routes == {
        ("/api/tasks", "GET"),
        ("/api/projects/{project_id}/tasks", "GET"),
    }
