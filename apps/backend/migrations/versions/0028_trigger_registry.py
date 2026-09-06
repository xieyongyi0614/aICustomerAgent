"""V2.0.0 LIFE-001：trigger_registry 持久化触发登记表。

替代 v1 内存 dict Trigger Registry（v1 审计问题 6：重启即丢 followup）。
状态机 pending→due→fired→done|cancelled；fired 处理滞留经 recover_stale
回 pending 重试（attempt_count + cooldown_until 防无限重试）；trigger_key
唯一防重复登记（与 v1 dedupe_key 同形）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trigger_registry",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("trigger_type", sa.String(), nullable=False),
        sa.Column("trigger_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trigger_key", name="uq_trigger_registry_key"),
        sa.CheckConstraint(
            "trigger_type IN ('conversation_inactivity', 'scheduled_followup', 'action_due')",
            name="ck_trigger_registry_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'due', 'fired', 'done', 'cancelled')",
            name="ck_trigger_registry_status",
        ),
    )
    op.create_index(
        "idx_trigger_registry_status_due_at",
        "trigger_registry",
        ["status", "due_at"],
    )
    op.create_index(
        "idx_trigger_registry_user_status",
        "trigger_registry",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_trigger_registry_user_status", table_name="trigger_registry")
    op.drop_index("idx_trigger_registry_status_due_at", table_name="trigger_registry")
    op.drop_table("trigger_registry")
