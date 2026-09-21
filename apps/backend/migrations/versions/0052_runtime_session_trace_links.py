"""V3.0.0 RT-002：运行时会话 / 因果链挂接列（唯一一次 Schema 扩展）。

`loop_runs.session_id`（可空 + 索引）：Run 挂接会话，历史行 NULL 兼容。
`runtime_traces.correlation_id`（可空 + 索引）：因果链关联（RT-005 / RT-019 消费）。
两列同批建，避免两次迁移链头钉测升级。

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("loop_runs", sa.Column("session_id", sa.String(), nullable=True))
    try:
        op.create_index("ix_loop_runs_session_id", "loop_runs", ["session_id"])
    except Exception:
        pass
    op.add_column(
        "runtime_traces", sa.Column("correlation_id", sa.String(), nullable=True)
    )
    try:
        op.create_index(
            "ix_runtime_traces_correlation_id", "runtime_traces", ["correlation_id"]
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_runtime_traces_correlation_id", table_name="runtime_traces")
    except Exception:
        pass
    op.drop_column("runtime_traces", "correlation_id")
    try:
        op.drop_index("ix_loop_runs_session_id", table_name="loop_runs")
    except Exception:
        pass
    op.drop_column("loop_runs", "session_id")
