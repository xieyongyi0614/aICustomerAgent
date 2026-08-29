import uuid
from datetime import datetime

from app.core.db import Memory, SessionLocal
from app.models.memory import (
    LEGACY_MEMORY_TYPE_MAP,
    MemoryType,
    MemoryTypeV4,
    UserMemory,
    UserMemoryV4,
)

VALID_MEMORY_TYPES = ("preference", "fact", "goal", "experience", "relationship")
VALID_MEMORY_TYPES_V4 = (
    "user_preference",
    "user_fact",
    "important_event",
    "relationship_event",
)

V4_TO_LEGACY_TYPE_MAP = {
    "user_preference": "preference",
    "user_fact": "fact",
    "important_event": "experience",
    "relationship_event": "relationship",
}


def _normalize_type(memory_type: str) -> MemoryTypeV4:
    if memory_type in VALID_MEMORY_TYPES_V4:
        return memory_type
    if memory_type in LEGACY_MEMORY_TYPE_MAP:
        return LEGACY_MEMORY_TYPE_MAP[memory_type]
    raise ValueError(f"非法 memory_type: {memory_type}")


def _to_user_memory(row: Memory) -> UserMemory:
    legacy_type = V4_TO_LEGACY_TYPE_MAP.get(row.memory_type, row.memory_type)
    return UserMemory(
        id=row.id,
        user_id=row.user_id,
        memory=row.memory,
        memory_type=legacy_type,
        importance=row.importance,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_user_memory_v4(row: Memory) -> UserMemoryV4:
    return UserMemoryV4(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        type=row.memory_type,
        content=row.memory,
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
    memory: str,
    memory_type: MemoryType,
    importance: float,
    character_id: str = "asuna",
    confidence: float = 0.0,
    source: str = "user_stated",
    expires_at: datetime | None = None,
) -> UserMemory:
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"非法 memory_type: {memory_type}")
    if not 0.0 <= importance <= 1.0:
        raise ValueError(f"importance 越界: {importance}")
    stored_type = LEGACY_MEMORY_TYPE_MAP[memory_type]
    now = datetime.now()
    with SessionLocal() as session:
        row = Memory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            memory=memory,
            memory_type=stored_type,
            importance=importance,
            character_id=character_id,
            confidence=confidence,
            source=source,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_user_memory(row)


def create_memory_v4(
    user_id: str,
    character_id: str,
    content: str,
    memory_type: str,
    importance: float,
    confidence: float = 0.0,
    source: str = "user_stated",
    expires_at: datetime | None = None,
) -> UserMemoryV4:
    normalized = _normalize_type(memory_type)
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
            memory=content,
            memory_type=normalized,
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
        return _to_user_memory_v4(row)


def list_by_user(user_id: str, limit: int = 50) -> list[UserMemory]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.user_id == user_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_user_memory(row) for row in rows]


def list_active_v4(
    user_id: str, character_id: str, limit: int = 20
) -> list[UserMemoryV4]:
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
        return [_to_user_memory_v4(row) for row in rows]


def get_memory(memory_id: str) -> UserMemory | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        return _to_user_memory(row) if row else None


def get_memory_v4(memory_id: str) -> UserMemoryV4 | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        return _to_user_memory_v4(row) if row else None


def update_memory_content(
    memory_id: str, content: str, importance: float | None = None
) -> UserMemoryV4 | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is None:
            return None
        row.memory = content
        if importance is not None:
            row.importance = importance
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_user_memory_v4(row)


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


def exists_similar(user_id: str, memory: str, threshold: float = 1.0) -> bool:
    with SessionLocal() as session:
        rows = session.query(Memory).filter(Memory.user_id == user_id).all()
        for row in rows:
            if memory == row.memory or memory in row.memory or row.memory in memory:
                return True
        return False
