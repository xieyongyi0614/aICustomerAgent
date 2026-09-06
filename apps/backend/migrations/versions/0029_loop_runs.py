"""V2.0.0 LIFE-002：loop_runs 周期记账表。

每个 Life Loop 周期一行：kind 区分用户周期与维护步骤；steps JSON 记录
步骤/时长/skip 原因；llm_call_count/token_total/budget_state 为 LIFE-003
记账列（建表一次到位，零二次迁移）。run 状态机 running→done|aborted。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "loop_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("trigger_id", sa.String(), nullable=True),
        sa.Column("trigger_type", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("current_step", sa.String(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("llm_call_count", sa.Integer(), nullable=False),
        sa.Column("token_total", sa.Integer(), nullable=False),
        sa.Column("budget_state", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('autonomy', 'world_maintenance', 'action_retry', "
            "'outbox_consume', 'trigger_reconcile')",
            name="ck_loop_runs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'aborted')",
            name="ck_loop_runs_status",
        ),
    )
    op.create_index(
        "idx_loop_runs_status_started_at", "loop_runs", ["status", "started_at"]
    )
    op.create_index(
        "idx_loop_runs_user_started_at", "loop_runs", ["user_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_loop_runs_user_started_at", table_name="loop_runs")
    op.drop_index("idx_loop_runs_status_started_at", table_name="loop_runs")
    op.drop_table("loop_runs")
