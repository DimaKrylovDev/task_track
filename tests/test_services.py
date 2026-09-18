from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.domain.enums import ProjectRole
from app.services.projects import ProjectService
from app.services.tasks import TaskService


class FakeProjectRepository:
    def __init__(self, project, member) -> None:
        self.project = project
        self.member = member

    async def get_accessible(self, project_id, user_id):
        return self.project

    async def get_membership(self, project_id, user_id):
        return self.member


class FakeUnitOfWork:
    def __init__(self, projects) -> None:
        self.projects = projects
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_member_cannot_update_project() -> None:
    owner_id = uuid4()
    member_id = uuid4()
    project = SimpleNamespace(owner_id=owner_id, name="Old", description=None)
    repo = FakeProjectRepository(project, SimpleNamespace(role=ProjectRole.MEMBER))
    service = ProjectService(FakeUnitOfWork(repo))

    with pytest.raises(ForbiddenError):
        await service.update(uuid4(), member_id, "New", None)


@pytest.mark.asyncio
async def test_owner_membership_cannot_be_removed() -> None:
    owner_id = uuid4()
    project = SimpleNamespace(owner_id=owner_id)
    owner_member = SimpleNamespace(role=ProjectRole.OWNER)
    repo = FakeProjectRepository(project, owner_member)
    service = ProjectService(FakeUnitOfWork(repo))

    with pytest.raises(ConflictError):
        await service.remove_member(uuid4(), owner_id, owner_id)


@pytest.mark.asyncio
async def test_task_rejects_tag_from_another_project() -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    user_id = uuid4()
    tag_id = uuid4()
    uow = FakeUnitOfWork(FakeProjectRepository(None, SimpleNamespace()))
    uow.tags = SimpleNamespace(
        get_many=lambda tag_ids: _async_value(
            [SimpleNamespace(id=tag_id, project_id=other_project_id)]
        )
    )
    uow.users = SimpleNamespace(get=lambda _: _async_value(SimpleNamespace(id=user_id)))

    with pytest.raises(NotFoundError, match="do not belong to this project"):
        await TaskService(uow).create(
            user_id=user_id,
            project_id=project_id,
            title="Task",
            description=None,
            status="TODO",
            priority="MEDIUM",
            assignee_id=None,
            due_at=None,
            tag_ids=[tag_id],
        )


async def _async_value(value):
    return value
