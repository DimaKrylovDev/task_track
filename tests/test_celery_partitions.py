from app.celery_app import celery_app
from app.jobs import partitions


def test_beat_schedules_check_and_create_independently() -> None:
    schedule = celery_app.conf.beat_schedule
    check = schedule["check-task-partitions-every-five-minutes"]
    create = schedule["create-task-partitions-nightly"]
    assert check["task"] == "partitions.check"
    assert check["schedule"].minute == set(range(0, 60, 5))
    assert create["task"] == "partitions.create"
    assert create["schedule"].hour == {1}
    assert create["schedule"].minute == {0}
    assert celery_app.conf.timezone == "Europe/Moscow"


def test_check_task_returns_critical_without_running_create(monkeypatch) -> None:
    calls = []

    async def execute(command):
        calls.append(command)
        return {"status": "CRITICAL", "missing": ["tasks_hash_p3"], "notification_sent": True}

    monkeypatch.setattr(partitions, "_execute", execute)
    result = partitions.check_partitions.apply().get()
    assert result["status"] == "CRITICAL"
    assert calls == ["check"]


def test_create_task_only_runs_creation(monkeypatch) -> None:
    calls = []

    async def execute(command):
        calls.append(command)
        return {"created": []}

    monkeypatch.setattr(partitions, "_execute", execute)
    assert partitions.create_partitions.apply().get() == {"created": []}
    assert calls == ["create"]
