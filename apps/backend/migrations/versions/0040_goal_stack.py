"""goals 扩列 origin（AGENT-003 Goal Stack）：来源可解释（既有供给标签 +
commitment/user/evolution）；layer 值域扩展 medium（重建 ck_character_goals_layer）。

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("character_goals", sa.Column("origin", sa.String(), nullable=True))
    with op.batch_alter_table("character_goals") as batch:
        batch.drop_constraint("ck_character_goals_layer", type_="check")
        batch.create_check_constraint(
            "ck_character_goals_layer",
            "layer IN ('short_term', 'medium', 'long_term') OR layer IS NULL",
        )


def downgrade() -> None:
    op.execute("UPDATE character_goals SET layer = NULL WHERE layer = 'medium'")
    with op.batch_alter_table("character_goals") as batch:
        batch.drop_constraint("ck_character_goals_layer", type_="check")
        batch.create_check_constraint(
            "ck_character_goals_layer",
            "layer IN ('short_term', 'long_term') OR layer IS NULL",
        )
    op.drop_column("character_goals", "origin")
