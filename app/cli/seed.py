import argparse
import asyncio
import random
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import insert

from app.cli.partitions import create_missing_task_partitions
from app.core.security import hash_password
from app.db.models import Comment, Project, ProjectMember, Tag, Task, TaskTag, User
from app.db.partitioning import add_months, month_start, required_months
from app.db.session import session_factory
from app.domain.enums import ProjectRole, TaskPriority, TaskStatus


def chunks[T](items: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def bulk_insert(model, rows: list[dict], batch_size: int) -> None:
    if not rows:
        return
    async with session_factory() as session:
        for batch in chunks(rows, batch_size):
            await session.execute(insert(model), batch)
            await session.commit()


async def generate(args: argparse.Namespace) -> None:
    if args.users < 1 or args.projects < 1:
        raise ValueError("--users and --projects must be at least 1")
    if args.members_per_project < 1:
        raise ValueError("--members-per-project must be at least 1")
    if args.tasks < 0 or args.comments < 0 or args.tags_per_project < 0:
        raise ValueError("Entity counts cannot be negative")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1")

    rng = random.Random(args.seed)
    run_id = uuid4().hex[:10]
    shared_password_hash = hash_password(args.password)

    user_ids = [uuid4() for _ in range(args.users)]
    users = [
        {
            "id": user_id,
            "email": f"seed-{run_id}-{index}@example.com",
            "display_name": f"Seed User {index:06d}",
            "password_hash": shared_password_hash,
        }
        for index, user_id in enumerate(user_ids, start=1)
    ]
    await bulk_insert(User, users, args.batch_size)

    project_ids = [uuid4() for _ in range(args.projects)]
    projects: list[dict] = []
    project_members: dict[UUID, list[UUID]] = {}
    memberships: list[dict] = []
    member_count = min(args.members_per_project, len(user_ids))
    for index, project_id in enumerate(project_ids):
        rotated = user_ids[index % len(user_ids) :] + user_ids[: index % len(user_ids)]
        members = rotated[:member_count]
        owner_id = members[0]
        project_members[project_id] = members
        projects.append(
            {
                "id": project_id,
                "name": f"Seed Project {run_id}-{index + 1}",
                "description": "Automatically generated project",
                "owner_id": owner_id,
            }
        )
        memberships.extend(
            {
                "project_id": project_id,
                "user_id": user_id,
                "role": ProjectRole.OWNER if user_id == owner_id else ProjectRole.MEMBER,
            }
            for user_id in members
        )
    await bulk_insert(Project, projects, args.batch_size)
    await bulk_insert(ProjectMember, memberships, args.batch_size)

    tags_by_project: dict[UUID, list[UUID]] = {}
    tags: list[dict] = []
    palette = ["#EF4444", "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6", "#EC4899"]
    for project_id in project_ids:
        tag_ids = [uuid4() for _ in range(args.tags_per_project)]
        tags_by_project[project_id] = tag_ids
        tags.extend(
            {
                "id": tag_id,
                "project_id": project_id,
                "name": f"tag-{tag_index + 1}",
                "color": palette[tag_index % len(palette)],
            }
            for tag_index, tag_id in enumerate(tag_ids)
        )
    await bulk_insert(Tag, tags, args.batch_size)

    statuses = list(TaskStatus)
    priorities = list(TaskPriority)
    now = datetime.now(UTC)
    first_month = month_start(now - timedelta(days=731))
    last_month = required_months(now)[-1]
    months = []
    start = first_month
    while start <= last_month:
        months.append(start)
        start = add_months(start, 1)
    async with session_factory() as session:
        await create_missing_task_partitions(await session.connection(), tuple(months))
        await session.commit()
    task_ids: list[UUID] = []
    task_dates: list[datetime] = []
    task_rows: list[dict] = []
    task_tag_rows: list[dict] = []

    async def flush_tasks() -> None:
        nonlocal task_rows, task_tag_rows
        await bulk_insert(Task, task_rows, args.batch_size)
        await bulk_insert(TaskTag, task_tag_rows, args.batch_size)
        task_rows = []
        task_tag_rows = []

    for index in range(args.tasks):
        task_id = uuid4()
        project_id = project_ids[index % len(project_ids)]
        members = project_members[project_id]
        task_ids.append(task_id)
        created_at = now - timedelta(days=rng.randint(0, 730), seconds=rng.randint(0, 86400))
        task_dates.append(created_at)
        task_rows.append(
            {
                "id": task_id,
                "project_id": project_id,
                "creator_id": rng.choice(members),
                "assignee_id": rng.choice(members) if rng.random() < 0.85 else None,
                "title": f"Generated task {run_id}-{index + 1}",
                "description": f"Synthetic task number {index + 1} for query experiments",
                "status": rng.choice(statuses),
                "priority": rng.choice(priorities),
                "due_at": now + timedelta(days=rng.randint(-90, 180)),
                "created_at": created_at,
                "updated_at": now,
            }
        )
        available_tags = tags_by_project[project_id]
        if available_tags:
            selected = rng.sample(available_tags, k=rng.randint(0, min(2, len(available_tags))))
            task_tag_rows.extend(
                {"task_id": task_id, "task_created_at": created_at, "tag_id": tag_id}
                for tag_id in selected
            )
        if len(task_rows) >= args.batch_size:
            await flush_tasks()
    await flush_tasks()

    comment_rows: list[dict] = []
    if args.comments and not task_ids:
        raise ValueError("Comments cannot be generated when --tasks is 0")
    for index in range(args.comments):
        task_index = rng.randrange(len(task_ids))
        task_id = task_ids[task_index]
        project_id = project_ids[task_index % len(project_ids)]
        comment_rows.append(
            {
                "id": uuid4(),
                "task_id": task_id,
                "task_created_at": task_dates[task_index],
                "author_id": rng.choice(project_members[project_id]),
                "body": f"Generated comment {run_id}-{index + 1}",
            }
        )
        if len(comment_rows) >= args.batch_size:
            await bulk_insert(Comment, comment_rows, args.batch_size)
            comment_rows = []
    await bulk_insert(Comment, comment_rows, args.batch_size)

    print(
        f"Generated run {run_id}: users={args.users}, projects={args.projects}, "
        f"tasks={args.tasks}, comments={args.comments}. Seed user password: {args.password}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append synthetic task-tracker data")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--projects", type=int, default=3)
    parser.add_argument("--tasks", type=int, default=100)
    parser.add_argument("--comments", type=int, default=200)
    parser.add_argument("--tags-per-project", type=int, default=6)
    parser.add_argument("--members-per-project", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--password", default="SeedPassword123!")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(generate(parse_args()))
