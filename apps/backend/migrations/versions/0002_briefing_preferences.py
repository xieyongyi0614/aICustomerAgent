"""0002：简报偏好表（API-008 偏好落库 + 天气定位城市）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "briefing_preferences",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("morning_at", sa.String(), nullable=True),
        sa.Column("evening_at", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("briefing_preferences")
