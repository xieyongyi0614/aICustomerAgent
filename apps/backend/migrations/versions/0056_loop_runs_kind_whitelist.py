"""loop_runs kind 白名单补全维护域 kind（world_simulation/action_schedule/ledger_alert/ledger_digest）。

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_KIND_CONSTRAINT = (
    "kind IN ('autonomy', 'chat', 'world_maintenance', 'world_simulation', "
    "'action_retry', 'action_schedule', 'ledger_digest', 'ledger_alert', "
    "'outbox_consume', 'trigger_reconcile')"
)
_OLD_KIND_CONSTRAINT = (
    "kind IN ('autonomy', 'chat', 'world_maintenance', 'action_retry', "
    "'outbox_consume', 'trigger_reconcile')"
)


def upgrade() -> None:
    with op.batch_alter_table("loop_runs") as batch:
        batch.drop_constraint("ck_loop_runs_kind", type_="check")
        batch.create_check_constraint("ck_loop_runs_kind", _NEW_KIND_CONSTRAINT)


def downgrade() -> None:
    op.execute(
        "DELETE FROM loop_runs WHERE kind IN "
        "('world_simulation', 'action_schedule', 'ledger_digest', 'ledger_alert')"
    )
    with op.batch_alter_table("loop_runs") as batch:
        batch.drop_constraint("ck_loop_runs_kind", type_="check")
        batch.create_check_constraint("ck_loop_runs_kind", _OLD_KIND_CONSTRAINT)
