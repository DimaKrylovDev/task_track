"""Move tasks from HASH(id) to monthly RANGE(created_at), preserving references."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.db.partitioning import add_months, month_start, partition_ddl, required_months

revision = "0003_tasks_monthly_range"
down_revision = "0002_partition_tasks_by_hash"
branch_labels = None
depends_on = None


def _drop_incoming() -> None:
    for table in ("comments", "task_tags"):
        op.drop_constraint(f"fk_{table}_task_id_tasks", table, type_="foreignkey")


def _restore_constraints(composite: bool) -> None:
    for column, destination, ondelete in (
        ("project_id", "projects", "CASCADE"),
        ("creator_id", "users", "RESTRICT"),
        ("assignee_id", "users", "SET NULL"),
    ):
        op.create_foreign_key(
            f"fk_tasks_{column}_{destination}", "tasks", destination,
            [column], ["id"], ondelete=ondelete,
        )
    for table in ("comments", "task_tags"):
        op.create_foreign_key(
            f"fk_{table}_task_id_tasks", table, "tasks",
            ["task_id", "task_created_at"] if composite else ["task_id"],
            ["id", "created_at"] if composite else ["id"], ondelete="CASCADE",
        )
    for column in ("project_id", "assignee_id", "title", "status", "priority", "due_at"):
        op.create_index(f"ix_tasks_{column}", "tasks", [column])
    op.execute("CREATE INDEX ix_tasks_created_at_desc ON tasks (created_at DESC)")


def upgrade() -> None:
    # Блокируем запись на время backfill и копирования, чтобы не терять новые строки.
    op.execute("LOCK TABLE tasks, comments, task_tags IN ACCESS EXCLUSIVE MODE")
    _drop_incoming()
    for table in ("comments", "task_tags"):
        op.add_column(table, sa.Column("task_created_at", sa.DateTime(timezone=True)))
        op.execute(
            f"UPDATE {table} SET task_created_at = tasks.created_at "
            f"FROM tasks WHERE {table}.task_id = tasks.id"
        )
        op.alter_column(table, "task_created_at", nullable=False)
    op.drop_constraint("pk_task_tags", "task_tags", type_="primary")
    op.create_primary_key("pk_task_tags", "task_tags", ["task_id", "task_created_at", "tag_id"])

    op.execute(
        "CREATE TABLE tasks_range (LIKE tasks INCLUDING DEFAULTS INCLUDING CONSTRAINTS) "
        "PARTITION BY RANGE (created_at)"
    )
    op.execute("ALTER TABLE tasks_range ADD CONSTRAINT pk_tasks_range PRIMARY KEY(id, created_at)")
    connection = op.get_bind()
    minimum, maximum = connection.execute(sa.text(
        "SELECT min(created_at), max(created_at) FROM tasks"
    )).one()
    now = datetime.now(UTC)
    first = min(month_start(minimum or now), month_start(now))
    last = max(month_start(maximum or now), required_months(now)[-1])
    start = first
    while start <= last:
        op.execute(partition_ddl(start, parent="tasks_range"))
        start = add_months(start, 1)
    op.execute("INSERT INTO tasks_range SELECT * FROM tasks")
    op.drop_table("tasks")
    op.rename_table("tasks_range", "tasks")
    op.execute("ALTER TABLE tasks RENAME CONSTRAINT pk_tasks_range TO pk_tasks")
    _restore_constraints(composite=True)
    op.execute("DELETE FROM task_partition_health_state WHERE table_name = 'tasks'")


def downgrade() -> None:
    op.execute("LOCK TABLE tasks, comments, task_tags IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS(SELECT id FROM tasks GROUP BY id HAVING count(*) > 1)"
    )):
        raise RuntimeError("Cannot downgrade: duplicate task UUIDs exist across monthly partitions")
    _drop_incoming()
    op.execute(
        "CREATE TABLE tasks_hash (LIKE tasks INCLUDING DEFAULTS INCLUDING CONSTRAINTS) "
        "PARTITION BY HASH (id)"
    )
    op.execute("ALTER TABLE tasks_hash ADD CONSTRAINT pk_tasks_hash PRIMARY KEY(id)")
    for remainder in range(4):
        op.execute(
            f"CREATE TABLE tasks_hash_p{remainder} PARTITION OF tasks_hash "
            f"FOR VALUES WITH (MODULUS 4, REMAINDER {remainder})"
        )
    op.execute("INSERT INTO tasks_hash SELECT * FROM tasks")
    op.drop_table("tasks")
    op.rename_table("tasks_hash", "tasks")
    op.execute("ALTER TABLE tasks RENAME CONSTRAINT pk_tasks_hash TO pk_tasks")
    op.drop_constraint("pk_task_tags", "task_tags", type_="primary")
    for table in ("comments", "task_tags"):
        op.drop_column(table, "task_created_at")
    op.create_primary_key("pk_task_tags", "task_tags", ["task_id", "tag_id"])
    _restore_constraints(composite=False)
    op.execute("DELETE FROM task_partition_health_state WHERE table_name = 'tasks'")
