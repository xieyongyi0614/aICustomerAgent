"""PLAN-005 单测共享构造：计划步骤 / 计划 / 目标 / 鸭子类型 ctx / 动作台账。

只做构造，不做断言（与 `plan004_support.py` 同款纪律）。`ctx` 用 `SimpleNamespace`
注入——`PlanScheduler.blocked_reason` 只消费 `tool_surface` / `now` / `step_cooldown_minutes`
三个投影，故调度单测零 DB、零世界、零 LLM（`PlanScheduler` / `PlanRevisionPolicy` 是纯函数，
其输入必须由调用方注入，不得自行 `get_settings()`）。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.models.action import ActionRecord
from app.models.goal import GoalPlanRecord, GoalRecord, SubGoalSpec
from app.models.tool import ToolSurface

NOW = datetime(2026, 9, 16, 12, 0, 0)

GOAL_ID = "plan5-goal"
PLAN_ID = "plan5-plan"
USER_ID = "plan5-user"

REMINDER_CREATE = "builtin.reminder.create"
CHANNEL_SEND = "channel.feishu.send"

STEP_MAX_ATTEMPTS = 2
COOLDOWN_MINUTES = 30


def spec(index: int = 1, **overrides) -> SubGoalSpec:
    """步骤构造器：默认 `create_reminder` 一步、判据与能力一致，任意字段可用 overrides 覆盖。"""
    capability = overrides.pop("capability", "create_reminder")
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


def plan(specs, *, goal_id: str = GOAL_ID, version: int = 1, status: str = "active"):
    """内存计划（零落库）：调度 / 修订 / 失败矩阵用例只需形状，不需 `goal_plans` 行。"""
    return GoalPlanRecord(
        id=PLAN_ID,
        goal_id=goal_id,
        version=version,
        status=status,
        sub_goals=list(specs),
        created_at=NOW,
        updated_at=NOW,
    )


def goal(**overrides) -> GoalRecord:
    """内存目标（零落库）：执行桥与观测的调用方身份。"""
    payload = {
        "id": GOAL_ID,
        "user_id": USER_ID,
        "type": "user_care",
        "description": "规划一次旅行",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return GoalRecord.model_validate(payload)


def surface(*tool_ids: str, run_kind: str = "autonomous_tick") -> ToolSurface:
    return ToolSurface(run_kind=run_kind, tool_ids=tuple(tool_ids))


def ctx(*tool_ids: str, now: datetime | None = NOW, cooldown: int | None = None):
    """鸭子类型调度上下文：缺省给面与时刻，冷却缺省**不判**（§4.5 的 `cooldown` 需显式注入）。"""
    return SimpleNamespace(
        tool_surface=surface(*tool_ids),
        now=now,
        step_cooldown_minutes=cooldown,
    )


def bare_ctx(now: datetime | None = NOW):
    """无工具面 / 无冷却值的上下文：验证「缺省即不判该项」的降级纪律。"""
    return SimpleNamespace(now=now)


def action_record(
    *,
    status: str = "succeeded",
    action_type: str = "create_reminder",
    step_status: str | None = "succeeded",
    steps: list[dict] | None = None,
    failure_kind: str | None = None,
    gate_reason: str | None = None,
    attempt: int = 1,
    dedupe_key: str = "",
    goal_id: str = GOAL_ID,
    record_id: str = "action-1",
    user_id: str = USER_ID,
) -> ActionRecord:
    """动作台账构造器：缺省一条单步成功记录（`steps[0].result` 为 V2.4.0 `ToolResult` 形状）。"""
    if steps is None:
        steps = [
            {
                "index": 1,
                "capability": "reminder",
                "action": "create",
                "params": {},
                "status": step_status,
                "tool_id": REMINDER_CREATE,
                "result": {
                    "status": step_status,
                    "effects": [{"kind": "world", "ref": "ev-1", "reversible": True}],
                    "observations": {"reminder_id": "ev-1"},
                    "failure_kind": failure_kind,
                    "usage": {"duration_ms": 12},
                },
                "duration_ms": 12,
            }
        ]
    return ActionRecord(
        id=record_id,
        user_id=user_id,
        goal_id=goal_id,
        action_type=action_type,
        status=status,
        gate_reason=gate_reason,
        steps=steps,
        dedupe_key=dedupe_key,
        attempt=attempt,
        created_at=NOW,
        updated_at=NOW,
    )


def tool_step(observations: dict, *, status: str = "succeeded") -> dict:
    """一条带 `ToolResult.observations` 的步记录（白名单裁剪用例的输入）。"""
    return {
        "index": 1,
        "capability": "reminder",
        "action": "create",
        "params": {},
        "status": status,
        "tool_id": REMINDER_CREATE,
        "result": {"status": status, "observations": dict(observations)},
        "duration_ms": 5,
    }


def last_attempt_at(minutes_ago: int) -> datetime:
    """相对 `NOW` 的尝试时刻（冷却判定的可判定输入）。"""
    return NOW - timedelta(minutes=minutes_ago)
