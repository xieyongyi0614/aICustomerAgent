"""loop_runs 扩 kind 值域：纳入新增维护步 world_simulation / action_schedule。

两处遗漏同源——新增维护步时未同步扩本约束，写入即触发
`IntegrityError: CHECK constraint failed: ck_loop_runs_kind`：

- `world_simulation`：WS-003 时间推进与模拟维护步新增，此前由
  `world_simulation_enabled and time_advance_enabled` 门控掩盖；V2.3.0 开关
  固化常开后门控归并为 `world_enabled`，维护步首次真正执行并暴露该缺陷。
- `action_schedule`：V2.6.1 REF-004 到期调度执行，REF-005 裁决挂在
  `life_loop` 维护步上；当前由 v26 双闸默认 off 掩盖，固化后引爆。

值域同步见 `app/core/db.py` 的 `LoopRunRow.__table_args__`。

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-18

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KIND_CONSTRAINT = (
    "kind IN ('autonomy', 'chat', 'world_maintenance', 'action_retry', "
    "'outbox_consume', 'trigger_reconcile')"
)
_NEW_KIND_CONSTRAINT = (
    "kind IN ('autonomy', 'chat', 'world_maintenance', 'world_simulation', "
    "'action_retry', 'action_schedule', 'outbox_consume', 'trigger_reconcile')"
)


def upgrade() -> None:
    with op.batch_alter_table("loop_runs") as batch:
        batch.drop_constraint("ck_loop_runs_kind", type_="check")
        batch.create_check_constraint("ck_loop_runs_kind", _NEW_KIND_CONSTRAINT)


def downgrade() -> None:
    op.execute(
        "DELETE FROM loop_runs WHERE kind IN ('world_simulation', 'action_schedule')"
    )
    with op.batch_alter_table("loop_runs") as batch:
        batch.drop_constraint("ck_loop_runs_kind", type_="check")
        batch.create_check_constraint("ck_loop_runs_kind", _OLD_KIND_CONSTRAINT)
