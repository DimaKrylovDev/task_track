from datetime import UTC, date, datetime, timedelta, timezone

from app.cli.partitions import _message
from app.db.partitioning import (
    add_months,
    month_start,
    partition_ddl,
    partition_name,
    required_months,
)


def test_expected_monthly_partitions_cross_year_boundary() -> None:
    assert tuple(map(partition_name, required_months(date(2026, 11, 15)))) == (
        "tasks_2026_11", "tasks_2026_12", "tasks_2027_01", "tasks_2027_02",
    )


def test_month_boundaries_are_utc_and_handle_leap_year() -> None:
    assert add_months(date(2028, 2, 1), 1) == date(2028, 3, 1)
    local = datetime(2026, 10, 1, 1, tzinfo=timezone(timedelta(hours=3)))
    assert month_start(local) == date(2026, 9, 1)
    assert month_start(datetime(2026, 10, 1, tzinfo=UTC)) == date(2026, 10, 1)
    ddl = partition_ddl(date(2026, 12, 1))
    assert "2026-12-01 00:00:00+00" in ddl
    assert "2027-01-01 00:00:00+00" in ddl


def test_critical_message_lists_missing_partitions() -> None:
    message = _message("CRITICAL", ("tasks_2026_12",))
    assert "Partition alert" in message
    assert "tasks_2026_12" in message
    assert "current + 3 months" in message


def test_recovery_message_is_explicit() -> None:
    message = _message("OK", ())
    assert "Partition check OK" in message
    assert "All required partitions exist" in message
