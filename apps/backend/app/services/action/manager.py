"""V2.6.0 ActionManager：Action 生命周期唯一管理者（architecture.md §8.1）。

六能力 + execute：create / update / query / cancel / retry / execute / get_status。
不决策（G3）、不编排（G2）、不写世界/记忆/关系。
"""

import logging
from datetime import datetime
from typing import Any

from app.core.settings import get_settings
from app.models.action import (
    Action,
    ActionIntent,
    ActionRecord,
    ActionResult,
    ActionStatus,
    ActionSource,
    ActionType,
    make_dedupe_key,
    transition_action,
)
from app.repositories import action_repository

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = frozenset({"params", "priority", "scheduled_at"})
IMMUTABLE_FIELDS = frozenset({"id", "user_id", "action_type", "dedupe_key", "status"})
CANCELLABLE_STATUSES = ("created", "planned")


def _now() -> datetime:
    return datetime.now()


def _record_to_action(record: ActionRecord) -> Action:
    result = None
    if record.result:
        try:
            result = ActionResult.model_validate(record.result)
        except Exception:
            result = None
    return Action(
        id=record.id,
        type=record.action_type,
        target=record.user_id,
        parameters=dict(record.params or {}),
        priority=record.priority,
        status=record.status,
        result=result,
        created_at=record.created_at,
        scheduled_at=record.scheduled_at,
        executed_at=record.executed_at,
        source=record.source,
        goal_id=record.goal_id,
        plan_step=(record.intent or {}).get("plan_step"),
        dedupe_key=record.dedupe_key,
        run_id=record.run_id or record.session_id,
    )


def create(
    *,
    user_id: str,
    action_type: ActionType,
    params: dict[str, Any] | None = None,
    source: ActionSource = "conversation",
    session_id: str | None = None,
    goal_id: str | None = None,
    priority: int = 100,
    intent: ActionIntent | None = None,
    plan_step: str | None = None,
) -> Action:
    """创建 Action（status=created）。不决策、不编排。"""
    params = dict(params or {})
    if intent is not None:
        action_type = intent.action_type
        params = dict(intent.params or params)
        dedupe_key = intent.dedupe_key or make_dedupe_key(action_type, params)
        intent_payload = intent.model_dump(mode="json")
    else:
        dedupe_key = make_dedupe_key(action_type, params)
        intent_payload = {
            "action_type": action_type,
            "confidence": "confident",
            "params": params,
            "dedupe_key": dedupe_key,
        }
    if plan_step:
        intent_payload["plan_step"] = plan_step
    now = _now()
    record = ActionRecord(
        id=action_repository.new_record_id(),
        user_id=user_id,
        session_id=session_id,
        source=source,
        action_type=action_type,
        intent=intent_payload,
        goal_id=goal_id,
        dedupe_key=dedupe_key,
        params=params,
        status="created",
        priority=priority,
        created_at=now,
        updated_at=now,
    )
    saved = action_repository.save_record(record)
    logger.info(
        "Action Created action_id=%s type=%s source=%s", saved.id, action_type, source
    )
    return _record_to_action(saved)


def update(action_id: str, **fields: Any) -> Action | None:
    """受控字段更新；不可变/状态字段拒绝（状态迁移走 cancel/retry/execute）。"""
    illegal = IMMUTABLE_FIELDS & set(fields)
    unknown = set(fields) - UPDATABLE_FIELDS
    if illegal or unknown:
        raise ValueError(
            f"Action.update 拒绝不可变/未知字段: {sorted(illegal | unknown)}"
        )
    record = action_repository.get_record(action_id)
    if record is None:
        return None
    for key, value in fields.items():
        setattr(record, key, value)
    record.updated_at = _now()
    saved = action_repository.save_record(record)
    return _record_to_action(saved)


def query(
    action_id: str | None = None,
    *,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> Action | list[Action] | None:
    if action_id is not None:
        record = action_repository.get_record(action_id)
        return _record_to_action(record) if record is not None else None
    if status is not None and user_id is None:
        records = action_repository.list_by_status(status, limit=limit)
    elif user_id is not None:
        records = action_repository.list_records(user_id, status=status, limit=limit)
    else:
        raise ValueError("query 需要 action_id 或 user_id/status 过滤条件")
    return [_record_to_action(r) for r in records]


def cancel(action_id: str, *, reason: str = "cancel_requested") -> bool:
    """仅 created/planned 可取消；经 transition_action；不写世界/记忆/关系。"""
    record = action_repository.get_record(action_id)
    if record is None or record.status not in CANCELLABLE_STATUSES:
        return False
    new_status = transition_action(record.status, "cancel_requested")
    if new_status is None:
        return False
    record.status = new_status
    record.gate_reason = reason
    record.updated_at = _now()
    action_repository.save_record(record)
    logger.info("Action Cancelled action_id=%s reason=%s", action_id, reason)
    return True


async def execute(action_id: str, *, session_id: str | None = None) -> ActionResult | None:
    """复用既有记录执行（唯一编排器 action_engine），不新建第二条 ActionRecord。

    V2.6.1：`executing` 且 `next_retry_at` 未到时拒绝立即执行（退避窗口守卫）。
    """
    from app.application import action_engine

    record = action_repository.get_record(action_id)
    if record is None:
        return None
    if record.status in ("succeeded", "cancelled"):
        return None
    if record.status == "failed":
        return None
    if record.status == "executing" and record.next_retry_at is not None:
        if record.next_retry_at > _now():
            logger.info(
                "Action Execute Hold action_id=%s next_retry_at=%s",
                action_id,
                record.next_retry_at.isoformat(),
            )
            return None
    if session_id is not None and record.session_id is None:
        record.session_id = session_id
        action_repository.save_record(record)
    return await action_engine.execute_existing_record(record)


async def retry(action_id: str) -> ActionResult | None:
    """仅 failed 可重试；受 max_attempts 约束；复用原 dedupe_key。"""
    from app.application import action_engine

    record = action_repository.get_record(action_id)
    if record is None or record.status != "failed":
        return None
    settings = get_settings()
    if record.attempt >= settings.action_retry_max_attempts:
        return None
    planned = transition_action("failed", "gate_pass")
    if planned is None:
        planned = "planned"
    record.attempt += 1
    record.status = planned
    record.gate_reason = None
    record.updated_at = _now()
    action_repository.save_record(record)
    logger.info("Action Retried action_id=%s attempt=%s", action_id, record.attempt)
    return await action_engine.execute_existing_record(record)


def get_status(action_id: str) -> ActionStatus | None:
    record = action_repository.get_record(action_id)
    return record.status if record is not None else None
