"""PLAN-012 版本验收共享构造：面试准备四步样例、终态路径与 Flag 矩阵基座。

只做构造，不做断言（与 `plan005_support.py` 同款纪律）。样例取自
architecture.md §6.2「后天有个面试，帮我准备一下」的四步拆解。
"""

from datetime import datetime

from app.models.goal import GoalPlanRecord, GoalRecord, SubGoalSpec
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK

NOW = datetime(2026, 9, 16, 12, 0, 0)
USER = "plan12-user"
SESSION = "plan12-session"
GOAL_ID = "plan12-interview"
PLAN_ID = "plan12-plan"

REMINDER_CREATE = "builtin.reminder.create"
MEMORY_SAVE = "builtin.memory.save"
ENV_QUERY = "world.env.query"
SEARCH_QUERY = "builtin.search.query"

INTERVIEW_STEPS: tuple[dict, ...] = (
    {
        "index": 1,
        "description": "记下后天面试的事",
        "capability": "remember_fact",
        "tool_id": MEMORY_SAVE,
        "kind": "tool",
        "params": {"content": "后天有面试"},
        "criteria": {
            "type": "action_succeeded",
            "capability": "remember_fact",
            "fact_source": "tool",
        },
        "observation_keys": ["memory_id"],
    },
    {
        "index": 2,
        "description": "查一下后天的天气",
        "capability": "query_environment",
        "tool_id": ENV_QUERY,
        "kind": "tool",
        "params": {"kind": "weather"},
        "criteria": {
            "type": "field_equals",
            "fact_source": "tool",
            "path": "condition",
            "value": "ok",
        },
        "observation_keys": ["condition"],
    },
    {
        "index": 3,
        "description": "提前一晚提醒准备",
        "capability": "create_reminder",
        "tool_id": REMINDER_CREATE,
        "kind": "tool",
        "depends_on": [1],
        "params": {"content": "明天面试，今晚准备一下"},
        "criteria": {
            "type": "action_succeeded",
            "capability": "create_reminder",
            "fact_source": "tool",
        },
        "observation_keys": ["reminder_id"],
    },
    {
        "index": 4,
        "description": "面试当天早上提醒",
        "capability": "create_reminder",
        "tool_id": REMINDER_CREATE,
        "kind": "tool",
        "depends_on": [1],
        "params": {"content": "今天面试，加油"},
        "criteria": {
            "type": "action_succeeded",
            "capability": "create_reminder",
            "fact_source": "tool",
        },
        "observation_keys": ["reminder_id"],
    },
)

FULL_CHAIN_ENVS = {
    "PLANNING_ENABLED": "true",
    "PLAN_CONTEXT_ENABLED": "true",
    "PLAN_STEP_BINDING_ENABLED": "true",
    "PLAN_SCHEDULER_ENABLED": "true",
    "PLAN_EXECUTION_ENABLED": "true",
    "PLAN_OBSERVATION_ENABLED": "true",
    "PLAN_REVISION_ENABLED": "true",
    "PLAN_MEMORY_ENABLED": "true",
    "PLAN_REFLECTION_ENABLED": "true",
    "PLAN_WORLD_FEEDBACK_ENABLED": "true",
    "PLAN_AUTONOMY_ENABLED": "true",
    "PLAN_DEBUG_ENABLED": "true",
    "TOOL_SYSTEM_ENABLED": "true",
    "ACTION_ENABLED": "true",
    "WORLD_ENABLED": "false",
    "OBSERVABILITY_PERSIST_ENABLED": "false",
}

V25_FLAG_NAMES: tuple[str, ...] = (
    "planning_enabled",
    "plan_context_enabled",
    "plan_step_binding_enabled",
    "plan_scheduler_enabled",
    "plan_execution_enabled",
    "plan_observation_enabled",
    "plan_revision_enabled",
    "plan_memory_enabled",
    "plan_reflection_enabled",
    "plan_world_feedback_enabled",
    "plan_autonomy_enabled",
    "plan_tool_required",
    "plan_debug_enabled",
)

V25_DEFAULTS: dict[str, bool] = {
    "planning_enabled": False,
    "plan_context_enabled": False,
    "plan_step_binding_enabled": False,
    "plan_scheduler_enabled": False,
    "plan_execution_enabled": False,
    "plan_observation_enabled": False,
    "plan_revision_enabled": False,
    "plan_memory_enabled": False,
    "plan_reflection_enabled": False,
    "plan_world_feedback_enabled": False,
    "plan_autonomy_enabled": False,
    "plan_tool_required": True,
    "plan_debug_enabled": False,
}

GATE_IDS: tuple[str, ...] = (
    "G-COMPAT",
    "G-PLAN",
    "G-DECOMPOSE",
    "G-BIND",
    "G-EXEC",
    "G-RETRY",
    "G-WORLD",
    "G-MEMORY",
    "G-REFLECT",
    "G-BOUNDARY",
    "G-ZERO-MIGRATION",
)

Q_IDS: tuple[str, ...] = tuple(f"Q{i}" for i in range(1, 11))

RED_LINE_IDS: tuple[str, ...] = tuple(f"红线{i}" for i in range(1, 11))


def interview_steps(**overrides) -> list[dict]:
    steps = [dict(item) for item in INTERVIEW_STEPS]
    for step in steps:
        step.update(overrides)
    return steps


def interview_specs() -> list[SubGoalSpec]:
    return [SubGoalSpec.model_validate(item) for item in interview_steps()]


def interview_plan(*, version: int = 1, status: str = "active") -> GoalPlanRecord:
    return GoalPlanRecord(
        id=PLAN_ID,
        goal_id=GOAL_ID,
        version=version,
        status=status,
        sub_goals=interview_specs(),
        created_at=NOW,
        updated_at=NOW,
    )


def interview_goal(**overrides) -> GoalRecord:
    payload = {
        "id": GOAL_ID,
        "user_id": USER,
        "type": "user_care",
        "description": "后天有个面试，帮我准备一下",
        "layer": "short_term",
        "domain": "personal",
        "status": "active",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return GoalRecord.model_validate(payload)


def interview_context(*, tool_ids: tuple[str, ...] | None = None) -> PlanContext:
    from app.services.planning import context as plan_context
    from app.core.settings import get_settings

    return PlanContext(
        goal=interview_goal(),
        tool_surface=ToolSurface(
            run_kind=RUN_KIND_AUTONOMOUS_TICK,
            tool_ids=tool_ids
            or (MEMORY_SAVE, ENV_QUERY, REMINDER_CREATE, SEARCH_QUERY),
        ),
        budget=plan_context.plan_budget(get_settings()),
    )


def apply_full_chain(override_settings) -> None:
    override_settings(**{k.lower(): v for k, v in FULL_CHAIN_ENVS.items()})
