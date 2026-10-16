"""记忆域模型：长期记忆、候选记忆与记忆关联。"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import DEFAULT_LAYER
from app.core.db.base import Base, UtcDateTime, VectorType


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    layer: Mapped[str] = mapped_column(String(16), nullable=False, default=DEFAULT_LAYER)
    """通道层（`layer_for_type(type)`）：episodic = 时间线经历；semantic = 跨事件抽象。

    Python 侧默认 `semantic` 保证测试与直写路径不炸；**不带 `server_default`**——迁移撤默认后
    「漏设 layer」的写入显式失败（fail-closed）。写入路径必须显式赋值。
    """
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="*", server_default="*"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="ai_inferred", server_default="ai_inferred"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    embedding: Mapped[object | None] = mapped_column(VectorType, nullable=True)
    salience: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_reinforced_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    last_decayed_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    forgotten_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    merge_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('user_preference', 'user_fact', 'experience',"
            " 'relationship_fact', 'commitment', 'milestone_event',"
            " 'behavior_pattern')",
            name="ck_memories_type",
        ),
        CheckConstraint(
            "layer IN ('episodic', 'semantic')",
            name="ck_memories_layer",
        ),
        Index("idx_memories_user", "user_id"),
        Index(
            "idx_memories_user_character_status",
            "user_id",
            "character_id",
            "status",
        ),
        Index("idx_memories_user_layer_status", "user_id", "layer", "status"),
    )


class MemoryCandidateRow(Base):
    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="*", server_default="*"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_type: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_table: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    salience: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'promoted')",
            name="ck_memory_candidates_status",
        ),
        UniqueConstraint("source_table", "source_id", name="uq_memory_candidates_source"),
        Index("idx_memory_candidates_user_status", "user_id", "status"),
    )


class MemoryLinkRow(Base):
    __tablename__ = "memory_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(String, nullable=False)
    related_memory_id: Mapped[str] = mapped_column(String, nullable=False)
    relation: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "relation IN ('supersedes', 'merges', 'contradicts')",
            name="ck_memory_links_relation",
        ),
        Index("idx_memory_links_memory", "memory_id"),
    )
