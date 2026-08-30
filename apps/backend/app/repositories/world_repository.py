"""V8 world 四表仓储（persistence.md §2）。

世界是长期状态：无 TTL 删除；完结事件与旧快照的保留清理在 008/013 接入。
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import and_ as sa_and_, or_ as sa_or_
from sqlalchemy.orm import Session as _Session  # noqa: F401

from app.core.db import (
    WorldEntityRow,
    WorldEventRow,
    WorldRow,
    WorldSnapshotRow,
    SessionLocal,
)
from app.core.settings import get_settings
from app.models.world import (
    EventImportance,
    EventSource,
    EventStatus,
    ObjectStatus,
    StateSnapshot,
    World,
    WorldEnvironment,
    WorldEvent,
    WorldObject,
    WorldTimeMode,
)

logger = logging.getLogger(__name__)


def world_id_for(user_id: str) -> str:
    return f"home:{user_id}"


def _to_world(row: WorldRow) -> World:
    return World(
        world_id=row.id,
        user_id=row.user_id,
        name=row.name,
        time_mode=WorldTimeMode(row.time_mode),
        sim_time=row.sim_time,
        sim_rate=row.sim_rate,
        current_location=row.current_location,
        environment=WorldEnvironment(**(row.environment or {})),
        notes=row.notes or [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_object(row: WorldEntityRow) -> WorldObject:
    return WorldObject(
        id=row.id,
        world_id=row.world_id,
        name=row.name,
        aliases=row.aliases or [],
        category=row.category,
        location_id=row.location_id,
        state=row.state,
        quantity=row.quantity,
        properties=row.properties or {},
        status=ObjectStatus(row.status),
        last_action_at=row.last_action_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_event(row: WorldEventRow) -> WorldEvent:
    return WorldEvent(
        id=row.id,
        world_id=row.world_id,
        type=row.type,
        title=row.title,
        importance=EventImportance(row.importance),
        status=EventStatus(row.status),
        started_at=row.started_at,
        due_at=row.due_at,
        completed_at=row.completed_at,
        payload=row.payload or {},
        source=EventSource(row.source),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def ensure_world(user_id: str) -> World:
    with SessionLocal() as session:
        world_id = world_id_for(user_id)
        row = session.get(WorldRow, world_id)
        if row is None:
            now = datetime.now()
            row = WorldRow(
                id=world_id,
                user_id=user_id,
                name="家",
                time_mode=get_settings().world_time_mode,
                sim_rate=get_settings().world_sim_rate,
                current_location="home.living_room",
                environment={},
                notes=[],
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
        return _to_world(row)


def get_world(user_id: str) -> World | None:
    with SessionLocal() as session:
        row = session.get(WorldRow, world_id_for(user_id))
        return _to_world(row) if row is not None else None


def save_world(world: World) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(WorldRow, world.world_id)
        if row is None:
            return
        row.name = world.name
        row.sim_time = world.sim_time
        row.sim_rate = world.sim_rate
        row.current_location = world.current_location
        row.environment = world.environment.model_dump(mode="json", exclude_none=True)
        row.notes = world.notes
        row.updated_at = now
        session.commit()


def save_object(obj: WorldObject) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(WorldEntityRow, obj.id)
        if row is None:
            row = WorldEntityRow(
                id=obj.id,
                world_id=obj.world_id,
                created_at=obj.created_at or now,
            )
            session.add(row)
        row.name = obj.name
        row.aliases = obj.aliases
        row.category = obj.category
        row.location_id = obj.location_id
        row.state = obj.state
        row.quantity = obj.quantity
        row.properties = obj.properties
        row.status = obj.status.value
        row.last_action_at = obj.last_action_at or now
        row.updated_at = now
        session.commit()


def get_object(world_id: str, object_id: str) -> WorldObject | None:
    with SessionLocal() as session:
        row = session.get(WorldEntityRow, object_id)
        if row is None or row.world_id != world_id:
            return None
        return _to_object(row)


def list_objects(world_id: str, status: str = "active") -> list[WorldObject]:
    with SessionLocal() as session:
        rows = (
            session.query(WorldEntityRow)
            .filter(WorldEntityRow.world_id == world_id, WorldEntityRow.status == status)
            .order_by(WorldEntityRow.last_action_at.desc().nullslast())
            .all()
        )
        return [_to_object(row) for row in rows]


def list_objects_at(world_id: str, location_id: str) -> list[WorldObject]:
    with SessionLocal() as session:
        rows = (
            session.query(WorldEntityRow)
            .filter(
                WorldEntityRow.world_id == world_id,
                WorldEntityRow.location_id == location_id,
                WorldEntityRow.status == "active",
            )
            .all()
        )
        return [_to_object(row) for row in rows]


def count_active_objects(world_id: str) -> int:
    with SessionLocal() as session:
        return (
            session.query(WorldEntityRow)
            .filter(WorldEntityRow.world_id == world_id, WorldEntityRow.status == "active")
            .count()
        )


def save_event(event: WorldEvent) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(WorldEventRow, event.id)
        if row is None:
            row = WorldEventRow(
                id=event.id,
                world_id=event.world_id,
                created_at=event.created_at or now,
            )
            session.add(row)
        row.type = event.type
        row.title = event.title
        row.importance = event.importance.value
        row.status = event.status.value
        row.started_at = event.started_at
        row.due_at = event.due_at
        row.completed_at = event.completed_at
        row.payload = event.payload
        row.source = event.source.value
        row.updated_at = now
        session.commit()


def get_event(world_id: str, event_id: str) -> WorldEvent | None:
    with SessionLocal() as session:
        row = session.get(WorldEventRow, event_id)
        if row is None or row.world_id != world_id:
            return None
        return _to_event(row)


def list_events(
    world_id: str, statuses: list[str] | None = None, limit: int = 50
) -> list[WorldEvent]:
    with SessionLocal() as session:
        query = session.query(WorldEventRow).filter(WorldEventRow.world_id == world_id)
        if statuses:
            query = query.filter(WorldEventRow.status.in_(statuses))
        rows = (
            query.order_by(WorldEventRow.due_at.asc().nullslast())
            .limit(limit)
            .all()
        )
        return [_to_event(row) for row in rows]


def list_due_events(world_id: str, now: datetime) -> list[WorldEvent]:
    with SessionLocal() as session:
        rows = (
            session.query(WorldEventRow)
            .filter(
                WorldEventRow.world_id == world_id,
                WorldEventRow.status == "scheduled",
                WorldEventRow.due_at.isnot(None),
                WorldEventRow.due_at <= now,
            )
            .all()
        )
        return [_to_event(row) for row in rows]


def count_active_events(world_id: str) -> int:
    with SessionLocal() as session:
        return (
            session.query(WorldEventRow)
            .filter(
                WorldEventRow.world_id == world_id,
                WorldEventRow.status.in_(["scheduled", "active"]),
            )
            .count()
        )


def save_snapshot(snapshot: StateSnapshot) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        session.add(
            WorldSnapshotRow(
                id=snapshot.id,
                world_id=snapshot.world_id,
                label=snapshot.label,
                state=snapshot.state,
                created_at=snapshot.created_at or now,
            )
        )
        session.commit()


def list_snapshots(world_id: str, limit: int = 20) -> list[StateSnapshot]:
    with SessionLocal() as session:
        rows = (
            session.query(WorldSnapshotRow)
            .filter(WorldSnapshotRow.world_id == world_id)
            .order_by(WorldSnapshotRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            StateSnapshot(
                id=row.id,
                world_id=row.world_id,
                label=row.label,
                state=row.state or {},
                created_at=row.created_at,
            )
            for row in rows
        ]


def get_snapshot(world_id: str, snapshot_id: str) -> StateSnapshot | None:
    with SessionLocal() as session:
        row = session.get(WorldSnapshotRow, snapshot_id)
        if row is None or row.world_id != world_id:
            return None
        return StateSnapshot(
            id=row.id,
            world_id=row.world_id,
            label=row.label,
            state=row.state or {},
            created_at=row.created_at,
        )


def new_object_id(category: str) -> str:
    return f"{category}_{uuid.uuid4().hex[:8]}"


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def new_snapshot_id() -> str:
    return f"snap_{uuid.uuid4().hex[:12]}"


def list_all_worlds() -> list[World]:
    with SessionLocal() as session:
        rows = session.query(WorldRow).all()
        return [_to_world(row) for row in rows]


def prune_events_before(world_id: str, cutoff: datetime) -> int:
    with SessionLocal() as session:
        deleted = (
            session.query(WorldEventRow)
            .filter(
                WorldEventRow.world_id == world_id,
                WorldEventRow.status.in_(["completed", "cancelled", "expired"]),
                sa_or_(
                    WorldEventRow.completed_at < cutoff,
                    sa_and_(
                        WorldEventRow.completed_at.is_(None),
                        WorldEventRow.updated_at < cutoff,
                    ),
                ),
            )
            .delete()
        )
        session.commit()
        return deleted


def prune_snapshots(world_id: str, keep: int) -> int:
    with SessionLocal() as session:
        rows = (
            session.query(WorldSnapshotRow)
            .filter(WorldSnapshotRow.world_id == world_id)
            .order_by(WorldSnapshotRow.created_at.desc())
            .all()
        )
        stale = rows[keep:]
        for row in stale:
            session.delete(row)
        session.commit()
        return len(stale)
