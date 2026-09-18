from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.cli.sharding import simulation
from app.db.sharded_users import ShardedUser, merge_user_pages
from app.db.sharding import (
    ConsistentHashRouter,
    ModuloHashRouter,
    compare_routers,
    shard_distribution,
    stable_hash,
)


def keys(count: int = 10_000):
    return [uuid5(NAMESPACE_URL, f"test-user-{number}") for number in range(count)]


def test_stable_hash_is_deterministic_and_type_aware() -> None:
    assert stable_hash("123") == stable_hash("123")
    assert stable_hash("123") != stable_hash(123)


def test_modulo_router_distributes_keys_between_every_shard() -> None:
    distribution = shard_distribution(ModuloHashRouter(("s0", "s1", "s2")), keys())

    assert sum(distribution.values()) == 10_000
    assert all(3_100 < count < 3_600 for count in distribution.values())


def test_consistent_hashing_only_moves_keys_to_added_shard() -> None:
    before = ConsistentHashRouter(("s0", "s1", "s2"), virtual_nodes=128)
    after = ConsistentHashRouter(("s0", "s1", "s2", "s3"), virtual_nodes=128)
    sample = keys()

    moved = [key for key in sample if before.route(key) != after.route(key)]

    assert moved
    assert all(after.route(key) == "s3" for key in moved)
    assert 15 < compare_routers(before, after, sample).moved_percent < 35


def test_modulo_rebalances_most_keys_when_shard_is_added() -> None:
    sample = keys()
    report = compare_routers(
        ModuloHashRouter(("s0", "s1", "s2")),
        ModuloHashRouter(("s0", "s1", "s2", "s3")),
        sample,
    )

    assert report.moved_percent == pytest.approx(75, abs=2)


def test_lab_simulation_is_reproducible() -> None:
    first = simulation(1_000, virtual_nodes=32)
    second = simulation(1_000, virtual_nodes=32)

    assert first == second
    assert first["records"] == 1_000


def test_distributed_order_merge_uses_global_order_and_limit() -> None:
    created_at = datetime.now(UTC)
    candidates = [
        ShardedUser(uuid5(NAMESPACE_URL, name), f"{name}@example.com", name, created_at)
        for name in ("Zoe", "Anna", "Mike")
    ]

    result = merge_user_pages((candidates[:1], candidates[1:]), limit=2)

    assert [user.display_name for user in result] == ["Anna", "Mike"]
