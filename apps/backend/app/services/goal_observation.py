"""V2.0.0 AUT-003 Observation：判据求值 / 推进 / 失败计数 / 调整裁决。

判据谓词与 AUT-002 校验闸共用 app/models/goal.py 白名单；事实由编排方
（Life Loop goal_advance 步骤）采集投影传入（GAP-AUT-02），本模块零
Action/World 表查询。调整全确定性：顺序跳步 / 触发重规划（AUT-002 通道）
/ goal failed；失败计数按周期事件幂等（同周期同步只计一次）。
"""

import logging
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.goal import SubGoalSpec
from app.repositories import goal_repository
from app.services import goal_planning, goal_arbitration
from app.services.memory2 import ingest as memory_ingest

logger = logging.getLogger(__name__)

STEP_NAME = "goal_observation"

REASON_COMPLETED = "goal_completed"
REASON_PERIOD_EXCEEDED = "exec_period_exceeded"
REASON_THRESHOLD_EXCEEDED = "subgoal_threshold_exceeded"
REASON_REPLAN_EXHAUSTED = "replan_exhausted"


def _fact_value(facts: dict, source: str, path: str):
    bucket = facts.get(source)
    if not isinstance(bucket, dict):
        return None
    return bucket.get(path)


def evaluate_criteria(criteria: dict, facts: dict) -> bool | None:
    """白名单谓词求值：True 达成 / False 未达成 / None 不可判定（异常跳过不计数）。"""
    criterion_type = criteria.get("type")
    if criterion_type == "action_succeeded":
        action_results = facts.get("action_results") or []
        within_minutes = criteria.get("within_minutes")
        window_start = (
            facts.get("now") - timedelta(minutes=within_minutes)
            if within_minutes and facts.get("now")
            else None
        )
        for record in action_results:
            if record.get("capability") != criteria.get("capability"):
                continue
            if record.get("status") != "succeeded":
                continue
            created_at = record.get("created_at")
            if window_start is not None and created_at is not None:
                if created_at < window_start:
                    continue
            return True
        return False
    if criterion_type == "field_equals":
        value = _fact_value(facts, criteria.get("source"), criteria.get("path"))
        if value is None:
            return None
        return value == criteria.get("value")
    if criterion_type == "threshold_reached":
        value = _fact_value(facts, criteria.get("source"), criteria.get("path"))
        if not isinstance(value, (int, float)):
            return None
        threshold = criteria.get("value")
        if criteria.get("op") == ">=":
            return value >= threshold
        if criteria.get("op") == "<=":
            return value <= threshold
        return None
    if criterion_type in ("all_of", "any_of"):
        children = criteria.get("children") or []
        results = [evaluate_criteria(child, facts) for child in children]
        if criterion_type == "all_of":
            if any(result is None for result in results):
                return None
            return all(results)
        if any(result is True for result in results):
            return True
        if any(result is None for result in results):
            return None
        return False
    return None


def _execution_order(specs: list[SubGoalSpec]) -> list[SubGoalSpec]:
    """叶子优先执行序：每顶层步的子步先于父步。"""
    order: list[SubGoalSpec] = []
    for top in (spec for spec in specs if spec.parent_index is None):
        order.extend(
            child for child in specs if child.parent_index == top.index
        )
        order.append(top)
    return order


def _current_step(specs: list[SubGoalSpec]) -> SubGoalSpec | None:
    for spec in _execution_order(specs):
        if spec.status in ("pending", "in_progress"):
            return spec
    return None


def _all_done(specs: list[SubGoalSpec]) -> bool:
    return all(spec.status == "done" for spec in specs)


def _has_executable(specs: list[SubGoalSpec]) -> bool:
    return any(
        spec.status in ("pending", "in_progress") and spec.parent_index is None
        for spec in specs
    )


def _save_progress(plan_id: str, specs: list[SubGoalSpec], now: datetime) -> None:
    goal_repository.update_plan_progress(plan_id, specs)


def _record_lifecycle(record, decision: str, reason: str, goal_id: str) -> None:
    """终态/挂起转换的 lifecycle 归因（不变量 2；委托仲裁器公共入口）。"""

    try:
        goal_arbitration.record_goal_lifecycle(
            record, decision, reason, {"goal_id": goal_id}
        )
    except Exception:
        logger.exception("goal lifecycle 归因失败（goal=%s）", goal_id)


def _complete(goal) -> dict:
    record = goal_repository.complete_goal(goal.id)
    _record_lifecycle(record or goal, "completed", "计划步骤全部完成", goal.id)

    try:
        from app.services.world import event_bridge

        event_bridge.register_goal_event(
            goal.user_id, goal.id, goal.description, "completed"
        )
    except Exception:
        logger.exception("goal 完成世界事件登记失败（goal=%s）", goal.id)

    try:
        memory_ingest.ingest_from_goal_completion(
            goal.user_id, goal.id, goal.description
        )
    except Exception:
        logger.exception("goal 完成 experience 转写失败（goal=%s）", goal.id)
    return {
        "outcome": "completed",
        "goal_status": record.status if record else None,
    }


def advance_goal(goal, plan, facts: dict, now: datetime) -> dict:
    """单 goal 推进：封顶 → 观察/推进/计数 → 调整 → 执行尝试由调用方接线。"""
    settings = get_settings()
    specs = list(plan.sub_goals)
    detail: dict = {"goal_id": goal.id, "observations": 0, "adjustments": []}

    active_start = plan.updated_at or plan.created_at
    max_hours = settings.v2_autonomy_goal_max_active_hours
    if active_start is not None and now - active_start > timedelta(hours=max_hours):
        record = goal_repository.fail_goal(goal.id, REASON_PERIOD_EXCEEDED)
        _record_lifecycle(record or goal, "failed", REASON_PERIOD_EXCEEDED, goal.id)
        detail["outcome"] = "failed"
        detail["reason"] = REASON_PERIOD_EXCEEDED
        detail["goal_status"] = record.status if record else None
        return detail

    current = _current_step(specs)
    if current is None:
        if _all_done(specs):
            detail.update(_complete(goal))
            return detail
        if goal_repository.count_plans(goal.id) < settings.v2_autonomy_planning_max_attempts:
            enqueued = goal_planning.enqueue_planning(
                goal.user_id, goal.id, goal_planning.TRIGGER_BLOCKED
            )
            detail["outcome"] = "replanning"
            detail["adjustments"].append(
                f"replan:{goal_planning.TRIGGER_BLOCKED}:"
                f"{'enqueued' if enqueued else 'deduped'}"
            )
            return detail
        record = goal_repository.fail_goal(goal.id, REASON_THRESHOLD_EXCEEDED)
        _record_lifecycle(record or goal, "failed", REASON_THRESHOLD_EXCEEDED, goal.id)
        enqueued = goal_planning.enqueue_planning(
            goal.user_id, goal.id, goal_planning.TRIGGER_REPLAN
        )
        detail["outcome"] = "failed"
        detail["reason"] = REASON_THRESHOLD_EXCEEDED
        detail["goal_status"] = record.status if record else None
        detail["adjustments"].append(
            f"failure_replan:{'enqueued' if enqueued else 'deduped'}"
        )
        return detail

    current.status = "in_progress"
    result = evaluate_criteria(current.criteria, facts)
    detail["observations"] = 1
    detail["criteria_result"] = result
    if result is None:
        detail["outcome"] = "skipped"
        current.last_observed_at = now
        _save_progress(plan.id, specs, now)
        return detail

    if result is True:
        current.status = "done"
        current.failure_note = None
        current.last_observed_at = now
        detail["outcome"] = "advanced"
        if _all_done(specs):
            detail.update(_complete(goal))
        _save_progress(plan.id, specs, now)
        return detail

    if current.last_observed_at != now:
        current.attempt_count += 1
    current.last_observed_at = now
    if current.attempt_count < settings.v2_autonomy_subgoal_failure_threshold:
        detail["outcome"] = "retrying"
        detail["attempt_count"] = current.attempt_count
        _save_progress(plan.id, specs, now)
        return detail

    current.status = "failed"
    current.failure_note = f"连续失败 {current.attempt_count} 次"
    detail["adjustments"].append("sub_goal_failed")
    if _has_executable(specs):
        detail["outcome"] = "skipped_ahead"
        detail["adjustments"].append("order_skip")
        _save_progress(plan.id, specs, now)
        return detail

    _save_progress(plan.id, specs, now)
    if goal_repository.count_plans(goal.id) < settings.v2_autonomy_planning_max_attempts:
        enqueued = goal_planning.enqueue_planning(
            goal.user_id, goal.id, goal_planning.TRIGGER_BLOCKED
        )
        detail["outcome"] = "replanning"
        detail["adjustments"].append(
            f"replan:{goal_planning.TRIGGER_BLOCKED}:"
            f"{'enqueued' if enqueued else 'deduped'}"
        )
        return detail
    record = goal_repository.fail_goal(goal.id, REASON_REPLAN_EXHAUSTED)
    _record_lifecycle(record or goal, "failed", REASON_REPLAN_EXHAUSTED, goal.id)
    detail["outcome"] = "failed"
    detail["reason"] = REASON_REPLAN_EXHAUSTED
    detail["goal_status"] = record.status if record else None
    return detail


def advance_user_goals(user_id: str, facts: dict, now: datetime) -> dict:
    """编排入口：active plans 全量推进（观察先于执行尝试）。"""
    settings = get_settings()
    pairs = goal_repository.list_active_plans(user_id)
    if not pairs:
        return {"status": "ok", "goals": 0, "results": []}
    results = []
    for goal, plan in pairs:
        try:
            results.append(advance_goal(goal, plan, facts, now))
        except Exception:
            logger.exception("goal 推进失败（goal=%s）", goal.id)
            results.append({"goal_id": goal.id, "outcome": "error"})
    return {"status": "ok", "goals": len(results), "results": results}
