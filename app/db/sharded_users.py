from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.models import User
from app.db.sharding import ShardRouter


@dataclass(frozen=True, slots=True)
class ShardedUser:
    id: UUID
    email: str
    display_name: str
    created_at: datetime | None = None


class ShardQueryError(RuntimeError):
    def __init__(self, failed_shards: Iterable[str]) -> None:
        self.failed_shards = tuple(failed_shards)
        super().__init__(f"Shard query failed: {', '.join(self.failed_shards)}")


def merge_user_pages(
    pages: Iterable[Iterable[ShardedUser]], limit: int
) -> list[ShardedUser]:
    candidates = [user for page in pages for user in page]
    candidates.sort(key=lambda user: (user.display_name, user.email))
    return candidates[:limit]


class ShardedUserStore:
    """User storage whose router selects one independent PostgreSQL engine."""

    def __init__(self, router: ShardRouter, urls: Mapping[str, str]) -> None:
        if set(router.nodes) != set(urls):
            raise ValueError("Router nodes and database URL names must match")
        self.router = router
        self.engines: dict[str, AsyncEngine] = {
            node: create_async_engine(
                urls[node],
                pool_pre_ping=True,
                connect_args={"server_settings": {"application_name": "krasova-shard-router"}},
            )
            for node in router.nodes
        }

    async def initialize(self) -> None:
        for engine in self.engines.values():
            async with engine.begin() as connection:
                await connection.run_sync(User.__table__.create, checkfirst=True)

    async def clear(self) -> None:
        for engine in self.engines.values():
            async with engine.begin() as connection:
                await connection.execute(delete(User))

    async def add_many(self, users: Iterable[ShardedUser]) -> None:
        grouped: dict[str, list[dict[str, object]]] = {
            node: [] for node in self.router.nodes
        }
        now = datetime.now(UTC)
        for user in users:
            grouped[self.router.route(user.id)].append(
                {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "password_hash": "lab5-not-for-login",
                    "created_at": now,
                    "updated_at": now,
                }
            )

        statement = insert(User).on_conflict_do_nothing(index_elements=[User.id])
        for node, rows in grouped.items():
            if rows:
                async with self.engines[node].begin() as connection:
                    await connection.execute(statement, rows)

    async def get(self, user_id: UUID) -> ShardedUser | None:
        node = self.router.route(user_id)
        async with self.engines[node].connect() as connection:
            row = (
                await connection.execute(
                    select(User.id, User.email, User.display_name, User.created_at).where(
                        User.id == user_id
                    )
                )
            ).one_or_none()
        return ShardedUser(**row._mapping) if row is not None else None

    async def _all_shards[T](
        self, operation: Callable[[str, AsyncEngine], Awaitable[T]]
    ) -> dict[str, T]:
        node_names = tuple(self.engines)
        values = await asyncio.gather(
            *(operation(node, self.engines[node]) for node in node_names),
            return_exceptions=True,
        )
        failed = [
            node for node, value in zip(node_names, values, strict=True)
            if isinstance(value, BaseException)
        ]
        if failed:
            raise ShardQueryError(failed)
        return {
            node: value
            for node, value in zip(node_names, values, strict=True)
            if not isinstance(value, BaseException)
        }

    async def counts(self) -> dict[str, int]:
        async def count_node(_node: str, engine: AsyncEngine) -> int:
            async with engine.connect() as connection:
                statement = select(func.count()).select_from(User)
                return int(await connection.scalar(statement) or 0)

        return await self._all_shards(count_node)

    async def count_all(self) -> int:
        """Map COUNT to every shard and reduce the partial counts in backend."""

        return sum((await self.counts()).values())

    async def search(self, query: str, limit: int = 20) -> list[ShardedUser]:
        """Merge per-shard ORDER BY/LIMIT results into one globally ordered page."""

        if limit < 1:
            raise ValueError("limit must be positive")

        async def search_node(_node: str, engine: AsyncEngine) -> list[ShardedUser]:
            async with engine.connect() as connection:
                pattern = f"%{query}%"
                statement = (
                    select(User.id, User.email, User.display_name, User.created_at)
                    .where(
                        or_(
                            User.email.ilike(pattern),
                            User.display_name.ilike(pattern),
                        )
                    )
                    .order_by(User.display_name, User.email)
                    .limit(limit)
                )
                rows = await connection.execute(
                    statement,
                )
                return [ShardedUser(**row._mapping) for row in rows]

        partial = await self._all_shards(search_node)
        return merge_user_pages(partial.values(), limit)

    async def dispose(self) -> None:
        for engine in self.engines.values():
            await engine.dispose()
