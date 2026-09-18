"""Partition tasks by its UUID primary key.

Revision ID: 0002_partition_tasks_by_hash
Revises: 0001_initial
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_partition_tasks_by_hash"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_INDEX_COLUMNS = {
    "ix_tasks_project_id": "project_id",
    "ix_tasks_assignee_id": "assignee_id",
    "ix_tasks_title": "title",
    "ix_tasks_status": "status",
    "ix_tasks_priority": "priority",
    "ix_tasks_due_at": "due_at",
}


def _drop_referencing_foreign_keys() -> None:
    op.drop_constraint("fk_task_tags_task_id_tasks", "task_tags", type_="foreignkey")
    op.drop_constraint("fk_comments_task_id_tasks", "comments", type_="foreignkey")


def _create_referencing_foreign_keys() -> None:
    op.create_foreign_key(
        "fk_task_tags_task_id_tasks",
        "task_tags",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_comments_task_id_tasks",
        "comments",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )


def _create_tasks_table(partitioned: bool) -> None:
    suffix = " PARTITION BY HASH (id)" if partitioned else ""
    op.execute(
        f"""
        CREATE TABLE tasks (
            id UUID NOT NULL,
            project_id UUID NOT NULL,
            creator_id UUID NOT NULL,
            assignee_id UUID,
            title VARCHAR(240) NOT NULL,
            description TEXT,
            status VARCHAR(20) NOT NULL,
            priority VARCHAR(20) NOT NULL,
            due_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            CONSTRAINT pk_tasks PRIMARY KEY (id),
            CONSTRAINT ck_tasks_ck_tasks_status
                CHECK (status IN ('BACKLOG', 'TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED')),
            CONSTRAINT ck_tasks_ck_tasks_priority
                CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            CONSTRAINT fk_tasks_project_id_projects FOREIGN KEY (project_id)
                REFERENCES projects(id) ON DELETE CASCADE,
            CONSTRAINT fk_tasks_creator_id_users FOREIGN KEY (creator_id)
                REFERENCES users(id) ON DELETE RESTRICT,
            CONSTRAINT fk_tasks_assignee_id_users FOREIGN KEY (assignee_id)
                REFERENCES users(id) ON DELETE SET NULL
        ){suffix}
        """
    )


def _create_task_indexes() -> None:
    for name, column in TASK_INDEX_COLUMNS.items():
        op.create_index(name, "tasks", [column])
    op.execute("CREATE INDEX ix_tasks_created_at_desc ON tasks (created_at DESC)")


def _rename_old_task_objects(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} RENAME CONSTRAINT pk_tasks TO pk_{table_name}")
    for index_name in (*TASK_INDEX_COLUMNS, "ix_tasks_created_at_desc"):
        op.execute(f"ALTER INDEX {index_name} RENAME TO {index_name}_old")


def upgrade() -> None:
    _drop_referencing_foreign_keys()
    op.rename_table("tasks", "tasks_before_partitioning")
    _rename_old_task_objects("tasks_before_partitioning")

    _create_tasks_table(partitioned=True)
    for remainder in range(4):
        op.execute(
            f"CREATE TABLE tasks_hash_p{remainder} PARTITION OF tasks "
            f"FOR VALUES WITH (MODULUS 4, REMAINDER {remainder})"
        )
    _create_task_indexes()
    op.execute("INSERT INTO tasks SELECT * FROM tasks_before_partitioning")
    op.drop_table("tasks_before_partitioning")
    _create_referencing_foreign_keys()

    op.execute(
        """
        CREATE TABLE task_partition_health_state (
            table_name TEXT PRIMARY KEY,
            status VARCHAR(16) NOT NULL CHECK (status IN ('OK', 'CRITICAL')),
            missing_partitions TEXT[] NOT NULL DEFAULT '{}',
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.drop_table("task_partition_health_state")
    _drop_referencing_foreign_keys()
    op.rename_table("tasks", "tasks_partitioned_old")
    _rename_old_task_objects("tasks_partitioned_old")

    _create_tasks_table(partitioned=False)
    _create_task_indexes()
    op.execute("INSERT INTO tasks SELECT * FROM tasks_partitioned_old")
    op.drop_table("tasks_partitioned_old")
    _create_referencing_foreign_keys()
