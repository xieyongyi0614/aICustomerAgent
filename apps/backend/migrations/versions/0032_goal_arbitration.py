"""V2.0.0 AUT-004：character_goals 仲裁留痕与状态机扩展。

新增 nullable arbitration_state JSON 列（冲突对方/优先级依据/裁决时刻）；
ck_character_goals_status 重建为七值（+failed/suspended/abandoned——failed
由 AUT-003 引入）并同步 ck_decision_records_kind（+goal_lifecycle）。
downgrade 清理 P6 非遗留状态行后回退四值约束。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_CHECK = (
    "status IN ('active', 'completed', 'expired', 'cancelled',"
    " 'failed', 'suspended', 'abandoned')"
)
_KIND_CHECK = (
    "kind IN ('proactive_autonomy', 'turn_goal', 'turn_intention',"
    " 'turn_behavior', 'goal_lifecycle')"
)


def upgrade() -> None:
    op.add_column(
        "character_goals", sa.Column("arbitration_state", sa.JSON(), nullable=True)
    )
    with op.batch_alter_table("character_goals") as batch_op:
        batch_op.drop_constraint("ck_character_goals_status", type_="check")
        batch_op.create_check_constraint(
            "ck_character_goals_status", _STATUS_CHECK
        )
    with op.batch_alter_table("decision_records") as batch_op:
        batch_op.drop_constraint("ck_decision_records_kind", type_="check")
        batch_op.create_check_constraint("ck_decision_records_kind", _KIND_CHECK)


def downgrade() -> None:
    op.execute(
        "DELETE FROM character_goals WHERE status IN"
        " ('failed', 'suspended', 'abandoned')"
    )
    op.execute("DELETE FROM decision_records WHERE kind = 'goal_lifecycle'")
    with op.batch_alter_table("character_goals") as batch_op:
        batch_op.drop_constraint("ck_character_goals_status", type_="check")
        batch_op.create_check_constraint(
            "ck_character_goals_status",
            "status IN ('active', 'completed', 'expired', 'cancelled')",
        )
    with op.batch_alter_table("decision_records") as batch_op:
        batch_op.drop_constraint("ck_decision_records_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_decision_records_kind",
            "kind IN ('proactive_autonomy', 'turn_goal', 'turn_intention',"
            " 'turn_behavior')",
        )
    op.drop_column("character_goals", "arbitration_state")
