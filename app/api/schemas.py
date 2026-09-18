from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.domain.enums import ProjectRole, TaskPriority, TaskStatus

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class UserSummary(ORMModel):
    id: UUID
    email: EmailStr
    display_name: str


class UserRead(UserSummary):
    created_at: datetime
    updated_at: datetime


class UserPut(BaseModel):
    email: EmailStr
    display_name: Annotated[Name, StringConstraints(max_length=120)]


class RegisterRequest(UserPut):
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(ORMModel):
    access_token: str
    refresh_token: str
    token_type: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class AuthResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class ProjectCreate(BaseModel):
    name: Annotated[Name, StringConstraints(max_length=160)]
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None


class ProjectPut(ProjectCreate):
    pass


class ProjectSummary(ORMModel):
    id: UUID
    name: str


class ProjectRead(ProjectSummary):
    description: str | None
    owner_id: UUID
    owner: UserSummary
    created_at: datetime
    updated_at: datetime


class MemberCreate(BaseModel):
    user_id: UUID


class MemberRead(ORMModel):
    project_id: UUID
    user_id: UUID
    role: ProjectRole
    joined_at: datetime
    user: UserSummary


class TagCreate(BaseModel):
    project_id: UUID
    name: Annotated[Name, StringConstraints(max_length=60)]
    color: Color = "#808080"


class TagPut(BaseModel):
    name: Annotated[Name, StringConstraints(max_length=60)]
    color: Color


class TagRead(ORMModel):
    id: UUID
    project_id: UUID
    name: str
    color: str
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    project_id: UUID
    title: Annotated[Name, StringConstraints(max_length=240)]
    description: Annotated[str, StringConstraints(max_length=20_000)] | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)


class TaskPut(BaseModel):
    title: Annotated[Name, StringConstraints(max_length=240)]
    description: Annotated[str, StringConstraints(max_length=20_000)] | None
    status: TaskStatus
    priority: TaskPriority
    assignee_id: UUID | None
    due_at: datetime | None
    tag_ids: list[UUID] = Field(max_length=50)


class TaskSummary(ORMModel):
    id: UUID
    project_id: UUID
    title: str


class TaskRead(TaskSummary):
    creator_id: UUID
    assignee_id: UUID | None
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    project: ProjectSummary
    creator: UserSummary
    assignee: UserSummary | None
    tags: list[TagRead]


class TaskPage(BaseModel):
    items: list[TaskRead]
    total: int
    page: int
    page_size: int
    pages: int


class AssigneeStats(BaseModel):
    user_id: UUID
    display_name: str
    task_count: int


class ProjectStats(BaseModel):
    by_status: dict[str, int]
    by_priority: dict[str, int]
    overdue: int
    by_assignee: list[AssigneeStats]


class CommentCreate(BaseModel):
    body: Annotated[Name, StringConstraints(max_length=10_000)]


class CommentPut(CommentCreate):
    pass


class CommentRead(ORMModel):
    id: UUID
    task_id: UUID
    author_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime
    task: TaskSummary
    author: UserSummary


class HealthResponse(BaseModel):
    status: str
    database: str

