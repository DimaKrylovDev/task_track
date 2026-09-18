from datetime import UTC, date, datetime

FUTURE_MONTHS = 3


def month_start(value: date | datetime) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Partition dates must be timezone-aware")
        value = value.astimezone(UTC).date()
    return value.replace(day=1)


def add_months(value: date, count: int) -> date:
    index = value.year * 12 + value.month - 1 + count
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def required_months(today: date | datetime | None = None) -> tuple[date, ...]:
    start = month_start(today if today is not None else datetime.now(UTC))
    return tuple(add_months(start, offset) for offset in range(FUTURE_MONTHS + 1))


def partition_name(start: date) -> str:
    return f"tasks_{start:%Y_%m}"


def partition_ddl(start: date, parent: str = "tasks") -> str:
    # start и end формируются из date, parent — только внутренний идентификатор.
    end = add_months(start, 1)
    return (
        f"CREATE TABLE {partition_name(start)} PARTITION OF {parent} "
        f"FOR VALUES FROM ('{start.isoformat()} 00:00:00+00') "
        f"TO ('{end.isoformat()} 00:00:00+00')"
    )
