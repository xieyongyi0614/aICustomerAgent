"""PLAN-007 单测共享构造：触发信号 / 策略快照 / 计划事实包 / 分层目标 / 推进审计。

只做构造，不做断言（与 `plan004_support.py` / `plan005_support.py` 同款纪律）。
本任务的装配点只读三处既有入口（`goal_repository.list_active_plans` / `PlanScheduler`
纯函数 / `decision_repository` 的 `goal_lifecycle` 审计行），故构造面也只覆盖这三处的
输入形状：分层（非分层）目标落库、计划落库、`PlanAdvance` 审计行落库。
"""

from datetime import datetime
from types import SimpleNamespace

from app.models.autonomy import TriggerSignal
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.models.observability import DecisionKind, DecisionRecord
from app.models.plan import PlanAdvance
from app.repositories import decision_repository, goal_repository
from app.engines import autonomy as autonomy_policy

NOW = datetime(2026, 9, 16, 12, 0, 0)

USER = "plan7-user"
GOAL_ID = "plan7-goal"
PLAN_ID = "plan7-plan"
SESSION_ID = "plan7-session"

REMINDER_ACTION = "create_reminder"
"""自治产行动分支唯一的动作身份（`PROACTIVE_ACTION_MAP["check_in"]`）——「同动作」用例用。"""

OTHER_ACTION = "send_notification"
"""与自治产行动不同的合法动作身份（`ACTION_TYPES` 成员）——「不同动作」用例用。"""

CHECK_IN_INTENTION = "check_in"

STEP_DEFAULT_CAPABILITY = REMINDER_ACTION


def spec(index: int = 1, **overrides) -> SubGoalSpec:
    """步骤构造器：缺省 `create_reminder` 一步（判据与能力一致），任意字段可覆盖。"""
    capability = overrides.pop("capability", STEP_DEFAULT_CAPABILITY)
    payload = {
        "index": index,
        "description": overrides.pop("description", f"步骤{index}"),
        "capability": capability,
        "params": overrides.pop("params", {}),
        "criteria": overrides.pop(
            "criteria", {"type": "action_succeeded", "capability": capability}
        ),
    }
    payload.update(overrides)
    return SubGoalSpec.model_validate(payload)


def plan(
    specs: list[SubGoalSpec],
    *,
    goal_id: str = GOAL_ID,
    version: int = 1,
    status: str = "active",
    plan_id: str = PLAN_ID,
    updated_at: datetime | None = None,
) -> GoalPlanRecord:
    """内存计划（零落库）：字段快照与调制用例只需形状。"""
    return GoalPlanRecord(
        id=plan_id,
        goal_id=goal_id,
        version=version,
        status=status,
        sub_goals=list(specs),
        created_at=NOW,
        updated_at=updated_at or NOW,
    )


def seed_plan(
    goal_id: str,
    specs: list[SubGoalSpec] | None = None,
    *,
    version: int = 1,
    plan_id: str = PLAN_ID,
    updated_at: datetime | None = None,
) -> GoalPlanRecord:
    """落库一份 active 计划（既有 `goal_repository.create_plan`，零改动）。

    `updated_at` 可控——「多计划取最近 `updated_at`」用例需要确定性排序输入。
    """
    record = plan(
        specs if specs is not None else [spec(1)],
        goal_id=goal_id,
        version=version,
        plan_id=plan_id,
        updated_at=updated_at,
    )
    return goal_repository.create_plan(record)


def signal(
    type: str = "conversation_inactivity",
    *,
    user_id: str = USER,
    dedupe_key: str = "plan7:inactivity",
) -> TriggerSignal:
    """触发信号构造器（P3 为缺省：`scheduled_followup` / `action_due` 为 P0 / P1）。"""
    return TriggerSignal(
        type=type, user_id=user_id, detected_at=NOW, dedupe_key=dedupe_key
    )


ACT_SNAPSHOT_DEFAULTS: dict = {
    "last_proactive_at": None,
    "attempt_count": 0,
    "intimacy": 0.62,
    "selected_goal_type": "user_care",
    "goal_degraded": False,
    "extra_flags": {"goal_id": GOAL_ID},
}


def act_snapshot(**overrides) -> autonomy_policy.PolicySnapshot:
    """能走完全部八步闸门的快照（`act` 基线），任意字段可覆盖。"""
    values = dict(ACT_SNAPSHOT_DEFAULTS)
    values.update(overrides)
    return autonomy_policy.PolicySnapshot(**values)


PLAN_FACTS_DEFAULTS: dict = {
    "active_goal_id": GOAL_ID,
    "plan_version": 2,
    "current_step": 3,
    "current_action_type": REMINDER_ACTION,
    "steps_total": 4,
    "blocked_steps": 0,
    "last_advanced_at": "2026-09-15T20:10:00",
}


def plan_facts(**overrides) -> dict:
    """计划事实包构造器（七键缺省齐全，任意键可覆盖为 `None` / 其他取值）。"""
    values = dict(PLAN_FACTS_DEFAULTS)
    values.update(overrides)
    return values


def barrier_snapshot(plan_overrides: dict | None = None, **snapshot_overrides) -> dict:
    """「计划推进中」的策略快照：快照字段用关键字参数，**事实包字段**用 `plan_overrides`。

    两段输入刻意分开——否则「覆盖当前步动作」会静默落进快照字段，用例会测错对象。
    """
    return act_snapshot(
        plan_facts=plan_facts(**(plan_overrides or {})), **snapshot_overrides
    )


def seed_layered_goal(
    user_id: str = USER,
    *,
    layer: str = "long_term",
    domain: str = "personal",
    description: str = "规划一次旅行",
    priority: int = 3,
):
    """分层目标落库（既有 `create_hierarchical_goal`，零改动）——`goal_compile` 候选面用。"""
    return goal_repository.create_hierarchical_goal(
        user_id, layer, domain, description, priority
    )


def bridge_ctx(now: datetime | None = None, **extra):
    """执行桥的鸭子类型上下文：缺省只给时刻（步骤无 `tool_id` 时不做面复核）。"""
    return SimpleNamespace(now=now or NOW, **extra)


def seed_advance(
    goal_id: str,
    *,
    user_id: str = USER,
    decision: str = "advanced",
    at: datetime = NOW,
    plan_id: str = PLAN_ID,
    plan_version: int = 1,
) -> DecisionRecord:
    """落一条 `PlanAdvance` 审计行（`kind='goal_lifecycle'`，与 `PlanObserver` 同形）。

    这是 `last_advanced_at` 的唯一读取入口的输入形状：`input_snapshot` 即
    `PlanAdvance.model_dump(mode="json")`（`at` 为 ISO 字符串）。
    """
    advance = PlanAdvance(
        goal_id=goal_id,
        plan_id=plan_id,
        plan_version=plan_version,
        decision=decision,
        reason="plan_step_advanced",
        at=at,
    )
    record = DecisionRecord(
        kind=DecisionKind.GOAL_LIFECYCLE,
        user_id=user_id,
        conversation_id=None,
        action_id=None,
        trigger="plan_observer",
        input_snapshot=advance.model_dump(mode="json"),
        decision=advance.decision,
        reason=advance.reason,
    )
    decision_repository.save(record)
    return record
