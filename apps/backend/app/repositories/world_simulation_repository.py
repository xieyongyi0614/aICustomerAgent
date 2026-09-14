"""V2.3.0 世界模拟仓储：daily_plans / user_situations 两表与时间推进锚点。"""

import logging
import uuid
from datetime import date, datetime

from sqlalchemy import select, update

from app.core.db import (
    DailyPlanRow,
    SessionLocal,
    UserSituationRow,
    WorldEventRow,
    WorldRow,
)
from app.models.world_simulation import (
    DailyPlan,
    DailyPlanStatus,
    DailyPlanVariability,
    SituationDimension,
    SituationSource,
    SituationStatus,
    UserSituation,
)

OPEN_PLAN_STATUSES = (DailyPlanStatus.PLANNED, DailyPlanStatus.ACTIVE)

logger = logging.getLogger(__name__)

DAY_CYCLE_OBSERVATION_KEY = "day_cycle_observation"


def new_plan_id() -> str:
    return f"plan_{uuid.uuid4().hex[:12]}"


def new_situation_id() -> str:
    return f"sit_{uuid.uuid4().hex[:12]}"


def _to_plan(row: DailyPlanRow) -> DailyPlan:
    return DailyPlan(
        id=row.id,
        user_id=row.user_id,
        plan_date=row.plan_date,
        seq=row.seq,
        part_of_day=row.part_of_day,
        start_minutes=row.start_minutes,
        end_minutes=row.end_minutes,
        activity=row.activity,
        location_id=row.location_id,
        variability_source=DailyPlanVariability(row.variability_source),
        status=DailyPlanStatus(row.status),
        routine_version=row.routine_version,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_situation(row: UserSituationRow) -> UserSituation:
    return UserSituation(
        id=row.id,
        user_id=row.user_id,
        dimension=SituationDimension(row.dimension),
        summary=row.summary,
        intensity=row.intensity,
        status=SituationStatus(row.status),
        source=SituationSource(row.source),
        evidence=row.evidence or {},
        detected_at=row.detected_at,
        valid_until=row.valid_until,
        updated_at=row.updated_at,
    )


def save_plan(plan: DailyPlan) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(DailyPlanRow, plan.id)
        if row is None:
            row = DailyPlanRow(
                id=plan.id,
                user_id=plan.user_id,
                created_at=plan.created_at or now,
            )
            session.add(row)
        row.plan_date = plan.plan_date
        row.seq = plan.seq
        row.part_of_day = plan.part_of_day
        row.start_minutes = plan.start_minutes
        row.end_minutes = plan.end_minutes
        row.activity = plan.activity
        row.location_id = plan.location_id
        row.variability_source = plan.variability_source.value
        row.status = plan.status.value
        row.routine_version = plan.routine_version
        row.note = plan.note
        row.updated_at = now
        session.commit()


def replace_day_plans(plans: list[DailyPlan]) -> int:
    """单事务写入当日新计划块：先 supersede 旧 OPEN 行，再整批插入。

    与逐块 save_plan 语义一致（保留 SUPERSEDED 历史行作为审计轨迹），
    但合并为一次事务：既避免 N 次 commit，也消除"旧计划已 supersede +
    新计划只写了一半"的中间态。
    """
    if not plans:
        return 0
    user_id = plans[0].user_id
    plan_date = plans[0].plan_date
    now = datetime.now()
    with SessionLocal() as session:
        session.execute(
            update(DailyPlanRow)
            .where(
                DailyPlanRow.user_id == user_id,
                DailyPlanRow.plan_date == plan_date,
                DailyPlanRow.status.in_([s.value for s in OPEN_PLAN_STATUSES]),
            )
            .values(status=DailyPlanStatus.SUPERSEDED.value, updated_at=now)
        )
        for plan in plans:
            session.add(
                DailyPlanRow(
                    id=plan.id,
                    user_id=plan.user_id,
                    plan_date=plan.plan_date,
                    seq=plan.seq,
                    part_of_day=plan.part_of_day,
                    start_minutes=plan.start_minutes,
                    end_minutes=plan.end_minutes,
                    activity=plan.activity,
                    location_id=plan.location_id,
                    variability_source=plan.variability_source.value,
                    status=plan.status.value,
                    routine_version=plan.routine_version,
                    note=plan.note,
                    created_at=plan.created_at or now,
                    updated_at=now,
                )
            )
        session.commit()
        return len(plans)


def supersede_open_plans(user_id: str, plan_date: date) -> int:
    with SessionLocal() as session:
        result = session.execute(
            update(DailyPlanRow)
            .where(
                DailyPlanRow.user_id == user_id,
                DailyPlanRow.plan_date == plan_date,
                DailyPlanRow.status.in_([s.value for s in OPEN_PLAN_STATUSES]),
            )
            .values(status=DailyPlanStatus.SUPERSEDED.value, updated_at=datetime.now())
        )
        session.commit()
        return int(result.rowcount or 0)


def get_day_plans(
    user_id: str,
    plan_date: date,
    statuses: tuple[DailyPlanStatus, ...] | None = None,
) -> list[DailyPlan]:
    with SessionLocal() as session:
        stmt = (
            select(DailyPlanRow)
            .where(DailyPlanRow.user_id == user_id, DailyPlanRow.plan_date == plan_date)
            .order_by(DailyPlanRow.seq)
        )
        if statuses is not None:
            stmt = stmt.where(DailyPlanRow.status.in_([s.value for s in statuses]))
        rows = session.scalars(stmt).all()
        return [_to_plan(row) for row in rows]


def has_open_plans(user_id: str, plan_date: date) -> bool:
    return bool(get_day_plans(user_id, plan_date, OPEN_PLAN_STATUSES))


def get_plan(user_id: str, plan_id: str) -> DailyPlan | None:
    with SessionLocal() as session:
        row = session.get(DailyPlanRow, plan_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_plan(row)


def prune_plans_before(user_id: str, cutoff: date) -> int:
    with SessionLocal() as session:
        result = session.execute(
            DailyPlanRow.__table__.delete()
            .where(DailyPlanRow.user_id == user_id)
            .where(DailyPlanRow.plan_date < cutoff)
        )
        session.commit()
        return int(result.rowcount or 0)


def save_situation(situation: UserSituation) -> None:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(UserSituationRow, situation.id)
        if row is None:
            row = UserSituationRow(
                id=situation.id,
                user_id=situation.user_id,
                detected_at=situation.detected_at or now,
            )
            session.add(row)
        row.dimension = situation.dimension.value
        row.summary = situation.summary
        row.intensity = situation.intensity
        row.status = situation.status.value
        row.source = situation.source.value
        row.evidence = situation.evidence
        row.valid_until = situation.valid_until
        row.updated_at = now
        session.commit()


def get_situation(user_id: str, situation_id: str) -> UserSituation | None:
    with SessionLocal() as session:
        row = session.get(UserSituationRow, situation_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_situation(row)


def list_situations(
    user_id: str,
    statuses: tuple[SituationStatus, ...] | None = None,
) -> list[UserSituation]:
    with SessionLocal() as session:
        stmt = (
            select(UserSituationRow)
            .where(UserSituationRow.user_id == user_id)
            .order_by(UserSituationRow.detected_at.desc())
        )
        if statuses is not None:
            stmt = stmt.where(UserSituationRow.status.in_([s.value for s in statuses]))
        rows = session.scalars(stmt).all()
        return [_to_situation(row) for row in rows]


def get_active_situation(user_id: str, dimension: SituationDimension) -> UserSituation | None:
    with SessionLocal() as session:
        row = session.scalars(
            select(UserSituationRow)
            .where(
                UserSituationRow.user_id == user_id,
                UserSituationRow.dimension == dimension.value,
                UserSituationRow.status == SituationStatus.ACTIVE.value,
            )
            .order_by(UserSituationRow.detected_at.desc())
            .limit(1)
        ).first()
        return _to_situation(row) if row is not None else None


def expire_stale_situations(user_id: str, now: datetime) -> list[UserSituation]:
    expired: list[UserSituation] = []
    with SessionLocal() as session:
        rows = session.scalars(
            select(UserSituationRow).where(
                UserSituationRow.user_id == user_id,
                UserSituationRow.status == SituationStatus.ACTIVE.value,
                UserSituationRow.valid_until.is_not(None),
                UserSituationRow.valid_until < now,
            )
        ).all()
        for row in rows:
            row.status = SituationStatus.EXPIRED.value
            row.updated_at = now
            expired.append(_to_situation(row))
        session.commit()
    return expired


def commit_time_advance(
    world_id: str,
    sim_time: datetime | None,
    sim_last_advanced_at: datetime,
) -> bool:
    """提交时间推进锚点：仅当新锚点晚于已存锚点才写入（防并发回退）。

    多 worker 并发 tick 时，后到但更早的推进结果不会覆盖更晚的结果；
    无条件写会造成模拟时间回退（世界时钟倒退）。返回是否实际写入。
    """
    with SessionLocal() as session:
        row = session.get(WorldRow, world_id)
        if row is None:
            return False
        current_anchor = row.sim_last_advanced_at
        if current_anchor is not None and sim_last_advanced_at <= current_anchor:
            logger.debug(
                "时间推进锚点未前移，跳过写入：world=%s current=%s incoming=%s",
                world_id,
                current_anchor.isoformat(),
                sim_last_advanced_at.isoformat(),
            )
            return False
        row.sim_time = sim_time if sim_time is not None else row.sim_time
        row.sim_last_advanced_at = sim_last_advanced_at
        row.updated_at = sim_last_advanced_at
        session.commit()
        return True


def get_latest_idempotency_keys(world_id: str, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    with SessionLocal() as session:
        rows = session.scalars(
            select(WorldEventRow.idempotency_key).where(
                WorldEventRow.world_id == world_id,
                WorldEventRow.idempotency_key.in_(keys),
            )
        ).all()
        return {key for key in rows if key is not None}


def get_day_cycle_observation(world_id: str) -> dict | None:
    """读取上次日循环观测（存于 worlds.environment，跨进程/重启可见）。"""
    with SessionLocal() as session:
        row = session.get(WorldRow, world_id)
        if row is None:
            return None
        environment = row.environment or {}
        observation = environment.get(DAY_CYCLE_OBSERVATION_KEY)
        return dict(observation) if isinstance(observation, dict) else None


def save_day_cycle_observation(
    world_id: str,
    observed_at: datetime,
    part_of_day: str,
    time_mode: str,
) -> None:
    """写入上次日循环观测锚点（整体替换 JSON 键，避免残留旧值）。"""
    with SessionLocal() as session:
        row = session.get(WorldRow, world_id)
        if row is None:
            return
        environment = dict(row.environment or {})
        environment[DAY_CYCLE_OBSERVATION_KEY] = {
            "observed_at": observed_at.isoformat(),
            "part_of_day": part_of_day,
            "time_mode": time_mode,
        }
        row.environment = environment
        row.updated_at = observed_at
        session.commit()


def clear_day_cycle_observation(world_id: str) -> None:
    """清除日循环观测锚点（下次 tick 按冷启动处理）。"""
    with SessionLocal() as session:
        row = session.get(WorldRow, world_id)
        if row is None:
            return
        environment = dict(row.environment or {})
        if environment.pop(DAY_CYCLE_OBSERVATION_KEY, None) is None:
            return
        row.environment = environment
        row.updated_at = datetime.now()
        session.commit()
