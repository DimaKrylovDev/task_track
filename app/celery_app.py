from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "task_tracker", broker=settings.celery_broker_url, include=["app.jobs.partitions"]
)
celery_app.conf.update(
    timezone="Europe/Moscow",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_default_queue="partition-maintenance",
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "check-task-partitions-every-five-minutes": {
            "task": "partitions.check",
            "schedule": crontab(minute="*/5"),
            "options": {"expires": 300},
        },
        "create-task-partitions-nightly": {
            "task": "partitions.create",
            "schedule": crontab(hour=1, minute=0),
        },
    },
)
