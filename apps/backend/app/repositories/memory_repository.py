import uuid
from datetime import datetime

from app.core.db import Memory, SessionLocal
from app.models.memory import MemoryType, UserMemory

VALID_MEMORY_TYPES = ("preference", "fact", "goal", "experience", "relationship")


def _to_user_memory(row: Memory) -> UserMemory:
    return UserMemory(
        id=row.id,
        user_id=row.user_id,
        memory=row.memory,
        memory_type=row.memory_type,
        importance=row.importance,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_memory(
    user_id: str, memory: str, memory_type: MemoryType, importance: float
) -> UserMemory:
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"非法 memory_type: {memory_type}")
    if not 0.0 <= importance <= 1.0:
        raise ValueError(f"importance 越界: {importance}")
    now = datetime.now()
    with SessionLocal() as session:
        row = Memory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            memory=memory,
            memory_type=memory_type,
            importance=importance,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_user_memory(row)


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


def get_memory(memory_id: str) -> UserMemory | None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        return _to_user_memory(row) if row else None


def delete_memory(memory_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is not None:
            session.delete(row)
            session.commit()


def exists_similar(memory: str, threshold: float = 1.0) -> bool:
    with SessionLocal() as session:
        rows = session.query(Memory).all()
        for row in rows:
            if memory == row.memory or memory in row.memory or row.memory in memory:
                return True
        return False
