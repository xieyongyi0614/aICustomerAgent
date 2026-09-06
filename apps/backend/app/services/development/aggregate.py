"""Development Aggregate 读写（DEV-001）。

状态机 active→superseded|retired（终态不复活、非法转换拒绝），与 reflection
状态机同构但独立实现（Development 只写本域两表，不 import reflection/memory2）。
upsert_modulation 单事务完成「读同 key active → 仲裁 → 新建/替换/落败留痕 +
changes 行」：select 带 with_for_update（PG 行锁串行化并发仲裁；SQLite 测试库
顺序执行天然安全），迁移 API 全部条件化，重复输入 no-op 天然幂等。
changes.before/after 审计每一笔 state 变化，insight_id 必填（E-DEV-01 归因）。

仲裁比较器入参注入（本体属 DEV-002 策略）：默认 strength 高者胜、平手先到先得；
DEV-002 注入「同 strength 取较新 Insight」的完整比较器。
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.db import DevelopmentChangeRow, DevelopmentStateRow, SessionLocal
from app.models.development import DevelopmentChange, DevelopmentState

logger = logging.getLogger(__name__)

STEP_NAME = "development_state"

STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_RETIRED = "retired"

EVENT_WRITE = "write"
EVENT_ARBITRATE = "arbitrate"
EVENT_RETIRE = "retire"

TRANSITIONS = {
    (STATUS_ACTIVE, EVENT_ARBITRATE): STATUS_SUPERSEDED,
    (STATUS_ACTIVE, EVENT_RETIRE): STATUS_RETIRED,
}

REASON_COMPILED = "compiled"
REASON_ARBITRATED = "arbitrated"
REASON_ARBITRATED_LOST = "arbitrated_lost"
REASON_RETIRED = "retired"
REASON_ROLLED_BACK = "rolled_back"
REASON_REPLAYED = "replayed"

OUTCOME_CREATED = "created"
OUTCOME_REPLACED = "replaced"
OUTCOME_LOST = "lost"
OUTCOME_NOOP = "noop"


class IllegalTransitionError(Exception):
    def __init__(self, status: str, event: str):
        super().__init__(f"非法状态转换: {status} --{event}--> ?")
        self.status = status
        self.event = event


def transition(status: str, event: str) -> str:
    try:
        return TRANSITIONS[(status, event)]
    except KeyError:
        raise IllegalTransitionError(status, event) from None


@dataclass
class UpsertOutcome:
    outcome: str
    state: DevelopmentState | None = None


def default_comparator(proposal: dict, existing: DevelopmentStateRow) -> bool:
    return proposal["strength"] > existing.strength


def upsert_modulation(
    user_id: str,
    kind: str,
    key: str,
    value: dict,
    strength: float,
    source_insight_id: str,
    *,
    source_insight_created_at: datetime | None = None,
    comparator=default_comparator,
    character_id: str = "asuna",
    now: datetime | None = None,
    trace=None,
) -> UpsertOutcome:
    """调制提案落库：无 active 新建；仲裁胜出替换（旧王 superseded）；落败留痕。

    同 (user, key, insight) 已有行 → noop（编译幂等的存储侧表达）。
    """
    started = time.perf_counter()
    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"strength 越界: {strength}")
    now = now or datetime.now()
    proposal = {
        "kind": kind,
        "key": key,
        "value": value,
        "strength": strength,
        "source_insight_id": source_insight_id,
        "source_insight_created_at": source_insight_created_at,
    }
    with SessionLocal() as session:
        seen = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.key == key,
                DevelopmentStateRow.source_insight_id == source_insight_id,
            )
            .first()
        )
        if seen is not None:
            outcome = UpsertOutcome(OUTCOME_NOOP, _to_state(seen))
            _trace(trace, started, key=key, op="noop", insight_id=source_insight_id)
            return outcome
        active = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.key == key,
                DevelopmentStateRow.status == STATUS_ACTIVE,
            )
            .with_for_update()
            .first()
        )
        if active is None:
            row = _insert(session, user_id, character_id, proposal, STATUS_ACTIVE, now)
            _record_change(
                session, row.id, None, value, source_insight_id, REASON_COMPILED, now
            )
            session.commit()
            result = UpsertOutcome(OUTCOME_CREATED, _to_state(row))
            _trace(trace, started, key=key, op="created", insight_id=source_insight_id)
            return result
        if comparator(proposal, active):
            active.status = transition(active.status, EVENT_ARBITRATE)
            active.updated_at = now
            row = _insert(session, user_id, character_id, proposal, STATUS_ACTIVE, now)
            _record_change(
                session,
                row.id,
                active.value,
                value,
                source_insight_id,
                REASON_ARBITRATED,
                now,
            )
            session.commit()
            result = UpsertOutcome(OUTCOME_REPLACED, _to_state(row))
            _trace(trace, started, key=key, op="replaced", insight_id=source_insight_id)
            return result
        row = _insert(session, user_id, character_id, proposal, STATUS_SUPERSEDED, now)
        _record_change(
            session, row.id, None, value, source_insight_id, REASON_ARBITRATED_LOST, now
        )
        session.commit()
        result = UpsertOutcome(OUTCOME_LOST, _to_state(row))
        _trace(trace, started, key=key, op="lost", insight_id=source_insight_id)
        return result


def retire_modulation(
    user_id: str,
    key: str,
    insight_id: str,
    reason: str = REASON_RETIRED,
    *,
    character_id: str = "asuna",
    now: datetime | None = None,
    trace=None,
) -> bool:
    """active→retired（调制撤除无继任）；无 active 行幂等 no-op 返回 False。"""
    started = time.perf_counter()
    now = now or datetime.now()
    with SessionLocal() as session:
        active = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.key == key,
                DevelopmentStateRow.status == STATUS_ACTIVE,
            )
            .with_for_update()
            .first()
        )
        if active is None:
            _trace(trace, started, key=key, op="retire", status="noop")
            return False
        active.status = transition(active.status, EVENT_RETIRE)
        active.updated_at = now
        _record_change(session, active.id, active.value, None, insight_id, reason, now)
        session.commit()
    _trace(trace, started, key=key, op="retire", insight_id=insight_id, status="ok")
    return True


def list_active_modulations(
    user_id: str, character_id: str = "asuna"
) -> list[DevelopmentState]:
    """active 调制只读查询（key ASC）；DEV-003 叠加层读取入口。"""
    with SessionLocal() as session:
        rows = (
            session.query(DevelopmentStateRow)
            .filter(
                DevelopmentStateRow.user_id == user_id,
                DevelopmentStateRow.character_id.in_([character_id, "*"]),
                DevelopmentStateRow.status == STATUS_ACTIVE,
            )
            .order_by(DevelopmentStateRow.key.asc())
            .all()
        )
        return [_to_state(row) for row in rows]


def get_state_history(state_id: str) -> list[DevelopmentChange]:
    """state 全部 changes（时间序）；DEV-004 重放与 DEV-005 归因复用。"""
    with SessionLocal() as session:
        rows = (
            session.query(DevelopmentChangeRow)
            .filter(DevelopmentChangeRow.development_state_id == state_id)
            .order_by(DevelopmentChangeRow.created_at.asc(), DevelopmentChangeRow.id.asc())
            .all()
        )
        return [_to_change(row) for row in rows]


def _insert(session, user_id, character_id, proposal: dict, status: str, now: datetime):
    row = DevelopmentStateRow(
        id=f"dev:{uuid.uuid4().hex}",
        user_id=user_id,
        character_id=character_id,
        kind=proposal["kind"],
        key=proposal["key"],
        value=proposal["value"],
        strength=proposal["strength"],
        source_insight_id=proposal["source_insight_id"],
        status=status,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def _record_change(
    session,
    state_id: str,
    before: dict | None,
    after: dict | None,
    insight_id: str,
    reason: str,
    now: datetime,
):
    session.add(
        DevelopmentChangeRow(
            id=f"devc:{uuid.uuid4().hex}",
            development_state_id=state_id,
            before=before,
            after=after,
            insight_id=insight_id,
            reason=reason,
            created_at=now,
        )
    )


def _to_state(row: DevelopmentStateRow) -> DevelopmentState:
    return DevelopmentState(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        kind=row.kind,
        key=row.key,
        value=row.value,
        strength=row.strength,
        source_insight_id=row.source_insight_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_change(row: DevelopmentChangeRow) -> DevelopmentChange:
    return DevelopmentChange(
        id=row.id,
        development_state_id=row.development_state_id,
        before=row.before,
        after=row.after,
        insight_id=row.insight_id,
        reason=row.reason,
        created_at=row.created_at,
    )


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
