"""PLAN-001 ↔ PLAN-002 范围标记：本包内「已落地」与「仍不得预埋」的可判定分界。

这些断言是「只做本任务范围」红线（Task Detail §1.2 Non-Scope、§10.3「无代码骨架污染」）
的可执行形式，属**有意的契约变更留痕**：后续任务落地对应产物时必须**显式更新本模块**，
更新动作本身就是「范围越界已评审」的证据，而非本模块回归失败。

| 标记 | 归属 | 状态 |
|---|---|---|
| `v25_*` Flag 与参数 | PLAN-002 | ✅ 已落地（13 Flag + 14 参数，总闸默认 off） |
| `SubGoalSpec` 7 个新字段 | PLAN-002 | ✅ 已落地（19 字段快照） |
| `GoalPlanRecord` 4 个新字段 | PLAN-002 | ✅ 已落地（12 字段快照） |
| `CRITERION_FACT_SOURCES` 第四值 | PLAN-002 | ✅ 已落地（四值） |
| `app/models/plan.py` / `settings/plan.py` | PLAN-002 | ✅ 已落地 |
| 计划域装配 / 引擎 / 拆解模块 | PLAN-003 / PLAN-004 | ⛔ 仍不得预埋 |
| 计划域调度 / 执行 / 观测 / 修订模块 | PLAN-005 | ⛔ 仍不得预埋 |

PLAN-002 落地时的改动仅限本模块中「尚不存在」类断言翻转为「已存在」类断言 + 新增字段
快照（原计划见 PLAN-001 Task Detail 的标记表）。
"""

from pathlib import Path

from app.core.settings import Settings, get_settings
from app.models.goal import (
    CRITERION_FACT_SOURCES,
    GoalPlanRecord,
    SubGoalSpec,
)
from app.services.planning import goal_contract

PLAN_002_SETTINGS_FLAGS = (
    "v25_planning_enabled",
    "v25_plan_context_enabled",
    "v25_plan_step_binding_enabled",
    "v25_plan_scheduler_enabled",
    "v25_plan_execution_enabled",
    "v25_plan_observation_enabled",
    "v25_plan_revision_enabled",
    "v25_plan_memory_enabled",
    "v25_plan_reflection_enabled",
    "v25_plan_world_feedback_enabled",
    "v25_plan_autonomy_enabled",
    "v25_plan_tool_required",
    "v25_plan_debug_enabled",
)

PLAN_002_SETTINGS_PARAMS = (
    "v25_plan_max_steps",
    "v25_plan_max_depth",
    "v25_plan_step_max_attempts",
    "v25_plan_revision_budget",
    "v25_plan_ttl_hours",
    "v25_plan_step_cooldown_minutes",
    "v25_plan_observation_window_minutes",
    "v25_plan_context_memory_limit",
    "v25_plan_context_insight_limit",
    "v25_plan_llm_profile",
    "v25_plan_replan_min_confidence",
    "v25_plan_reflection_min_samples",
    "v25_plan_memory_importance_floor",
    "v25_plan_context_digest_enabled",
)

PLAN_002_SUB_GOAL_FIELDS = (
    "tool_id",
    "kind",
    "retry_policy",
    "on_failure",
    "expected_effects",
    "observation_keys",
    "binding_reason",
)

PLAN_002_GOAL_PLAN_FIELDS = (
    "trigger",
    "context_digest",
    "revision_of",
    "evidence_refs",
)

PLAN_005_EXECUTION_MODULES = (
    "scheduler.py",
    "executor_bridge.py",
    "observer.py",
    "revision.py",
    "revision_listener.py",
)

PLAN_003_004_MODULES = ("context.py", "engine.py", "decompose.py")


def _backend_root() -> Path:
    return Path(goal_contract.__file__).parents[3]


def _planning_dir() -> Path:
    return Path(goal_contract.__file__).parent


def test_plan_002_settings_are_embedded_and_the_master_stays_off():
    settings = get_settings()
    declared = {name for name in Settings.model_fields if name.startswith("v25_")}
    assert declared == set(PLAN_002_SETTINGS_FLAGS) | set(PLAN_002_SETTINGS_PARAMS)
    assert len(PLAN_002_SETTINGS_FLAGS) == 13
    assert len(PLAN_002_SETTINGS_PARAMS) == 14
    assert settings.v25_planning_enabled is False
    assert settings.v25_plan_tool_required is True
    assert (_backend_root() / "app" / "core" / "settings" / "plan.py").exists()


def test_sub_goal_spec_carries_the_plan_002_fields_in_declared_order():
    fields = tuple(SubGoalSpec.model_fields)
    assert fields[:12] == (
        "index",
        "description",
        "capability",
        "params",
        "criteria",
        "depends_on",
        "parent_index",
        "status",
        "attempt_count",
        "last_observed_at",
        "last_attempt_at",
        "failure_note",
    )
    assert fields[12:] == PLAN_002_SUB_GOAL_FIELDS
    assert len(fields) == 19


def test_goal_plan_record_carries_the_plan_002_fields_in_declared_order():
    assert tuple(GoalPlanRecord.model_fields) == (
        "id",
        "goal_id",
        "version",
        "status",
        "sub_goals",
        "rejection_reason",
        "created_at",
        "updated_at",
    ) + PLAN_002_GOAL_PLAN_FIELDS


def test_plan_domain_model_module_is_present():
    assert (_backend_root() / "app" / "models" / "plan.py").exists()


def test_plan_execution_modules_are_absent():
    present = [name for name in PLAN_005_EXECUTION_MODULES if (_planning_dir() / name).exists()]
    assert present == []


def test_planning_engine_modules_are_absent():
    present = [name for name in PLAN_003_004_MODULES if (_planning_dir() / name).exists()]
    assert present == []


def test_planning_package_holds_only_the_declaration_module():
    modules = sorted(
        path.name for path in _planning_dir().rglob("*.py") if "__pycache__" not in path.parts
    )
    assert modules == ["__init__.py", "goal_contract.py"]


def test_plan_002_fourth_criterion_source_is_embedded():
    assert CRITERION_FACT_SOURCES == ("world", "state", "memory", "tool")
