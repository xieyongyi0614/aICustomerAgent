"""AGENT-005 Evolution：development_changes 扩展承载 personality 审计 +
Evolution Ledger 只读投影（仓储层查询 evolution.ledger()，覆盖 personality/
goal/relationship/memory 四源；跨 SQLite/PG 方言安全，故不建 SQL 视图）。

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "development_changes", sa.Column("personality_state_id", sa.String(), nullable=True)
    )
    with op.batch_alter_table("development_changes") as batch:
        batch.alter_column(
            "development_state_id", existing_type=sa.String(), nullable=True
        )
        batch.create_check_constraint(
            "ck_development_changes_subject",
            "development_state_id IS NOT NULL OR personality_state_id IS NOT NULL",
        )
    with op.batch_alter_table("development_changes") as batch:
        batch.drop_constraint("ck_development_changes_reason", type_="check")
        batch.create_check_constraint(
            "ck_development_changes_reason",
            "reason IN ('compiled', 'arbitrated', 'arbitrated_lost',"
            " 'rolled_back', 'retired', 'replayed', 'personality')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM development_changes WHERE reason = 'personality'")
    with op.batch_alter_table("development_changes") as batch:
        batch.drop_constraint("ck_development_changes_subject", type_="check")
        batch.drop_constraint("ck_development_changes_reason", type_="check")
        batch.create_check_constraint(
            "ck_development_changes_reason",
            "reason IN ('compiled', 'arbitrated', 'arbitrated_lost',"
            " 'rolled_back', 'retired', 'replayed')",
        )
    op.drop_column("development_changes", "personality_state_id")
