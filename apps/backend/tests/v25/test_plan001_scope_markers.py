"""PLAN-001 范围标记：本任务**不得**预埋 PLAN-002 ~ PLAN-005 的产物。

这些断言是「只做 PLAN-001 范围」红线（Task Detail §1.2 Non-Scope、§10.3「无代码骨架污染」）
的可执行形式，属**有意的契约变更留痕**：后续任务落地对应产物时必须**显式更新本模块**，
更新动作本身就是「范围越界已评审」的证据，而非本模块回归失败。

| 标记 | 归属 | 落地时的动作 |
|---|---|---|
| `v25_*` Flag 与参数 | PLAN-002（`app/core/settings/plan.py`） | 删除 `test_no_v25_flag_is_pre_embedded` |
| `SubGoalSpec` 7 个新字段 | PLAN-002 | 删除对应断言并改为新字段快照 |
| `GoalPlanRecord` 4 个新字段 | PLAN-002 | 同上 |
| `app/models/plan.py` | PLAN-002 | 删除 `test_plan_002_artifacts_are_absent` 中该项 |
| 计划域引擎模块 | PLAN-003 / PLAN-004 / PLAN-005 | 删除 `test_plan_execution_modules_are_absent` |
"""

from pathlib import Path

from app.core.settings import Settings, get_settings
from app.models.goal import CRITERION_FACT_SOURCES, GoalPlanRecord, SubGoalSpec
from app.services.planning import goal_contract

PLAN_002_SETTINGS_FIELDS = (
    "v25_planning_enabled",
    "v25_plan_tool_required",
    "v25_plan_revision_budget",
    "v25_plan_max_steps",
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


def test_no_v25_flag_is_pre_embedded():
    assert [name for name in Settings.model_fields if name.startswith("v25_")] == []
    assert [name for name in dir(get_settings()) if name.startswith("v25_")] == []
    assert not (_backend_root() / "app" / "core" / "settings" / "plan.py").exists()


def test_sub_goal_spec_carries_no_plan_002_fields_yet():
    fields = tuple(SubGoalSpec.model_fields)
    for field in PLAN_002_SUB_GOAL_FIELDS:
        assert field not in fields, field
    assert len(fields) == 12


def test_goal_plan_record_carries_no_plan_002_fields_yet():
    fields = tuple(GoalPlanRecord.model_fields)
    for field in PLAN_002_GOAL_PLAN_FIELDS:
        assert field not in fields, field
    assert fields == (
        "id",
        "goal_id",
        "version",
        "status",
        "sub_goals",
        "rejection_reason",
        "created_at",
        "updated_at",
    )


def test_plan_domain_model_module_is_absent():
    assert not (_backend_root() / "app" / "models" / "plan.py").exists()


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


def test_plan_002_third_criterion_source_is_not_pre_embedded():
    assert CRITERION_FACT_SOURCES == ("world", "state", "memory")
