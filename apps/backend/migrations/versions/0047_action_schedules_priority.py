"""TASK-002 V2.6.0 Action Persistence：action_schedules 新表 + action_records.priority 加列 + source 五值放宽。

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_SOURCES = "('conversation', 'autonomy', 'cancel')"
TARGET_SOURCES = "('conversation', 'autonomy', 'cancel', 'plan', 'event_driven')"


def _rebuild_source_check(target_sources: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_action_records_source", "action_records", type_="check")
        op.create_check_constraint(
            "ck_action_records_source",
            "action_records",
            f"source IN {target_sources}",
        )
        return
    _sqlite_rebuild_action_records(target_sources)


_ACTION_RECORDS_COLUMNS = (
    ("id", "VARCHAR NOT NULL"),
    ("user_id", "VARCHAR NOT NULL"),
    ("character_id", "VARCHAR NOT NULL DEFAULT 'asuna'"),
    ("session_id", "VARCHAR"),
    ("source", "VARCHAR NOT NULL DEFAULT 'conversation'"),
    ("action_type", "VARCHAR NOT NULL"),
    ("intent", "JSON NOT NULL"),
    ("goal_id", "VARCHAR"),
    ("target_record_id", "VARCHAR"),
    ("dedupe_key", "VARCHAR NOT NULL DEFAULT ''"),
    ("params", "JSON NOT NULL"),
    ("status", "VARCHAR NOT NULL DEFAULT 'created'"),
    ("gate_reason", "VARCHAR"),
    ("steps", "JSON NOT NULL"),
    ("result", "JSON"),
    ("attempt", "INTEGER NOT NULL DEFAULT 1"),
    ("priority", "INTEGER NOT NULL DEFAULT 100"),
    ("next_retry_at", "DATETIME"),
    ("scheduled_at", "DATETIME"),
    ("created_at", "DATETIME NOT NULL"),
    ("updated_at", "DATETIME NOT NULL"),
    ("executed_at", "DATETIME"),
)

_CARRY_OVER_INDEXES = (
    ("idx_action_records_user_status", "user_id, status", False),
    ("idx_action_records_user_dedupe", "user_id, dedupe_key", False),
    ("ix_action_records_user_id", "user_id", True),
)


def _sqlite_rebuild_action_records(source_check: str) -> None:
    bind = op.get_bind()
    column_ddl = ", ".join(f"{name} {ddl}" for name, ddl in _ACTION_RECORDS_COLUMNS)
    create_table = (
        f"CREATE TABLE action_records_new ({column_ddl}, "
        f"PRIMARY KEY (id), "
        f"CONSTRAINT ck_action_records_status "
        f"CHECK (status IN ('created', 'planned', 'executing', 'succeeded', 'failed', 'cancelled')), "
        f"CONSTRAINT ck_action_records_source CHECK (source IN {source_check}))"
    )
    target_names = ", ".join(name for name, _ in _ACTION_RECORDS_COLUMNS)
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    bind.exec_driver_sql("ALTER TABLE action_records RENAME TO action_records_old")
    bind.exec_driver_sql(create_table)
    bind.exec_driver_sql(
        f"INSERT INTO action_records_new ({target_names}) "
        f"SELECT {target_names} FROM action_records_old"
    )
    bind.exec_driver_sql("DROP TABLE action_records_old")
    bind.exec_driver_sql("ALTER TABLE action_records_new RENAME TO action_records")
    for name, columns, unique in _CARRY_OVER_INDEXES:
        prefix = "CREATE UNIQUE INDEX" if unique else "CREATE INDEX"
        bind.exec_driver_sql(f"{prefix} {name} ON action_records ({columns})")
    bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    op.add_column(
        "action_records",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
    )
    _rebuild_source_check(TARGET_SOURCES)
    op.create_table(
        "action_schedules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column("when_type", sa.String(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="scheduled"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", name="uq_action_schedules_action"),
        sa.CheckConstraint(
            "when_type IN ('immediate', 'delay', 'cron')",
            name="ck_action_schedules_when_type",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'due', 'executed', 'cancelled')",
            name="ck_action_schedules_status",
        ),
    )
    op.create_index(
        "idx_action_schedules_due",
        "action_schedules",
        ["status", "scheduled_at", "priority"],
    )


def downgrade() -> None:
    op.drop_index("idx_action_schedules_due", table_name="action_schedules")
    op.drop_table("action_schedules")
    _rebuild_source_check(LEGACY_SOURCES)
    op.drop_column("action_records", "priority")
