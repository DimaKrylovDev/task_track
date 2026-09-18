from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

ShardKey = str | int | UUID | bytes


def stable_hash(value: ShardKey) -> int:
    """Return a process-independent 256-bit hash for a shard key.

    Python's built-in ``hash(str)`` is salted for every process, so it cannot be
    used by a distributed router.  A type prefix also prevents, for example,
    integer ``1`` and string ``"1"`` from silently becoming the same key.
    """

    if isinstance(value, UUID):
        payload = b"uuid:" + value.bytes
    elif isinstance(value, bytes):
        payload = b"bytes:" + value
    elif isinstance(value, int):
        payload = f"int:{value}".encode()
    else:
        payload = f"str:{value}".encode()
    return int.from_bytes(sha256(payload).digest(), byteorder="big")


class ShardRouter(Protocol):
    nodes: tuple[str, ...]

    def route(self, key: ShardKey) -> str: ...


class ModuloHashRouter:
    """Route a key using stable_hash(key) % number_of_nodes."""

    def __init__(self, nodes: Sequence[str]) -> None:
        if not nodes:
            raise ValueError("At least one shard is required")
        if len(set(nodes)) != len(nodes):
            raise ValueError("Shard names must be unique")
        self.nodes = tuple(nodes)

    def route(self, key: ShardKey) -> str:
        return self.nodes[stable_hash(key) % len(self.nodes)]


class ConsistentHashRouter:
    """A deterministic hash ring with virtual nodes."""

    def __init__(self, nodes: Sequence[str], virtual_nodes: int = 128) -> None:
        if not nodes:
            raise ValueError("At least one shard is required")
        if len(set(nodes)) != len(nodes):
            raise ValueError("Shard names must be unique")
        if virtual_nodes < 1:
            raise ValueError("virtual_nodes must be positive")

        self.nodes = tuple(nodes)
        self.virtual_nodes = virtual_nodes
        ring = sorted(
            (stable_hash(f"virtual-node:{node}:{replica}"), node)
            for node in self.nodes
            for replica in range(virtual_nodes)
        )
        self._ring = tuple(ring)
        self._points = tuple(point for point, _ in ring)

    def route(self, key: ShardKey) -> str:
        position = bisect_left(self._points, stable_hash(key))
        if position == len(self._ring):
            position = 0
        return self._ring[position][1]


@dataclass(frozen=True, slots=True)
class MovementReport:
    total: int
    moved: int

    @property
    def unchanged(self) -> int:
        return self.total - self.moved

    @property
    def moved_percent(self) -> float:
        return self.moved * 100 / self.total if self.total else 0.0


def shard_distribution(router: ShardRouter, keys: Iterable[ShardKey]) -> dict[str, int]:
    result = dict.fromkeys(router.nodes, 0)
    for key in keys:
        result[router.route(key)] += 1
    return result


def compare_routers(
    before: ShardRouter, after: ShardRouter, keys: Iterable[ShardKey]
) -> MovementReport:
    total = 0
    moved = 0
    for key in keys:
        total += 1
        moved += before.route(key) != after.route(key)
    return MovementReport(total=total, moved=moved)
