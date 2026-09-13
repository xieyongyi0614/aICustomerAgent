"""loop_runs 扩列 run_kind/profile + 终态 degraded + kind 值域 chat（AGENT-001 Run 模型）。

- run_kind：V2.1.0 统一 Run 分类（foreground_chat/autonomous_tick/event_driven），
  NULL = 既有维护类行；存量 autonomy 行回填 autonomous_tick。
- profile：Run Open 时 Profile 实例化快照（JSON）。
- status 约束追加 degraded（Gateway 熔断降级终态）。
- kind 约束追加 chat（前台 Run 行，autonomy 语义不变）。

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KIND_CONSTRAINT = "kind IN ('autonomy', 'world_maintenance', 'action_retry', 'outbox_consume', 'trigger_reconcile')"
_NEW_KIND_CONSTRAINT = "kind IN ('autonomy', 'chat', 'world_maintenance', 'action_retry', 'outbox_consume', 'trigger_reconcile')"
_OLD_STATUS_CONSTRAINT = "status IN ('running', 'done', 'aborted')"
_NEW_STATUS_CONSTRAINT = "status IN ('running', 'done', 'aborted', 'degraded')"


def upgrade() -> None:
    op.add_column("loop_runs", sa.Column("run_kind", sa.String(), nullable=True))
    op.add_column("loop_runs", sa.Column("profile", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE loop_runs SET run_kind = 'autonomous_tick' "
        "WHERE kind = 'autonomy' AND run_kind IS NULL"
    )
    with op.batch_alter_table("loop_runs") as batch:
        batch.drop_constraint("ck_loop_runs_kind", type_="check")
        batch.drop_constraint("ck_loop_runs_status", type_="check")
        batch.create_check_constraint("ck_loop_runs_kind", _NEW_KIND_CONSTRAINT)
        batch.create_check_constraint("ck_loop_runs_status", _NEW_STATUS_CONSTRAINT)


def downgrade() -> None:
    op.execute("UPDATE loop_runs SET run_kind = NULL WHERE kind <> 'chat'")
    op.execute("DELETE FROM loop_runs WHERE kind = 'chat'")
    with op.batch_alter_table("loop_runs") as batch:
        batch.drop_constraint("ck_loop_runs_kind", type_="check")
        batch.drop_constraint("ck_loop_runs_status", type_="check")
        batch.create_check_constraint("ck_loop_runs_kind", _OLD_KIND_CONSTRAINT)
        batch.create_check_constraint("ck_loop_runs_status", _OLD_STATUS_CONSTRAINT)
    op.drop_column("loop_runs", "profile")
    op.drop_column("loop_runs", "run_kind")
