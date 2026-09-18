from app.main import app


def test_required_routes_are_documented() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/health",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/projects",
        "/api/projects/{project_id}/members",
        "/api/projects/{project_id}/tasks",
        "/api/projects/{project_id}/stats",
        "/api/tasks",
        "/api/tags",
        "/api/tasks/{task_id}/comments",
    }
    assert required <= paths.keys()

