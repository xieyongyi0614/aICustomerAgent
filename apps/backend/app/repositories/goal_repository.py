import uuid
from datetime import datetime

from app.core.db import GoalPlanRow, GoalRow, SessionLocal
from app.models.goal import (
    DOMAIN_VALUES,
    GOAL_DESCRIPTION_MAX_LENGTH,
    GoalPlanRecord,
    GoalRecord,
    GoalSeed,
    HIERARCHICAL_TYPE_MAP,
    LAYER_VALUES,
    SubGoalSpec,
    goal_transitions,
)

_HIERARCHICAL_HORIZON = "persistent"


def _to_record(row: GoalRow) -> GoalRecord:
    return GoalRecord(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        type=row.type,
        description=row.description,
        priority=row.priority,
        status=row.status,
        horizon=row.horizon,
        source=row.source,
        created_turn=row.created_turn,
        expires_at_turn=row.expires_at_turn,
        created_at=row.created_at,
        updated_at=row.updated_at,
        parent_goal_id=row.parent_goal_id,
        layer=row.layer,
        domain=row.domain,
        failure_reason=row.failure_reason,
        arbitration_state=row.arbitration_state,
    )


def _to_row(record: GoalRecord) -> GoalRow:
    return GoalRow(
        id=record.id,
        user_id=record.user_id,
        character_id=record.character_id,
        type=record.type,
        description=record.description,
        priority=record.priority,
        status=record.status,
        horizon=record.horizon,
        source=record.source,
        created_turn=record.created_turn,
        expires_at_turn=record.expires_at_turn,
        created_at=record.created_at,
        updated_at=record.updated_at,
        parent_goal_id=record.parent_goal_id,
        layer=record.layer,
        domain=record.domain,
        failure_reason=record.failure_reason,
        arbitration_state=record.arbitration_state,
    )


def _to_plan_record(row: GoalPlanRow) -> GoalPlanRecord:
    return GoalPlanRecord(
        id=row.id,
        goal_id=row.goal_id,
        version=row.version,
        status=row.status,
        sub_goals=[SubGoalSpec.model_validate(item) for item in row.sub_goals or []],
        rejection_reason=row.rejection_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def seed_goals(
    user_id: str, seeds: list[GoalSeed], character_id: str = "asuna"
) -> int:
    now = datetime.now()
    with SessionLocal() as session:
        existing = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.character_id == character_id,
                GoalRow.status == "active",
                GoalRow.horizon == "persistent",
            )
            .all()
        )
        existing_keys = {(row.type, row.description) for row in existing}
        created = 0
        for seed in seeds:
            if (seed.type, seed.description) in existing_keys:
                continue
            session.add(
                GoalRow(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    character_id=character_id,
                    type=seed.type,
                    description=seed.description,
                    priority=seed.priority,
                    status="active",
                    horizon="persistent",
                    source="definition",
                    created_turn=0,
                    expires_at_turn=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        session.commit()
        return created


def list_active(user_id: str, character_id: str = "asuna") -> list[GoalRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.character_id == character_id,
                GoalRow.status == "active",
            )
            .order_by(GoalRow.created_at.asc(), GoalRow.id.asc())
            .all()
        )
        return [_to_record(row) for row in rows]


def get_goal(goal_id: str) -> GoalRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        return _to_record(row) if row is not None else None


def create_goal(record: GoalRecord) -> GoalRecord:
    with SessionLocal() as session:
        row = _to_row(record)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_record(row)


def finish_goal(
    goal_id: str, status: str, failure_reason: str | None = None
) -> GoalRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        if row is None:
            return None
        if row.status != "active":
            return _to_record(row)
        if status not in goal_transitions(row.layer, row.status):
            raise ValueError(f"非法状态转换：{row.status} → {status}")
        row.status = status
        if failure_reason is not None:
            row.failure_reason = failure_reason
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_record(row)


def complete_goal(goal_id: str) -> GoalRecord | None:
    return finish_goal(goal_id, "completed")


def expire_goal(goal_id: str) -> GoalRecord | None:
    return finish_goal(goal_id, "expired")


def cancel_goal(goal_id: str) -> GoalRecord | None:
    return finish_goal(goal_id, "cancelled")


def fail_goal(goal_id: str, failure_reason: str) -> GoalRecord | None:
    return finish_goal(goal_id, "failed", failure_reason=failure_reason)


def reactivate_goal(goal_id: str) -> GoalRecord | None:
    """failed→active（失败后单次重规划成功；AUT-004 状态机的 failed→active 边）。"""
    with SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        if row is None or row.status != "failed":
            return _to_record(row) if row is not None else None
        if "active" not in goal_transitions(row.layer, row.status):
            raise ValueError(f"非法状态转换：{row.status} → active")
        row.status = "active"
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_record(row)


def set_status(
    goal_id: str,
    target: str,
    arbitration_state: dict | None = None,
) -> GoalRecord | None:
    """状态变更唯一入口（层级行）：转换表守卫 + 仲裁留痕原子写入。"""
    with SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        if row is None:
            return None
        if target == row.status:
            return _to_record(row)
        if target not in goal_transitions(row.layer, row.status):
            raise ValueError(f"非法状态转换：{row.status} → {target}")
        row.status = target
        if arbitration_state is not None:
            row.arbitration_state = arbitration_state
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_record(row)


def list_top_level_layered(
    user_id: str, statuses: tuple[str, ...] = ("active",)
) -> list[GoalRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.layer.isnot(None),
                GoalRow.parent_goal_id.is_(None),
                GoalRow.status.in_(statuses),
            )
            .order_by(GoalRow.created_at.asc(), GoalRow.id.asc())
            .all()
        )
        return [_to_record(row) for row in rows]


def list_children_by_status(
    parent_goal_id: str, statuses: tuple[str, ...]
) -> list[GoalRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(
                GoalRow.parent_goal_id == parent_goal_id,
                GoalRow.status.in_(statuses),
            )
            .all()
        )
        return [_to_record(row) for row in rows]


def update_plan_progress(plan_id: str, sub_goals: list[SubGoalSpec]) -> GoalPlanRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalPlanRow, plan_id)
        if row is None:
            return None
        row.sub_goals = [item.model_dump(mode="json") for item in sub_goals]
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_plan_record(row)


def create_hierarchical_goal(
    user_id: str,
    layer: str,
    domain: str,
    description: str,
    priority: int,
    character_id: str = "asuna",
    parent_id: str | None = None,
    horizon: str | None = None,
    source: str = "policy",
) -> GoalRecord:
    if layer not in LAYER_VALUES:
        raise ValueError(f"非法 layer：{layer!r}")
    if domain not in DOMAIN_VALUES:
        raise ValueError(f"非法 domain：{domain!r}")
    if len(description) > GOAL_DESCRIPTION_MAX_LENGTH:
        raise ValueError("描述超长")
    resolved_horizon = _HIERARCHICAL_HORIZON
    if layer == "short_term" and horizon == "current":
        resolved_horizon = "current"
    with SessionLocal() as session:
        if parent_id is not None:
            parent = session.get(GoalRow, parent_id)
            if parent is None:
                raise ValueError("父目标不存在")
            if parent.layer is None:
                raise ValueError("v1 目标不可作父级")
        now = datetime.now()
        row = GoalRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            character_id=character_id,
            type=HIERARCHICAL_TYPE_MAP[domain],
            description=description,
            priority=priority,
            status="active",
            horizon=resolved_horizon,
            source=source,
            created_turn=0,
            expires_at_turn=None,
            created_at=now,
            updated_at=now,
            parent_goal_id=parent_id,
            layer=layer,
            domain=domain,
            failure_reason=None,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_record(row)


def list_children(goal_id: str) -> list[GoalRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(GoalRow.parent_goal_id == goal_id)
            .order_by(GoalRow.created_at.asc(), GoalRow.id.asc())
            .all()
        )
        return [_to_record(row) for row in rows]


def list_tree(user_id: str, root_goal_id: str) -> list[dict]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.layer.isnot(None),
            )
            .order_by(GoalRow.created_at.asc(), GoalRow.id.asc())
            .all()
        )
        records = [_to_record(row) for row in rows]
    roots: list[dict] = []
    by_parent: dict[str, list[GoalRecord]] = {}
    for record in records:
        by_parent.setdefault(record.parent_goal_id or "", []).append(record)
    root = next((r for r in records if r.id == root_goal_id), None)
    if root is None:
        return roots

    def _node(record: GoalRecord) -> dict:
        children = by_parent.get(record.id, [])
        return {
            "goal": record,
            "children": [_node(child) for child in children],
        }

    roots.append(_node(root))
    return roots


def list_layered_active(
    user_id: str,
    layer: str | None = None,
    domain: str | None = None,
    character_id: str = "asuna",
) -> list[GoalRecord]:
    with SessionLocal() as session:
        query = session.query(GoalRow).filter(
            GoalRow.user_id == user_id,
            GoalRow.character_id == character_id,
            GoalRow.status == "active",
            GoalRow.layer.isnot(None),
        )
        if layer is not None:
            query = query.filter(GoalRow.layer == layer)
        if domain is not None:
            query = query.filter(GoalRow.domain == domain)
        rows = query.order_by(GoalRow.created_at.asc(), GoalRow.id.asc()).all()
        return [_to_record(row) for row in rows]


def list_top_level_layered_active(user_id: str) -> list[GoalRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.status == "active",
                GoalRow.layer.isnot(None),
                GoalRow.parent_goal_id.is_(None),
            )
            .order_by(GoalRow.created_at.asc(), GoalRow.id.asc())
            .all()
        )
        return [_to_record(row) for row in rows]


def create_plan(record: GoalPlanRecord) -> GoalPlanRecord:
    with SessionLocal() as session:
        row = GoalPlanRow(
            id=record.id,
            goal_id=record.goal_id,
            version=record.version,
            status=record.status,
            sub_goals=[item.model_dump(mode="json") for item in record.sub_goals],
            rejection_reason=record.rejection_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_plan_record(row)


def get_plan(plan_id: str) -> GoalPlanRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalPlanRow, plan_id)
        return _to_plan_record(row) if row is not None else None


def list_plans(goal_id: str) -> list[GoalPlanRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalPlanRow)
            .filter(GoalPlanRow.goal_id == goal_id)
            .order_by(GoalPlanRow.version.desc())
            .all()
        )
        return [_to_plan_record(row) for row in rows]


def get_latest_plan(goal_id: str) -> GoalPlanRecord | None:
    plans = list_plans(goal_id)
    return plans[0] if plans else None


def count_plans(goal_id: str) -> int:
    with SessionLocal() as session:
        return (
            session.query(GoalPlanRow)
            .filter(GoalPlanRow.goal_id == goal_id)
            .count()
        )


def set_plan_status(plan_id: str, status: str) -> GoalPlanRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalPlanRow, plan_id)
        if row is None:
            return None
        row.status = status
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_plan_record(row)


def set_plan_rejection(plan_id: str, reason: str) -> GoalPlanRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalPlanRow, plan_id)
        if row is None:
            return None
        row.status = "rejected"
        row.rejection_reason = reason
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_plan_record(row)


def list_active_plans(user_id: str) -> list[tuple[GoalRecord, GoalPlanRecord]]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalPlanRow, GoalRow)
            .join(GoalRow, GoalRow.id == GoalPlanRow.goal_id)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.status == "active",
                GoalPlanRow.status == "active",
            )
            .order_by(GoalPlanRow.updated_at.asc(), GoalPlanRow.id.asc())
            .all()
        )
        return [(_to_record(goal_row), _to_plan_record(plan_row)) for plan_row, goal_row in rows]
