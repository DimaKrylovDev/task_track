from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.telegram import send_telegram_message
from app.db.partitioning import FUTURE_MONTHS, partition_ddl, partition_name, required_months
from app.db.session import engine

LOGGER = logging.getLogger("partition-maintenance")


@dataclass(frozen=True, slots=True)
class PartitionCheckResult:
    status: str
    missing: tuple[str, ...]
    notification_sent: bool


async def existing_task_partitions(connection: AsyncConnection) -> set[str]:
    rows = await connection.execute(
        text(
            """
            SELECT child.relname
            FROM pg_inherits
            JOIN pg_class parent ON parent.oid = inhparent
            JOIN pg_class child ON child.oid = inhrelid
            JOIN pg_namespace ns ON ns.oid = parent.relnamespace
            WHERE parent.relname = 'tasks'
              AND ns.nspname = current_schema()
            """
        )
    )
    return set(rows.scalars())


async def create_missing_task_partitions(
    connection: AsyncConnection, months: tuple[date, ...] | None = None
) -> tuple[str, ...]:
    await connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"), {
        "lock_name": "task-tracker.create-task-partitions"
    })
    existing = await existing_task_partitions(connection)
    months = required_months() if months is None else months
    created: list[str] = []
    LOGGER.info("Partition job started: existing=%d required=%d", len(existing), len(months))

    for start in months:
        name = partition_name(start)
        if name in existing:
            continue
        relation_exists = await connection.scalar(text("SELECT to_regclass(:name)"), {
            "name": name
        })
        if relation_exists is not None:
            raise RuntimeError(f"Relation {name} exists but is not attached to tasks")
        # Идентификаторы берутся только из константы выше, пользовательского ввода здесь нет.
        await connection.execute(text(partition_ddl(start)))
        created.append(name)
        LOGGER.info("Created partition: %s", name)

    LOGGER.info("Partition job finished: created=%d", len(created))
    return tuple(created)


def _message(status: str, missing: tuple[str, ...]) -> str:
    checked_at = datetime.now(UTC).isoformat()
    if status == "CRITICAL":
        return (
            "Partition alert\nTable: tasks\nMissing partitions: "
            f"{', '.join(missing)}\nExpected horizon: current + {FUTURE_MONTHS} months (UTC)\n"
            f"Checked at: {checked_at}"
        )
    return (
        "Partition check OK\nTable: tasks\nAll required partitions exist.\n"
        f"Checked at: {checked_at}"
    )


def _post_webhook(url: str, message: str) -> None:
    request = Request(
        url,
        data=json.dumps({"text": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - URL задаёт администратор
        if response.status >= 300:
            raise RuntimeError(f"Alert webhook returned HTTP {response.status}")


async def _notify(message: str) -> None:
    token = settings.telegram_bot_token.get_secret_value()
    if bool(token) != bool(settings.telegram_chat_id):
        raise RuntimeError("Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    LOGGER.warning("%s", message.replace("\n", " | "))
    if token:
        await asyncio.to_thread(send_telegram_message, token, settings.telegram_chat_id, message)
    if settings.partition_alert_webhook_url:
        await asyncio.to_thread(_post_webhook, settings.partition_alert_webhook_url, message)


async def deliver_event_alerts(connection: AsyncConnection) -> int:
    """Deliver the lab SQL outbox; keep failed messages pending for the next run."""
    token = settings.telegram_bot_token.get_secret_value()
    if not token or not settings.telegram_chat_id:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for outbox delivery")
    # Совместимость со стендом, созданным до добавления Telegram-канала.
    await connection.execute(text(
        "ALTER TABLE krasova_lab3.partition_alert_outbox "
        "ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ"
    ))
    rows = await connection.execute(text(
        "SELECT id, message FROM krasova_lab3.partition_alert_outbox "
        "WHERE delivered_at IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED"
    ))
    delivered = 0
    for row in rows:
        await asyncio.to_thread(
            send_telegram_message, token, settings.telegram_chat_id, row.message
        )
        await connection.execute(text(
            "UPDATE krasova_lab3.partition_alert_outbox SET delivered_at = now() WHERE id = :id"
        ), {"id": row.id})
        delivered += 1
    return delivered


async def check_task_partitions(connection: AsyncConnection) -> PartitionCheckResult:
    await connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"), {
        "lock_name": "task-tracker.check-task-partitions"
    })
    existing = await existing_task_partitions(connection)
    expected = tuple(partition_name(start) for start in required_months())
    missing = tuple(name for name in expected if name not in existing)
    status = "CRITICAL" if missing else "OK"
    previous = (
        await connection.execute(
            text(
                """
                SELECT status, missing_partitions
                FROM task_partition_health_state
                WHERE table_name = 'tasks'
                FOR UPDATE
                """
            )
        )
    ).one_or_none()
    should_notify = (
        previous is None
        or previous.status != status
        or tuple(previous.missing_partitions) != missing
    )

    if should_notify:
        await _notify(_message(status, missing))
        await connection.execute(
            text(
                """
                INSERT INTO task_partition_health_state
                    (table_name, status, missing_partitions, changed_at)
                VALUES ('tasks', :status, :missing, now())
                ON CONFLICT (table_name) DO UPDATE
                SET status = EXCLUDED.status,
                    missing_partitions = EXCLUDED.missing_partitions,
                    changed_at = EXCLUDED.changed_at
                """
            ),
            {"status": status, "missing": list(missing)},
        )
    return PartitionCheckResult(status, missing, should_notify)


async def _run(command: str) -> int:
    if command == "test-alert":
        if not settings.telegram_bot_token.get_secret_value() or not settings.telegram_chat_id:
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        await _notify("Telegram partition alert delivery test")
        print(json.dumps({"telegram_test_sent": True}))
        return 0
    async with engine.begin() as connection:
        if command == "deliver-events":
            delivered = await deliver_event_alerts(connection)
            print(json.dumps({"delivered": delivered}))
            return 0
        if command == "create":
            created = await create_missing_task_partitions(connection)
            print(json.dumps({"created": created}, ensure_ascii=False))
            return 0
        result = await check_task_partitions(connection)
        print(json.dumps({
            "status": result.status,
            "missing": result.missing,
            "notification_sent": result.notification_sent,
        }, ensure_ascii=False))
        return 1 if result.status == "CRITICAL" else 0


async def _entrypoint(command: str) -> int:
    try:
        return await _run(command)
    finally:
        # Engine и его asyncpg-соединения закрываются в том же event loop.
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Maintain and check tasks monthly RANGE partitions"
    )
    parser.add_argument("command", choices=("create", "check", "test-alert", "deliver-events"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(_entrypoint(args.command)))


if __name__ == "__main__":
    main()
