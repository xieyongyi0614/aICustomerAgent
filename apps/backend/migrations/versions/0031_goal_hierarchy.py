"""V2.0.0 AUT-001：character_goals 层级扩展与 goal_plans 规划表。

层级 goal（short/long × personal/relationship/world）存储基座：旧行 4 列
NULL = 走 v1 路径（验收硬条件）；goal_plans 版本化 Sub-Goal 树 +
白名单完成判据（写入方 AUT-002，本迁移只建结构）。downgrade 干净。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "character_goals", sa.Column("parent_goal_id", sa.String(), nullable=True)
    )
    op.add_column("character_goals", sa.Column("layer", sa.String(), nullable=True))
    op.add_column("character_goals", sa.Column("domain", sa.String(), nullable=True))
    op.add_column(
        "character_goals", sa.Column("failure_reason", sa.String(), nullable=True)
    )
    with op.batch_alter_table("character_goals") as batch_op:
        batch_op.create_check_constraint(
            "ck_character_goals_layer",
            "layer IN ('short_term', 'long_term') OR layer IS NULL",
        )
        batch_op.create_check_constraint(
            "ck_character_goals_domain",
            "domain IN ('personal', 'relationship', 'world') OR domain IS NULL",
        )
    op.create_index(
        "idx_character_goals_parent", "character_goals", ["parent_goal_id"]
    )
    op.create_index(
        "idx_character_goals_layer_domain", "character_goals", ["layer", "domain"]
    )
    op.create_table(
        "goal_plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("sub_goals", sa.JSON(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "version", name="uq_goal_plans_goal_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'active', 'rejected', 'superseded')",
            name="ck_goal_plans_status",
        ),
    )
    op.create_index("idx_goal_plans_goal_status", "goal_plans", ["goal_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_goal_plans_goal_status", table_name="goal_plans")
    op.drop_table("goal_plans")
    with op.batch_alter_table("character_goals") as batch_op:
        batch_op.drop_index("idx_character_goals_layer_domain")
        batch_op.drop_index("idx_character_goals_parent")
        batch_op.drop_constraint("ck_character_goals_domain")
        batch_op.drop_constraint("ck_character_goals_layer")
        batch_op.drop_column("failure_reason")
        batch_op.drop_column("domain")
        batch_op.drop_column("layer")
        batch_op.drop_column("parent_goal_id")
