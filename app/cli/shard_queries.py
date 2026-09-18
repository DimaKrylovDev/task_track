from __future__ import annotations

import argparse
import asyncio
import json
from time import perf_counter
from typing import Any

from app.cli.sharding import shard_urls, user_ids
from app.db.sharded_users import ShardedUserStore, ShardQueryError
from app.db.sharding import ModuloHashRouter


async def timed[T](operation) -> tuple[T, float]:
    started = perf_counter()
    result = await operation
    return result, round((perf_counter() - started) * 1_000, 3)


async def experiment(shards: int, search: str, limit: int) -> dict[str, Any]:
    nodes = tuple(f"shard-{number}" for number in range(shards))
    router = ModuloHashRouter(nodes)
    store = ShardedUserStore(router, shard_urls(shards))
    target_id = user_ids(1)[0]
    try:
        user, single_ms = await timed(store.get(target_id))
        partial_counts, count_ms = await timed(store.counts())
        users, order_ms = await timed(store.search(search, limit))
        return {
            "single_shard": {
                "user_id": str(target_id),
                "routed_to": router.route(target_id),
                "found": user is not None,
                "milliseconds": single_ms,
            },
            "distributed_count": {
                "partial": partial_counts,
                "total": sum(partial_counts.values()),
                "milliseconds": count_ms,
            },
            "distributed_order_by_limit": {
                "query": search,
                "limit": limit,
                "returned": len(users),
                "users": [
                    {"id": str(user.id), "display_name": user.display_name}
                    for user in users
                ],
                "milliseconds": order_ms,
            },
        }
    finally:
        await store.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lab 6 distributed query experiment")
    parser.add_argument("--shards", type=int, default=3, choices=range(1, 5))
    parser.add_argument("--search", default="Lab 5 User 99")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        result = asyncio.run(experiment(args.shards, args.search, args.limit))
    except ShardQueryError as exc:
        print(
            json.dumps(
                {"error": "shard_unavailable", "failed_shards": exc.failed_shards},
                indent=2,
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
