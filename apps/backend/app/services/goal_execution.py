"""V2.0.0 AUT-003 Sub-Goal 执行尝试：规则构建 ActionIntent → V9 既有闸门。

引擎本体零改动（run_action_planning 原样调用，source=autonomy）；V9 闸门
拒绝（duplicate/quota 等返回 None）≠ 执行失败——不计失败数，trace 留痕；
执行成败由下周期判据观察收敛。user-facing 能力受静音时段克制（编排层
规则，不入 AutonomyPolicy——红线继承）。
"""

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.models.action import ActionIntent
from app.repositories import conversation_repository, goal_repository
from app.services import goal_observation, autonomy_policy

logger = logging.getLogger(__name__)

STEP_NAME = "goal_execution"

_USER_FACING_CAPABILITIES = frozenset({"send_notification"})


def _in_quiet_hours(now: datetime) -> bool:
    settings = get_settings()
    return autonomy_policy.in_quiet_hours(
        now,
        settings.autonomy_quiet_hours_start,
        settings.autonomy_quiet_hours_end,
    )


async def attempt_current_step(goal, plan, now: datetime) -> dict:
    """当前 Sub-Goal 的一次执行尝试；cooldown 内/静音时段/闸门拒绝全 trace。"""
    settings = get_settings()
    specs = list(plan.sub_goals)
    current = goal_observation._current_step(specs)
    if current is None:
        return {"status": "skipped", "skip_reason": "no_current_step"}
    cooldown = settings.autonomy_subgoal_execute_cooldown_minutes
    last = current.last_attempt_at
    if last is not None and (now - last).total_seconds() < cooldown * 60:
        return {"status": "skipped", "skip_reason": "cooldown", "goal_id": goal.id}
    if current.capability in _USER_FACING_CAPABILITIES and _in_quiet_hours(now):
        return {"status": "skipped", "skip_reason": "quiet_hours", "goal_id": goal.id}

    conversation = conversation_repository.get_latest_for_user(goal.user_id)
    intent = ActionIntent(
        action_type=current.capability,
        confidence="confident",
        params=dict(current.params or {}),
        dedupe_key=f"goal:{goal.id}:{plan.version}:{current.index}",
    )

    try:
        from app.application.action_engine import run_action_planning

        record = await run_action_planning(
            goal.user_id,
            intent,
            session_id=conversation.id if conversation is not None else None,
            goal_id=goal.id,
            source="autonomy",
        )
    except Exception as exc:
        logger.exception("Sub-Goal 执行尝试失败（goal=%s）", goal.id)
        return {
            "status": "error",
            "goal_id": goal.id,
            "error": exc.__class__.__name__,
        }
    current.last_attempt_at = now
    goal_repository.update_plan_progress(plan.id, specs)
    if record is None:
        return {
            "status": "gated",
            "goal_id": goal.id,
            "capability": current.capability,
        }
    return {
        "status": "ok",
        "goal_id": goal.id,
        "action_id": record.id,
        "action_status": record.status,
    }
