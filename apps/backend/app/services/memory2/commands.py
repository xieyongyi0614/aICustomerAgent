"""Memory 2.0 显式命令通道（MEM-007）。

规则词表识别「记住/忘掉 X」显式指令：remember → explicit_remember 候选（幂等键
commands:{user_id}:{object_hash}）经 MEM-003 直通转正（salience=1.0、0 LLM），
同主题既有记忆则 reinforce 而非新建；forget → same_topic 匹配 active 记忆，仅
唯一高匹配才执行 lifecycle.explicit_forget，多匹配/无匹配一律不删并降级为普通
候选流程（防误删，误删率 0 为硬指标）。识别失败静默降级，不新增 LLM 链。
"""

import hashlib
import logging
import time
import uuid
from datetime import datetime

from app.core.db import Memory, MemoryCandidateRow, SessionLocal
from app.core.settings import get_settings
from app.services.memory2 import evaluator as memory_evaluator
from app.services.memory2 import lifecycle as memory_lifecycle
from app.services.memory_conflict import _lcs_length, same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "memory_command"

SOURCE_TABLE_COMMANDS = "commands"
SOURCE_EXPLICIT_REMEMBER = "explicit_remember"
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"

LIFECYCLE_MATCHABLE_STATUSES = ("active", "decayed")

OUTCOME_REMEMBER_PROMOTED = "remember_promoted"
OUTCOME_REMEMBER_REINFORCED = "remember_reinforced"
OUTCOME_FORGOT = "forgot"
OUTCOME_MISS = "miss"

ACTION_REMEMBER = "remember"
ACTION_FORGET = "forget"

_REMEMBER_TRIGGERS = ("记住", "记一下", "记着", "帮我记")
_FORGET_TRIGGERS = ("忘掉", "忘记", "删除记忆", "别记了", "忘了吧")

_OBJECT_MIN_CHARS = 2
_OBJECT_LEADING_PUNCTUATION = "，,。.：:、！!？? 　"

_PREFERENCE_HINTS = ("喜欢", "讨厌", "爱", "不爱", "偏好", "最爱")


def detect_command(message_text: str) -> tuple[str, str] | None:
    """词表识别：返回 (action, object)；未命中、疑问句或 object 过短返回 None。"""
    text = (message_text or "").strip()
    if not text or text.endswith(("？", "?")):
        return None
    for action, triggers in (
        (ACTION_FORGET, _FORGET_TRIGGERS),
        (ACTION_REMEMBER, _REMEMBER_TRIGGERS),
    ):
        for trigger in triggers:
            if trigger in text:
                object_text = _extract_object(text, trigger)
                if len(object_text) < _OBJECT_MIN_CHARS:
                    return None
                return action, object_text
    return None


def _extract_object(text: str, trigger: str) -> str:
    remainder = text.split(trigger, 1)[1].strip()
    return remainder.lstrip(_OBJECT_LEADING_PUNCTUATION).strip()


def _object_hash(object_text: str) -> str:
    return hashlib.sha256(object_text.encode("utf-8")).hexdigest()[:16]


def _proposed_type_for(object_text: str) -> str:
    if any(hint in object_text for hint in _PREFERENCE_HINTS):
        return "user_preference"
    return "user_fact"


async def handle(user_id: str, message_text: str, trace=None) -> str:
    """命令入口：命中并执行返回 handled 类 Outcome；miss 时走普通候选流程。"""
    started = time.perf_counter()
    detected = detect_command(message_text)
    if detected is None:
        _trace(trace, started, outcome=OUTCOME_MISS, reason="no_command")
        return OUTCOME_MISS
    action, object_text = detected
    try:
        if action == ACTION_REMEMBER:
            outcome = await _handle_remember(user_id, object_text, trace=trace)
        else:
            outcome = _handle_forget(user_id, object_text, trace=trace)
    except Exception:
        logger.exception("显式命令执行失败，降级普通候选流程")
        _trace(trace, started, outcome=OUTCOME_MISS, reason="execution_error")
        return OUTCOME_MISS
    _trace(
        trace,
        started,
        outcome=outcome,
        command=action,
        object_preview=object_text[:32],
    )
    return outcome


async def _handle_remember(user_id: str, object_text: str, trace=None) -> str:
    existing = _match_active(user_id, object_text)
    if existing:
        best = max(
            existing,
            key=lambda row: _similarity(object_text, row.content or ""),
        )
        memory_lifecycle.record_reinforce(best.id)
        memory_lifecycle.flush_reinforce_buffer()
        _trace(
            trace,
            0.0,
            outcome=OUTCOME_REMEMBER_REINFORCED,
            target_id=best.id,
        )
        return OUTCOME_REMEMBER_REINFORCED
    row = _create_command_candidate(
        user_id,
        action=ACTION_REMEMBER,
        object_text=object_text,
    )
    if row is None:
        return OUTCOME_MISS
    decision = await memory_evaluator.evaluate_candidate(
        row, _active_contents(user_id)
    )
    if decision.action == "approve":
        return OUTCOME_REMEMBER_PROMOTED
    return OUTCOME_MISS


def _handle_forget(user_id: str, object_text: str, trace=None) -> str:
    matches = _match_active(user_id, object_text)
    if len(matches) == 0:
        _trace(trace, 0.0, outcome="degraded", reason="forget_no_match")
        return OUTCOME_MISS
    if len(matches) > 1:
        _trace(
            trace,
            0.0,
            outcome="degraded",
            reason="forget_ambiguous",
            match_count=len(matches),
        )
        return OUTCOME_MISS
    target = matches[0]
    memory_lifecycle.explicit_forget(target.id, trace=trace)
    return OUTCOME_FORGOT


def _match_active(user_id: str, object_text: str) -> list[Memory]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.status.in_(LIFECYCLE_MATCHABLE_STATUSES),
            )
            .all()
        )
        matched = [
            row
            for row in rows
            if _same_topic(object_text, row.content or "")
        ]
        for row in matched:
            session.expunge(row)
        return matched


def _active_contents(user_id: str) -> list[str]:
    with SessionLocal() as session:
        rows = (
            session.query(Memory.content)
            .filter(Memory.user_id == user_id, Memory.status == STATUS_ACTIVE)
            .all()
        )
        return [row[0] for row in rows]


def _same_topic(left: str, right: str) -> bool:
    return same_topic(left, right)


def _similarity(left: str, right: str) -> float:
    return _lcs_length(left, right) / max(len(left), len(right))


def _create_command_candidate(user_id: str, *, action: str, object_text: str):
    source_id = f"{user_id}:{action}:{_object_hash(object_text)}"
    with SessionLocal() as session:
        existing = (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.source_table == SOURCE_TABLE_COMMANDS,
                MemoryCandidateRow.source_id == source_id,
            )
            .first()
        )
        if existing is not None:
            session.expunge(existing)
            return existing
        row = MemoryCandidateRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            character_id="asuna",
            content=object_text,
            proposed_type=_proposed_type_for(object_text),
            source=SOURCE_EXPLICIT_REMEMBER,
            source_ref={"table": SOURCE_TABLE_COMMANDS, "id": source_id},
            source_table=SOURCE_TABLE_COMMANDS,
            source_id=source_id,
            salience=1.0,
            status=STATUS_PENDING,
            visibility="private",
            created_at=datetime.now(),
        )
        session.add(row)
        session.commit()
        session.expunge(row)
        return row


def _trace(trace, started: float, *, outcome: str, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, outcome=outcome, **extra)
