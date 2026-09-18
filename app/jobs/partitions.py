import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.celery_app import celery_app
from app.cli.partitions import check_task_partitions, create_missing_task_partitions
from app.core.config import settings

LOGGER = logging.getLogger(__name__)


async def _execute(command: str) -> dict:
    # Каждый запуск Celery имеет свой event loop и engine, без соединений FastAPI.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            if command == "create":
                created = await create_missing_task_partitions(connection)
                result = {"created": list(created)}
            else:
                checked = await check_task_partitions(connection)
                result = {
                    "status": checked.status,
                    "missing": list(checked.missing),
                    "notification_sent": checked.notification_sent,
                }
        LOGGER.info("Partition %s finished: %s", command, result)
        return result
    finally:
        await engine.dispose()


@celery_app.task(
    name="partitions.check",
    autoretry_for=(RuntimeError, SQLAlchemyError),
    retry_backoff=30,
    retry_backoff_max=120,
    retry_kwargs={"max_retries": 3},
)
def check_partitions() -> dict:
    # CRITICAL — результат проверки, а не ошибка доставки: бесконечного retry нет.
    return asyncio.run(_execute("check"))


@celery_app.task(
    name="partitions.create",
    autoretry_for=(RuntimeError, SQLAlchemyError),
    retry_backoff=30,
    retry_backoff_max=120,
    retry_kwargs={"max_retries": 3},
)
def create_partitions() -> dict:
    return asyncio.run(_execute("create"))
