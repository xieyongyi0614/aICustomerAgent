"""V2.0.0 MEM-001：Memory 2.0 存储与向量基座。

memories 扩列（embedding/salience/last_reinforced_at/merge_chain/source_ref/visibility，
全部可 NULL，v1 代码不可见）；新增 memory_candidates / memory_links / background_jobs
三张表；pgvector 扩展 + memories.embedding HNSW（cosine）索引。

生产仅支持 PostgreSQL（需 pgvector 扩展，缺失时 fail-fast）；
SQLite 兜底库走兼容路径：embedding 列以 JSON 模拟，仅保证迁移可跑，向量检索不启用。

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HNSW_INDEX_NAME = "idx_memories_embedding_hnsw"


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "VECTOR(768)"


def _vector_available(bind) -> bool:
    return (
        bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
        is not None
    )


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        if not _vector_available(bind):
            raise RuntimeError(
                "pgvector 扩展不可用：请使用 pgvector/pgvector 镜像或在 PostgreSQL "
                "安装 vector 扩展后重试（Memory 2.0 生产仅支持启用 pgvector 的 PostgreSQL）。"
            )
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        op.add_column("memories", sa.Column("embedding", Vector(), nullable=True))
    else:
        op.add_column("memories", sa.Column("embedding", sa.JSON(), nullable=True))

    op.add_column("memories", sa.Column("salience", sa.Float(), nullable=True))
    op.add_column(
        "memories",
        sa.Column("last_reinforced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("memories", sa.Column("merge_chain", sa.JSON(), nullable=True))
    op.add_column("memories", sa.Column("source_ref", sa.JSON(), nullable=True))
    op.add_column("memories", sa.Column("visibility", sa.String(), nullable=True))

    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="*"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("proposed_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("source_table", sa.String(), nullable=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("salience", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'promoted')",
            name="ck_memory_candidates_status",
        ),
        sa.UniqueConstraint("source_table", "source_id", name="uq_memory_candidates_source"),
    )
    op.create_index(
        "idx_memory_candidates_user_status",
        "memory_candidates",
        ["user_id", "status"],
    )

    op.create_table(
        "memory_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("related_memory_id", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "relation IN ('supersedes', 'merges', 'contradicts')",
            name="ck_memory_links_relation",
        ),
    )
    op.create_index("idx_memory_links_memory", "memory_links", ["memory_id"])

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_at", sa.DateTime(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_background_jobs_status",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_background_jobs_idempotency_key"),
    )
    op.create_index(
        "idx_background_jobs_status_run_at",
        "background_jobs",
        ["status", "run_at"],
    )

    if is_postgres:
        op.execute(
            f"CREATE INDEX {HNSW_INDEX_NAME} ON memories USING hnsw "
            "(embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX_NAME}")

    op.drop_index("idx_background_jobs_status_run_at", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_index("idx_memory_links_memory", table_name="memory_links")
    op.drop_table("memory_links")
    op.drop_index("idx_memory_candidates_user_status", table_name="memory_candidates")
    op.drop_table("memory_candidates")

    if is_postgres:
        op.drop_column("memories", "embedding")
    else:
        with op.batch_alter_table("memories") as batch:
            batch.drop_column("embedding")
    op.drop_column("memories", "visibility")
    op.drop_column("memories", "source_ref")
    op.drop_column("memories", "merge_chain")
    op.drop_column("memories", "last_reinforced_at")
    op.drop_column("memories", "salience")