"""V2.0.0 LIFE-004：outbox_events 跨域投递一致性表。

Action 成功 → 与 action_records 终态同事务写入（幂等键 = action_id）→
消费器幂等消费（world 效果经既有引擎函数落库 + applied_ops 进度标记）
→ pending→consumed CAS；失败指数退避重试 max5 → failed 死信。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False, server_default="action_result"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency"),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'failed')",
            name="ck_outbox_events_status",
        ),
    )
    op.create_index(
        "idx_outbox_events_status_next_retry",
        "outbox_events",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_outbox_events_status_next_retry", table_name="outbox_events"
    )
    op.drop_table("outbox_events")
