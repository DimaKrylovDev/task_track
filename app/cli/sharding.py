from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterator
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.config import settings
from app.db.sharded_users import ShardedUser, ShardedUserStore
from app.db.sharding import (
    ConsistentHashRouter,
    ModuloHashRouter,
    ShardRouter,
    compare_routers,
    shard_distribution,
)


def user_ids(records: int) -> list[UUID]:
    return [uuid5(NAMESPACE_URL, f"krasova-lab5-user-{number}") for number in range(records)]


def users_in_batches(ids: list[UUID], batch_size: int) -> Iterator[list[ShardedUser]]:
    for start in range(0, len(ids), batch_size):
        yield [
            ShardedUser(
                id=user_id,
                email=f"lab5.user.{start + offset}@example.com",
                display_name=f"Lab 5 User {start + offset}",
            )
            for offset, user_id in enumerate(ids[start : start + batch_size])
        ]


def nodes(count: int) -> tuple[str, ...]:
    if not 1 <= count <= 4:
        raise ValueError("This lab stand supports from one to four shards")
    return tuple(f"shard-{number}" for number in range(count))


def build_router(strategy: str, count: int, virtual_nodes: int) -> ShardRouter:
    shard_nodes = nodes(count)
    if strategy == "modulo":
        return ModuloHashRouter(shard_nodes)
    return ConsistentHashRouter(shard_nodes, virtual_nodes=virtual_nodes)


def simulation(records: int, virtual_nodes: int) -> dict[str, object]:
    keys = user_ids(records)
    modulo_3 = ModuloHashRouter(nodes(3))
    modulo_4 = ModuloHashRouter(nodes(4))
    ring_3 = ConsistentHashRouter(nodes(3), virtual_nodes=virtual_nodes)
    ring_4 = ConsistentHashRouter(nodes(4), virtual_nodes=virtual_nodes)
    modulo_movement = compare_routers(modulo_3, modulo_4, keys)
    ring_movement = compare_routers(ring_3, ring_4, keys)
    return {
        "records": records,
        "virtual_nodes_per_shard": virtual_nodes,
        "modulo_distribution_3": shard_distribution(modulo_3, keys),
        "consistent_distribution_3": shard_distribution(ring_3, keys),
        "modulo_3_to_4": {
            "moved": modulo_movement.moved,
            "unchanged": modulo_movement.unchanged,
            "moved_percent": round(modulo_movement.moved_percent, 3),
        },
        "consistent_3_to_4": {
            "moved": ring_movement.moved,
            "unchanged": ring_movement.unchanged,
            "moved_percent": round(ring_movement.moved_percent, 3),
        },
    }


def shard_urls(count: int) -> dict[str, str]:
    if len(settings.shard_database_urls) < count:
        raise ValueError(f"SHARD_DATABASE_URLS must contain at least {count} URLs")
    return dict(zip(nodes(count), settings.shard_database_urls[:count], strict=True))


async def seed(
    strategy: str,
    shard_count: int,
    records: int,
    virtual_nodes: int,
    batch_size: int,
    reset: bool,
) -> dict[str, int]:
    router = build_router(strategy, shard_count, virtual_nodes)
    store = ShardedUserStore(router, shard_urls(shard_count))
    try:
        await store.initialize()
        if reset:
            await store.clear()
        ids = user_ids(records)
        for batch in users_in_batches(ids, batch_size):
            await store.add_many(batch)
        return await store.counts()
    finally:
        await store.dispose()


async def count(shard_count: int) -> dict[str, int]:
    store = ShardedUserStore(ModuloHashRouter(nodes(shard_count)), shard_urls(shard_count))
    try:
        await store.initialize()
        return await store.counts()
    finally:
        await store.dispose()


async def run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "simulate":
        return simulation(args.records, args.virtual_nodes)
    if args.command == "count":
        return {"database_counts": await count(args.shards)}
    counts = await seed(
        args.strategy,
        args.shards,
        args.records,
        args.virtual_nodes,
        args.batch_size,
        args.reset,
    )
    result: dict[str, object] = {"database_counts": counts}
    if args.shards == 3:
        result["experiment_3_to_4"] = simulation(args.records, args.virtual_nodes)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Lab 5 PostgreSQL sharding experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate_parser = subparsers.add_parser("simulate")
    simulate_parser.add_argument("--records", type=int, default=100_000)
    simulate_parser.add_argument("--virtual-nodes", type=int, default=128)

    count_parser = subparsers.add_parser("count")
    count_parser.add_argument("--shards", type=int, default=3)

    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("--strategy", choices=("modulo", "consistent"), default="modulo")
    seed_parser.add_argument("--shards", type=int, default=3)
    seed_parser.add_argument("--records", type=int, default=100_000)
    seed_parser.add_argument("--virtual-nodes", type=int, default=128)
    seed_parser.add_argument("--batch-size", type=int, default=5_000)
    seed_parser.add_argument("--reset", action="store_true")

    args = parser.parse_args()
    if getattr(args, "records", 1) < 1:
        parser.error("--records must be positive")
    if getattr(args, "virtual_nodes", 1) < 1:
        parser.error("--virtual-nodes must be positive")
    if getattr(args, "batch_size", 1) < 1:
        parser.error("--batch-size must be positive")
    print(json.dumps(asyncio.run(run(args)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
