"""V2.6.0 ActionScheduler：Action 级延迟/定时/优先级/队列（architecture.md §8.3）。"""

import logging
from datetime import datetime, timedelta
from typing import Sequence

from app.core.settings import get_settings
from app.models.action import Action, ActionSchedule
from app.repositories import action_repository, trigger_registry_repository

logger = logging.getLogger(__name__)

WHEN_IMMEDIATE = "immediate"
WHEN_DELAY = "delay"
WHEN_CRON = "cron"

CRON_DEFAULT_STEP_MINUTES = 1440


def _now() -> datetime:
    return datetime.now()


def _resolve_scheduled_at(
    when: str | None,
    *,
    now: datetime,
    delay: timedelta | None = None,
    scheduled_at: datetime | None = None,
    cron_from: datetime | None = None,
) -> tuple[str, datetime]:
    if when in (None, WHEN_IMMEDIATE):
        return WHEN_IMMEDIATE, now
    if when == WHEN_DELAY:
        if delay is None and scheduled_at is None:
            raise ValueError("delay 调度需要 delay 或 scheduled_at")
        if scheduled_at is not None:
            return WHEN_DELAY, scheduled_at
        return WHEN_DELAY, now + delay
    if when == WHEN_CRON:
        if scheduled_at is not None:
            return WHEN_CRON, scheduled_at
        base = cron_from or now
        return WHEN_CRON, base + timedelta(minutes=CRON_DEFAULT_STEP_MINUTES)
    raise ValueError(f"不支持的 when_type: {when}")


def schedule(
    action: Action,
    *,
    when: str | None = None,
    delay: timedelta | None = None,
    scheduled_at: datetime | None = None,
    priority: int | None = None,
    user_id: str | None = None,
) -> ActionSchedule:
    settings = get_settings()
    now = _now()
    when_type, due_at = _resolve_scheduled_at(
        when, now=now, delay=delay, scheduled_at=scheduled_at
    )
    resolved_priority = (
        priority
        if priority is not None
        else getattr(action, "priority", None)
        or settings.v26_action_schedule_default_priority
    )
    schedule_row = ActionSchedule(
        id=action_repository.new_schedule_id(),
        action_id=action.id,
        when_type=when_type,
        scheduled_at=due_at,
        priority=resolved_priority,
        status="scheduled",
        created_at=now,
        updated_at=now,
    )
    saved = action_repository.save_schedule(schedule_row)
    record = action_repository.get_record(action.id)
    owner = user_id or (record.user_id if record is not None else None) or "system"
    if record is not None and record.scheduled_at is None:
        record.scheduled_at = due_at
        if record.status == "created":
            from app.models.action import transition_action

            record.status = transition_action("created", "gate_pass") or "planned"
        record.updated_at = now
        action_repository.save_record(record)
    try:
        trigger_registry_repository.register(
            user_id=owner,
            trigger_type="action_due",
            trigger_key=f"action_schedule:{action.id}",
            due_at=due_at,
            payload={"kind": "action_schedule", "action_id": action.id, "when_type": when_type},
            now=now,
        )
    except Exception:
        logger.exception("action_schedule 触发器登记失败 action_id=%s", action.id)
    logger.info(
        "Action Scheduled action_id=%s when=%s at=%s priority=%s",
        action.id,
        when_type,
        due_at.isoformat(),
        resolved_priority,
    )
    return saved


def sort_queue(actions: Sequence[Action]) -> list[Action]:
    def key(action: Action):
        scheduled = action.scheduled_at or datetime.min
        return (-int(action.priority or 0), scheduled, action.id)

    return sorted(actions, key=key)


def due_actions(now: datetime | None = None, limit: int = 50) -> list[Action]:
    when = now or _now()
    schedules = action_repository.list_due_schedules(when, limit=limit)
    actions: list[Action] = []
    for item in schedules:
        record = action_repository.get_record(item.action_id)
        if record is None:
            continue
        actions.append(
            Action(
                id=record.id,
                type=record.action_type,
                target=record.user_id,
                parameters=dict(record.params or {}),
                priority=item.priority,
                status=record.status,
                scheduled_at=item.scheduled_at,
                source=record.source,
                goal_id=record.goal_id,
                dedupe_key=record.dedupe_key,
            )
        )
    return sort_queue(actions)


def next_action(now: datetime | None = None) -> Action | None:
    queue = due_actions(now)
    return queue[0] if queue else None


def consume_due_schedule(action_id: str) -> ActionSchedule | None:
    return action_repository.mark_schedule_executed(action_id)


def cancel_schedule(action_id: str) -> ActionSchedule | None:
    return action_repository.mark_schedule_cancelled(action_id)


def step_action_schedule(now: datetime | None = None) -> dict:
    """life_loop 维护步：扫描到期调度并登记 action_due 触发。"""
    settings = get_settings()
    if not (
        getattr(settings, "v26_action_execution_enabled", False)
        and getattr(settings, "v26_action_scheduler_enabled", False)
    ):
        return {"status": "skipped", "skip_reason": "flag_off"}
    when = now or _now()
    due = action_repository.list_due_schedules(when, limit=20)
    claimed = 0
    for item in due:
        if item.status == "scheduled":
            action_repository.save_schedule(
                item.model_copy(update={"status": "due", "updated_at": when})
            )
            claimed += 1
        record = action_repository.get_record(item.action_id)
        owner = record.user_id if record is not None else "system"
        try:
            trigger_registry_repository.register(
                user_id=owner,
                trigger_type="action_due",
                trigger_key=f"action_schedule:{item.action_id}",
                due_at=item.scheduled_at,
                payload={
                    "kind": "action_schedule",
                    "action_id": item.action_id,
                    "when_type": item.when_type,
                },
                now=when,
            )
        except Exception:
            logger.exception("到期调度触发登记失败 action_id=%s", item.action_id)
    return {"status": "done", "due": len(due), "claimed": claimed}
