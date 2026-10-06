"""Memory 2.0 生命周期引擎（MEM-005）。

六态状态机（active/superseded/invalidated/decayed/forgotten + 软删后物理删），
非法转换守卫拒绝。衰减 `salience·exp(-λ_type·Δdays)` 按日桶幂等（last_decayed_at
游标，Δ<1 天跳过），压到 floor 转 decayed；decayed 超保留期转 forgotten。
reinforce 走内存缓冲批量 flush（取代 v1 读路径直写），支持 decayed 复活。
on_promoted 对新转正记忆做冲突检测：同主题 → supersede/merge 记链（superseded_by
+ memory_links + merge_chain）；extractor negate 信号 → contradicts 保守并存（两行
均 active，由用户澄清/P2 反思解决）。显式 forget 同事务置 forgotten + 清向量，
保留期后 purge 物理删除（含 links）。
"""

import logging
import math
import time
from datetime import datetime, timedelta

from sqlalchemy import or_

from app.core import ids, timeutil
from app.core.db import Memory, MemoryLinkRow, SessionLocal
from app.core.settings import get_settings
from app.services.memory import types as memory_types
from app.engines.memory_conflict import _lcs_length, same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "memory_lifecycle"

STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_INVALIDATED = "invalidated"
STATUS_DECAYED = "decayed"
STATUS_FORGOTTEN = "forgotten"

EVENT_REINFORCE = "reinforce"
EVENT_SUPERSEDE = "supersede"
EVENT_MERGE = "merge"
EVENT_INVALIDATE = "invalidate"
EVENT_DECAY_FLOOR = "decay_floor"
EVENT_DECAY_FORGET = "decay_forget"
EVENT_FORGET = "forget"

RELATION_SUPERSEDES = "supersedes"
RELATION_MERGES = "merges"
RELATION_CONTRADICTS = "contradicts"

TRANSITIONS = {
    (STATUS_ACTIVE, EVENT_REINFORCE): STATUS_ACTIVE,
    (STATUS_DECAYED, EVENT_REINFORCE): STATUS_ACTIVE,
    (STATUS_ACTIVE, EVENT_SUPERSEDE): STATUS_SUPERSEDED,
    (STATUS_ACTIVE, EVENT_MERGE): STATUS_SUPERSEDED,
    (STATUS_ACTIVE, EVENT_INVALIDATE): STATUS_INVALIDATED,
    (STATUS_ACTIVE, EVENT_DECAY_FLOOR): STATUS_DECAYED,
    (STATUS_ACTIVE, EVENT_DECAY_FORGET): STATUS_FORGOTTEN,
    (STATUS_DECAYED, EVENT_DECAY_FORGET): STATUS_FORGOTTEN,
    (STATUS_ACTIVE, EVENT_FORGET): STATUS_FORGOTTEN,
    (STATUS_DECAYED, EVENT_FORGET): STATUS_FORGOTTEN,
    (STATUS_SUPERSEDED, EVENT_FORGET): STATUS_FORGOTTEN,
    (STATUS_INVALIDATED, EVENT_FORGET): STATUS_FORGOTTEN,
    (STATUS_FORGOTTEN, EVENT_FORGET): STATUS_FORGOTTEN,
}

_FORGET_ABLE_STATUSES = (STATUS_ACTIVE, STATUS_DECAYED)

_DEFAULT_SALIENCE = 0.5
_PURGE_BATCH_LIMIT = 200


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


def _similarity(left: str, right: str) -> float:
    longer = max(len(left), len(right))
    if longer == 0:
        return 0.0
    return _lcs_length(left, right) / longer


def decay_lambda_for(memory_type: str) -> float:
    table = get_settings().decay_lambdas()
    canonical = memory_types.normalize_type(memory_type) or memory_type
    if canonical in table:
        return float(table[canonical])
    return max(float(value) for value in table.values())


_reinforce_pending: list[str] = []
_reinforce_seen: set[str] = set()


def record_reinforce(memory_id: str) -> None:
    """检索命中侧只进内存缓冲，批量 flush（写放大防护）。"""
    if not memory_id or memory_id in _reinforce_seen:
        return
    _reinforce_seen.add(memory_id)
    _reinforce_pending.append(memory_id)


def flush_reinforce_buffer(trace=None) -> list[str]:
    """批量落库强化缓冲；返回本次落库的 memory_id（REF-003 事件计数订阅该返回值）。"""
    if not _reinforce_pending:
        return []
    batch = list(_reinforce_pending)
    try:
        updated_ids = _apply_reinforce(batch, trace=trace)
    except Exception:
        logger.exception("reinforce 批量写失败，缓冲保留待下轮")
        return []
    flushed = set(batch)
    _reinforce_pending[:] = [mid for mid in _reinforce_pending if mid not in flushed]
    _reinforce_seen.difference_update(flushed)
    return updated_ids


def _apply_reinforce(memory_ids: list[str], trace=None) -> list[str]:
    started = time.perf_counter()
    now = timeutil.now()
    boost = get_settings().memory_reinforce_boost
    updated_ids: list[str] = []
    with SessionLocal() as session:
        rows = session.query(Memory).filter(Memory.id.in_(memory_ids)).all()
        for row in rows:
            if (row.status, EVENT_REINFORCE) not in TRANSITIONS:
                continue
            row.status = transition(row.status, EVENT_REINFORCE)
            row.salience = min(1.0, (row.salience if row.salience is not None else _DEFAULT_SALIENCE) + boost)
            row.last_reinforced_at = now
            row.last_decayed_at = now
            row.last_accessed_at = now
            updated_ids.append(row.id)
        session.commit()
    _trace(
        trace,
        started,
        event=EVENT_REINFORCE,
        memory_ids=list(memory_ids),
        updated=len(updated_ids),
    )
    return updated_ids


def _decay_reference(row: Memory) -> datetime:
    return row.last_decayed_at or row.last_reinforced_at or row.created_at


def _forget_reference(row: Memory) -> datetime:
    return row.last_reinforced_at or row.created_at


def run_decay_cycle(now: datetime | None = None, trace=None) -> dict:
    """周期入口：衰减批 + decayed 超期遗忘 + forgotten 物理清。MEM-009 调度。"""
    now = timeutil.ensure_aware(now) or timeutil.now()
    stats = {"decayed": 0, "auto_forgotten": 0, "purged": 0}
    stats["decayed"] = _decay_batch(now, trace=trace)
    stats["auto_forgotten"] = _forget_stale_decayed(now, trace=trace)
    stats["purged"] = purge_expired_forgotten(now, trace=trace)
    return stats


def _decay_batch(now: datetime, trace=None) -> int:
    started = time.perf_counter()
    settings = get_settings()
    floor = settings.memory_salience_floor
    decayed_count = 0
    scanned = 0
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.status == STATUS_ACTIVE)
            .order_by(Memory.created_at.asc())
            .limit(settings.memory_decay_batch_size)
            .all()
        )
        for row in rows:
            try:
                elapsed_days = (now - _decay_reference(row)).total_seconds() / 86400
                if elapsed_days < 1.0:
                    continue
                scanned += 1
                lam = decay_lambda_for(row.type)
                base = row.salience if row.salience is not None else _DEFAULT_SALIENCE
                row.salience = base * math.exp(-lam * elapsed_days)
                row.last_decayed_at = now
                if row.salience <= floor:
                    row.status = transition(row.status, EVENT_DECAY_FLOOR)
                    decayed_count += 1
            except Exception:
                logger.exception("记忆衰减失败，跳过该行：%s", row.id)
        session.commit()
    _trace(trace, started, event="decay", scanned=scanned, decayed=decayed_count)
    return decayed_count


def _forget_stale_decayed(now: datetime, trace=None) -> int:
    started = time.perf_counter()
    now = timeutil.ensure_aware(now)
    retention_days = get_settings().memory_forget_retention_days
    threshold = now - timedelta(days=retention_days)
    forgotten = 0
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.status == STATUS_DECAYED)
            .all()
        )
        for row in rows:
            if _forget_reference(row) >= threshold:
                continue
            try:
                row.status = transition(row.status, EVENT_DECAY_FORGET)
                row.embedding = None
                row.forgotten_at = now
                forgotten += 1
            except Exception:
                logger.exception("decayed 自动遗忘失败：%s", row.id)
        session.commit()
    _trace(trace, started, event=EVENT_DECAY_FORGET, forgotten=forgotten)
    return forgotten


def purge_expired_forgotten(now: datetime | None = None, trace=None) -> int:
    """软删保留期（memory_forget_retention_days）届满的 forgotten 行物理删除。"""
    now = timeutil.ensure_aware(now) or timeutil.now()
    started = time.perf_counter()
    threshold = now - timedelta(days=get_settings().memory_forget_retention_days)
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.status == STATUS_FORGOTTEN,
                Memory.forgotten_at.isnot(None),
                Memory.forgotten_at < threshold,
            )
            .limit(_PURGE_BATCH_LIMIT)
            .all()
        )
        ids = [row.id for row in rows]
        if not ids:
            _trace(trace, started, event="purge", purged=0)
            return 0
        session.query(MemoryLinkRow).filter(
            or_(
                MemoryLinkRow.memory_id.in_(ids),
                MemoryLinkRow.related_memory_id.in_(ids),
            )
        ).delete(synchronize_session=False)
        session.query(Memory).filter(Memory.id.in_(ids)).delete(
            synchronize_session=False
        )
        session.commit()
    _trace(trace, started, event="purge", purged=len(ids))
    return len(ids)


def on_promoted(memory_id: str, relation: str | None = None, trace=None) -> None:
    """新转正记忆的冲突检测：同主题 supersede/merge 记链；negate 保守并存。"""
    started = time.perf_counter()
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is None or row.status != STATUS_ACTIVE or not (row.content or "").strip():
            return
        actives = (
            session.query(Memory)
            .filter(
                Memory.user_id == row.user_id,
                Memory.status == STATUS_ACTIVE,
                Memory.id != row.id,
            )
            .all()
        )
        matches = [
            existing
            for existing in actives
            if same_topic(row.content, existing.content or "")
        ]
        if not matches:
            _trace(
                trace, started, event="no_conflict", memory_id=memory_id
            )
            return
        target = max(matches, key=lambda m: _similarity(row.content, m.content or ""))
        if relation == "negate":
            if not _link_exists(session, row.id, target.id, RELATION_CONTRADICTS):
                _create_link(session, row.id, target.id, RELATION_CONTRADICTS)
            session.commit()
            _trace(
                trace,
                started,
                event="contradicts",
                memory_id=memory_id,
                target_id=target.id,
                reason="negate 信号保守并存，待澄清",
            )
            return
        if (target.content or "") and (target.content or "") in (row.content or ""):
            link_relation = RELATION_MERGES
            event = EVENT_MERGE
        else:
            link_relation = RELATION_SUPERSEDES
            event = EVENT_SUPERSEDE
        target.status = transition(target.status, event)
        target.superseded_by = row.id
        target.updated_at = now
        merge_chain = list(row.merge_chain or [])
        merge_chain.append(target.id)
        row.merge_chain = merge_chain
        if not _link_exists(session, row.id, target.id, link_relation):
            _create_link(session, row.id, target.id, link_relation)
        session.commit()
        _trace(
            trace,
            started,
            event=event,
            memory_id=memory_id,
            target_id=target.id,
            relation=link_relation,
        )


def _link_exists(session, memory_id: str, related_memory_id: str, relation: str) -> bool:
    return (
        session.query(MemoryLinkRow)
        .filter(
            MemoryLinkRow.memory_id == memory_id,
            MemoryLinkRow.related_memory_id == related_memory_id,
            MemoryLinkRow.relation == relation,
        )
        .first()
        is not None
    )


def _create_link(session, memory_id: str, related_memory_id: str, relation: str) -> None:
    session.add(
        MemoryLinkRow(
            id=ids.new_id_str(),
            memory_id=memory_id,
            related_memory_id=related_memory_id,
            relation=relation,
            created_at=timeutil.now(),
        )
    )


def explicit_forget(memory_id: str, trace=None) -> bool:
    """显式遗忘单条：状态机迁移 forgotten + 清向量（同事务）；已 forgotten 幂等。"""
    started = time.perf_counter()
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.get(Memory, memory_id)
        if row is None:
            _trace(trace, started, event=EVENT_FORGET, memory_id=memory_id, status="miss")
            return False
        previous = row.status
        new_status = transition(row.status, EVENT_FORGET)
        if new_status != previous:
            row.status = new_status
            row.embedding = None
            row.forgotten_at = now
            row.updated_at = now
        session.commit()
    _trace(
        trace,
        started,
        event=EVENT_FORGET,
        memory_id=memory_id,
        previous_status=previous,
        status="ok",
    )
    return True


def explicit_forget_by_match(
    user_id: str, content: str, character_id: str = "asuna", trace=None
) -> list[str]:
    """按内容高匹配遗忘（相等或包含）；模糊不删（防误删，MEM-007 复用）。"""
    target = (content or "").strip()
    if not target:
        return []
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.character_id.in_([character_id, "*"]),
                Memory.status.in_(_FORGET_ABLE_STATUSES),
            )
            .all()
        )
        matched_ids = [
            row.id
            for row in rows
            if target == row.content.strip()
            or target in row.content.strip()
            or row.content.strip() in target
        ]
    forgotten_ids = []
    for memory_id in matched_ids:
        if explicit_forget(memory_id, trace=trace):
            forgotten_ids.append(memory_id)
    return forgotten_ids


def _trace(trace, started: float, *, event: str, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    payload = {"event": event, **extra}
    trace.record(STEP_NAME, duration, status, **payload)


def reset_reinforce_buffer() -> None:
    """清空强化缓冲（测试与运维复位；flush 失败保留语义不受影响）。"""
    _reinforce_pending.clear()
    _reinforce_seen.clear()
