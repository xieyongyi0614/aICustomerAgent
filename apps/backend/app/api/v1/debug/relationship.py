"""关系域调试端点：状态 / 时间线 / 手动回滚（快照锚定 + 事件重放）。"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core import timeutil
from app.api.v1.auth import require_user
from app.api.v1.deps import debug_surface_gate
from app.engines import relationship_evolution
from app.engines.relationship_evolution import distance_index
from app.models.relationship import RelationshipState
from app.repositories import (
    memory_repository,
    relationship_conflict_repository,
    relationship_event_repository,
    relationship_milestone_repository,
    relationship_repository,
    relationship_snapshot_repository,
)

logger = logging.getLogger(__name__)


relationship_router = APIRouter(
    dependencies=[Depends(debug_surface_gate), Depends(require_user)], tags=["debug"]
)


@relationship_router.get("/debug/relationship/state")
def get_relationship_state(user_id: str):
    from datetime import datetime

    state = relationship_repository.get_relationship(user_id)
    unlocks = relationship_milestone_repository.list_unlocks(user_id)
    now = timeutil.now()
    distance = distance_index(state, now)
    return {
        "user_id": user_id,
        "state": state.model_dump(mode="json"),
        "unlocks": list(unlocks),
        "derived": {
            "distance_index": round(distance, 4),
        },
    }


@relationship_router.get("/debug/relationship/timeline")
def get_relationship_timeline(user_id: str, limit: int = 50):
    limit_clamped = max(1, min(limit, 200))
    events = relationship_event_repository.list_events(user_id, limit=limit_clamped)
    milestones = relationship_milestone_repository.list_milestones(user_id)[:limit_clamped]
    conflicts = relationship_conflict_repository.list_conflicts(user_id, limit=limit_clamped)
    snapshots = relationship_snapshot_repository.list_snapshots(user_id, limit=limit_clamped)

    narrative_rows = memory_repository.list_active_by_types(
        user_id,
        "asuna",
        ["relationship_fact", "milestone_event"],
        limit=500,
    )
    source_refs = memory_repository.get_source_refs([m.id for m in narrative_rows])
    narrative_by_source: dict[tuple[str, str], list[str]] = {}
    for row in narrative_rows:
        ref = source_refs.get(row.id) or {}
        table = ref.get("table")
        target_id = ref.get("id")
        if table and target_id:
            narrative_by_source.setdefault((table, target_id), []).append(row.id)

    merged: list[dict] = []
    for e in events:
        merged.append(
            {
                "kind": "event",
                "at": e.created_at.isoformat(),
                "type": e.type,
                "magnitude": e.magnitude,
                "source": e.source,
                "cause": e.cause,
                "impact": e.impact.model_dump(mode="json"),
                "id": e.id,
                "narrative_memory_ids": narrative_by_source.get(
                    ("relationship_events", e.id), []
                ),
            }
        )
    for m in milestones:
        merged.append(
            {
                "kind": "milestone",
                "at": m.created_at.isoformat(),
                "key": m.milestone_key,
                "period_key": m.period_key,
                "title": m.title,
                "unlocks": list(m.unlocks),
                "bonus": m.applied_bonus.model_dump(mode="json"),
                "id": m.id,
                "narrative_memory_ids": narrative_by_source.get(
                    ("relationship_milestones", m.id), []
                ),
            }
        )
    for c in conflicts:
        merged.append(
            {
                "kind": "conflict",
                "at": c.started_at.isoformat(),
                "status": c.status,
                "resolution": c.resolution,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                "id": c.id,
            }
        )
    for s in snapshots:
        merged.append(
            {
                "kind": "snapshot",
                "at": s.created_at.isoformat(),
                "version": s.version,
                "stage": s.stage,
                "conflict_status": s.conflict_status,
                "trigger": s.trigger,
                "dimensions": s.dimensions,
                "id": s.id,
            }
        )
    merged.sort(key=lambda r: r["at"], reverse=True)
    return {"user_id": user_id, "items": merged[:limit_clamped]}


@relationship_router.post("/debug/relationship/rollback")
def rollback_relationship(user_id: str, target_version: int):
    from datetime import datetime


    earliest = relationship_snapshot_repository.get_earliest_version(user_id)
    if earliest is None:
        raise HTTPException(status_code=404, detail="无可用关键帧，无法回滚")
    if target_version < earliest:
        raise HTTPException(
            status_code=400,
            detail=f"target_version 早于最早关键帧 {earliest}",
        )
    current = relationship_repository.get_relationship(user_id)
    now = timeutil.now()
    try:
        relationship_snapshot_repository.create_snapshot(
            user_id,
            current.version,
            current,
            trigger="manual_pre_rollback",
            now=now,
        )
    except Exception:
        logger.exception("回滚前快照创建失败：%s", user_id)
    anchor = relationship_snapshot_repository.get_latest_before(user_id, target_version)
    if anchor is None:
        raise HTTPException(status_code=404, detail="无法定位 ≤ target_version 的关键帧")
    base_state = RelationshipState(
        intimacy=anchor.dimensions.get("intimacy", current.intimacy),
        trust=anchor.dimensions.get("trust", current.trust),
        familiarity=anchor.dimensions.get("familiarity", current.familiarity),
        respect=anchor.dimensions.get("respect", current.respect),
        comfort=anchor.dimensions.get("comfort", current.comfort),
        tension=anchor.dimensions.get("tension", current.tension),
        stage=anchor.stage,
        conflict_status=anchor.conflict_status,
        neglect_active=current.neglect_active,
        last_interaction_at=current.last_interaction_at,
        version=anchor.version,
        updated_at=now,
    )
    all_events = relationship_event_repository.list_events(user_id, limit=2000)
    anchor_time = anchor.created_at
    replayable = [e for e in all_events if e.created_at > anchor_time]
    rebuilt = relationship_evolution.replay(base_state, replayable)
    final = rebuilt.model_copy(
        update={"version": max(current.version, rebuilt.version) + 1, "updated_at": now}
    )
    persisted = relationship_repository.upsert_relationship(user_id, final)
    relationship_snapshot_repository.create_snapshot(
        user_id,
        final.version,
        final,
        trigger="manual",
        now=now,
    )
    return {
        "user_id": user_id,
        "target_version": target_version,
        "anchor_version": anchor.version,
        "replayed_events": len(replayable),
        "final_state": persisted.model_dump(mode="json"),
    }
