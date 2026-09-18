import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_read_uow, get_uow
from app.db.base import Base
from app.main import app
from app.repositories.uow import SqlAlchemyUnitOfWork

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="Set TEST_DATABASE_URL to run PostgreSQL integration tests"
)


@pytest_asyncio.fixture
async def client():
    assert TEST_DATABASE_URL is not None
    database_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in database_name.lower():
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a database containing 'test' in its name"
        )
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_read_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api
    app.dependency_overrides.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def register(client: AsyncClient, number: int) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={
            "email": f"user{number}@example.com",
            "display_name": f"User {number}",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_full_project_task_flow_and_refresh_rotation(client: AsyncClient) -> None:
    owner = await register(client, 1)
    member = await register(client, 2)
    outsider = await register(client, 3)
    owner_headers = {"Authorization": f"Bearer {owner['tokens']['access_token']}"}
    member_headers = {"Authorization": f"Bearer {member['tokens']['access_token']}"}
    outsider_headers = {"Authorization": f"Bearer {outsider['tokens']['access_token']}"}

    project_response = await client.post(
        "/api/projects",
        headers=owner_headers,
        json={"name": "Platform", "description": "Main project"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]

    forbidden = await client.get(f"/api/projects/{project_id}", headers=outsider_headers)
    assert forbidden.status_code == 404

    member_response = await client.post(
        f"/api/projects/{project_id}/members",
        headers=owner_headers,
        json={"user_id": member["user"]["id"]},
    )
    assert member_response.status_code == 201, member_response.text

    tag_response = await client.post(
        "/api/tags",
        headers=member_headers,
        json={"project_id": project_id, "name": "backend", "color": "#3B82F6"},
    )
    assert tag_response.status_code == 201, tag_response.text
    tag_id = tag_response.json()["id"]

    task_response = await client.post(
        "/api/tasks",
        headers=member_headers,
        json={
            "project_id": project_id,
            "title": "Implement API",
            "description": "FastAPI service",
            "status": "IN_PROGRESS",
            "priority": "HIGH",
            "assignee_id": member["user"]["id"],
            "due_at": None,
            "tag_ids": [tag_id],
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = task_response.json()["id"]

    page = await client.get(
        f"/api/projects/{project_id}/tasks",
        headers=owner_headers,
        params={"status": "IN_PROGRESS", "search": "API", "page_size": 10},
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["tags"][0]["id"] == tag_id

    comment = await client.post(
        f"/api/tasks/{task_id}/comments",
        headers=owner_headers,
        json={"body": "Looks good"},
    )
    assert comment.status_code == 201, comment.text

    stats = await client.get(f"/api/projects/{project_id}/stats", headers=owner_headers)
    assert stats.status_code == 200, stats.text
    assert stats.json()["by_status"]["IN_PROGRESS"] == 1

    old_refresh = owner["tokens"]["refresh_token"]
    refreshed = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert refreshed.status_code == 200, refreshed.text
    replay = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401
    logout = await client.post(
        "/api/auth/logout",
        headers=owner_headers,
        json={"refresh_token": refreshed.json()["refresh_token"]},
    )
    assert logout.status_code == 204
