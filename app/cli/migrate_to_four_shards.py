from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.cli.sharding import build_router, shard_urls
from app.db.models import User
from app.db.sharded_users import ShardedUserStore
from app.db.sharding import ShardRouter


async def migrate_batch(
    store: ShardedUserStore,
    old_router: ShardRouter,
    new_router: ShardRouter,
    source: str,
    rows: list[dict[str, Any]],
    dry_run: bool,
) -> int:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        user_id = row["id"]
        if old_router.route(user_id) != source:
            continue

        target = new_router.route(user_id)
        if target != source:
            grouped.setdefault(target, []).append(row)

    if dry_run or not grouped:
        return sum(len(users) for users in grouped.values())

    insert_statement = insert(User)
    statement = insert_statement.on_conflict_do_update(
        index_elements=[User.id],
        set_={
            "email": insert_statement.excluded.email,
            "display_name": insert_statement.excluded.display_name,
            "password_hash": insert_statement.excluded.password_hash,
            "created_at": insert_statement.excluded.created_at,
            "updated_at": insert_statement.excluded.updated_at,
        },
    )
    for target, users in grouped.items():
        async with store.engines[target].begin() as connection:
            await connection.execute(statement, users)

    moved_ids = [row["id"] for users in grouped.values() for row in users]
    async with store.engines[source].begin() as connection:
        await connection.execute(delete(User).where(User.id.in_(moved_ids)))

    return len(moved_ids)


async def migrate(
    strategy: str,
    virtual_nodes: int,
    batch_size: int,
    dry_run: bool,
) -> dict[str, object]:
    old_router = build_router(strategy, count=3, virtual_nodes=virtual_nodes)
    new_router = build_router(strategy, count=4, virtual_nodes=virtual_nodes)
    store = ShardedUserStore(new_router, shard_urls(4))
    scanned = 0
    moved = 0

    try:
        await store.initialize()
        for source in old_router.nodes:
            cursor: UUID | None = None
            while True:
                statement = select(User.__table__).order_by(User.id).limit(batch_size)
                if cursor is not None:
                    statement = statement.where(User.id > cursor)

                async with store.engines[source].connect() as connection:
                    result = await connection.execute(statement)
                    rows = [dict(row) for row in result.mappings()]

                if not rows:
                    break

                scanned += len(rows)
                cursor = rows[-1]["id"]
                moved += await migrate_batch(
                    store,
                    old_router,
                    new_router,
                    source,
                    rows,
                    dry_run,
                )

        result: dict[str, object] = {
            "strategy": strategy,
            "from_shards": 3,
            "to_shards": 4,
            "scanned": scanned,
            "moved": moved,
            "dry_run": dry_run,
        }
        if not dry_run:
            result["database_counts"] = await store.counts()
        return result
    finally:
        await store.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move users from a three-shard layout to a four-shard layout"
    )
    parser.add_argument(
        "--strategy",
        choices=("modulo", "consistent"),
        default="modulo",
        help="must match the strategy used to seed the three shards",
    )
    parser.add_argument("--virtual-nodes", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.virtual_nodes < 1:
        parser.error("--virtual-nodes must be positive")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    result = asyncio.run(
        migrate(
            strategy=args.strategy,
            virtual_nodes=args.virtual_nodes,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
