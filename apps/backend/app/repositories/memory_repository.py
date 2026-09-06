import json
import uuid
from datetime import datetime
from typing import get_args

from sqlalchemy import text as sa_text

from app.core.db import Memory, SessionLocal
from app.models.memory import MemoryType, UserMemory

VALID_MEMORY_TYPES = get_args(MemoryType)


def _to_memory(row: Memory) -> UserMemory:
    return UserMemory(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        type=row.type,
        content=row.content,
        importance=row.importance,
        confidence=row.confidence,
        source=row.source,
        status=row.status,
        superseded_by=row.superseded_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_accessed_at=row.last_accessed_at,
        expires_at=row.expires_at,
    )


def create_memory(
    user_id: str,
    character_id: str,
    content: str,
    memory_type: str,
    importance: float,
    confidence: float = 0.0,
    source: str = "user_stated",
    expires_at: datetime | None = None,
) -> UserMemory:
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"非法 memory_type: {memory_type}")
    if not 0.0 <= importance <= 1.0:
        raise ValueError(f"importance 越界: {importance}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence 越界: {confidence}")
    if source not in ("user_stated", "user_derived", "ai_inferred"):
        raise ValueError(f"非法 source: {source}")
    now = datetime.now()
    with SessionLocal() as session:
        row = Memory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            content=content,
            type=memory_type,
            importance=importance,
            character_id=character_id,
            confidence=confidence,
            source=source,
            status="active",
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_memory(row)


def list_by_user(user_id: str, limit: int = 50) -> list[UserMemory]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.user_id == user_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_memory(row) for row in rows]


def list_active(
    user_id: str, character_id: str, limit: int = 20
) -> list[UserMemory]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.status == "active",
                Memory.character_id.in_([character_id, "*"]),
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_memory(row) for row in rows]


def list_active_by_types(
    user_id: str,
    character_id: str,
    types: list[str],
    limit: int = 200,
) -> list[UserMemory]:
    """按类型批量取 active 记忆（Relationship 域只读投影/审计用）。"""
    if not types:
        return []
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.status == "active",
                Memory.character_id.in_([character_id, "*"]),
                Memory.type.in_(list(types)),
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_memory(row) for row in rows]


def list_expired_active(now: datetime, limit: int = 500) -> list[UserMemory]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.status == "active",
                Memory.expires_at.isnot(None),
                Memory.expires_at < now,
            )
            .limit(limit)
            .all()
        )
        return [_to_memory(row) for row in rows]


def get_memory(memory_id: str) -> UserMemory | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        return _to_memory(row) if row else None


def get_source_refs(memory_ids: list[str]) -> dict[str, dict]:
    """批量读取 source_ref（REF-005 编排层识别 negate 信号用；只读）。"""
    if not memory_ids:
        return {}
    with SessionLocal() as session:
        rows = (
            session.query(Memory.id, Memory.source_ref)
            .filter(Memory.id.in_(memory_ids))
            .all()
        )
        return {row_id: (source_ref or {}) for row_id, source_ref in rows}


def update_memory_content(
    memory_id: str, content: str, importance: float | None = None
) -> UserMemory | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is None:
            return None
        row.content = content
        if importance is not None:
            row.importance = importance
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_memory(row)


def supersede_memory(old_id: str, new_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(Memory, old_id)
        if row is not None:
            row.status = "superseded"
            row.superseded_by = new_id
            row.updated_at = datetime.now()
            session.commit()


def invalidate_memory(memory_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is not None:
            row.status = "invalidated"
            row.updated_at = datetime.now()
            session.commit()


def touch_last_accessed(memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    now = datetime.now()
    with SessionLocal() as session:
        rows = session.query(Memory).filter(Memory.id.in_(memory_ids)).all()
        for row in rows:
            row.last_accessed_at = now
        session.commit()


def forget_memory(memory_id: str) -> None:
    delete_memory(memory_id)


def delete_memory(memory_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is not None:
            session.delete(row)
            session.commit()


def create_memory_and_supersede(
    user_id: str,
    character_id: str,
    content: str,
    memory_type: str,
    importance: float,
    confidence: float = 0.0,
    source: str = "user_stated",
    expires_at: datetime | None = None,
    superseded_id: str | None = None,
) -> UserMemory:
    """新建记忆并替代旧记忆：同一事务，避免新旧双 active。"""
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"非法 memory_type: {memory_type}")
    if not 0.0 <= importance <= 1.0:
        raise ValueError(f"importance 越界: {importance}")
    now = datetime.now()
    with SessionLocal() as session:
        row = Memory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            content=content,
            type=memory_type,
            importance=importance,
            character_id=character_id,
            confidence=confidence,
            source=source,
            status="active",
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        if superseded_id is not None:
            old = session.get(Memory, superseded_id)
            if old is not None:
                old.status = "superseded"
                old.superseded_by = row.id
                old.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_memory(row)


def list_pending_embedding(limit: int = 100) -> list[UserMemory]:
    """待回填向量的 active 记忆（embedding IS NULL），按创建时间升序。"""
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.status == "active", Memory.embedding.is_(None))
            .order_by(Memory.created_at.asc())
            .limit(limit)
            .all()
        )
        return [_to_memory(row) for row in rows]


def update_embedding(memory_id: str, vector: list[float]) -> bool:
    """条件回填单条向量：仅在 active 且 embedding 为空时写入。"""
    encoded = json.dumps(vector)
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is None or row.embedding is not None or row.status != "active":
            return False
        row.embedding = encoded
        session.commit()
        return True


def update_embeddings_batch(items: list[tuple[str, list[float]]]) -> int:
    """条件回填一批向量：单事务；已填或非 active 行跳过，幂等可重放。"""
    updated = 0
    with SessionLocal() as session:
        for memory_id, vector in items:
            row = session.get(Memory, memory_id)
            if row is None or row.embedding is not None or row.status != "active":
                continue
            row.embedding = json.dumps(vector)
            updated += 1
        session.commit()
    return updated


def search_by_vector(
    user_id: str,
    character_id: str,
    query_vector: list[float],
    limit: int = 20,
) -> list[UserMemory]:
    """pgvector 余弦近邻（<=>）召回候选；仅 active 非 hypothetical；非 PG 库返回空。"""
    with SessionLocal() as session:
        if session.bind.dialect.name != "postgresql":
            return []
        vector_literal = json.dumps(query_vector)
        result = session.execute(
            sa_text(
                "SELECT id FROM memories WHERE user_id = :user_id AND status = 'active'"
                " AND character_id IN (:character_id, '*')"
                " AND (visibility IS NULL OR visibility != 'hypothetical')"
                " AND embedding IS NOT NULL"
                " ORDER BY embedding <=> :vector LIMIT :limit"
            ),
            {
                "user_id": user_id,
                "character_id": character_id,
                "vector": vector_literal,
                "limit": limit,
            },
        )
        ids = [row[0] for row in result.fetchall()]
        if not ids:
            return []
        rows = session.query(Memory).filter(Memory.id.in_(ids)).all()
        by_id = {row.id: row for row in rows}
        return [_to_memory(by_id[memory_id]) for memory_id in ids if memory_id in by_id]
