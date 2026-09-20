"""PLAN-002 I6 / I7：静态分层断言与零迁移断言（Task Detail §8 Step 5、§10.3）。

两套断言合一处的原因：二者都是「本任务不得越界」的静态可判定形式——模型层不得反向依赖
上层，数据库不得新增任何结构。
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint

from app.core.db import Base, GoalPlanRow
from app.models import goal as goal_model
from app.models.observability import DecisionKind
from app.models.plan import PlanContext
from app.services.planning import goal_contract

from . import _plan_scan as scan

BACKEND_ROOT = Path(goal_contract.__file__).parents[3]

PLAN_MODEL_PATH = BACKEND_ROOT / "app" / "models" / "plan.py"
GOAL_MODEL_PATH = BACKEND_ROOT / "app" / "models" / "goal.py"
PLAN_SETTINGS_PATH = BACKEND_ROOT / "app" / "core" / "settings" / "plan.py"

MODEL_LAYER_MODULES = (PLAN_MODEL_PATH, GOAL_MODEL_PATH)

FORBIDDEN_LAYER_PREFIXES = ("app.repositories", "app.services", "app.application")

PLAN_MODEL_ALLOWED_APP_IMPORTS = (
    "app.models.goal",
    "app.models.reflection",
    "app.models.tool",
    "app.models.world",
    "app.models.world_simulation",
)

PLAN_MODEL_FORBIDDEN_IO_TOKENS = (
    "SessionLocal",
    "session.execute",
    "session.add",
    "session.commit",
    "session.query",
    "session.flush",
    "requests.",
    "httpx.",
    "get_llm",
    "build_structured_chain",
    "llm_gateway",
    "ChatOpenAI",
    "subprocess",
    "urlopen",
)

GOAL_PLAN_COLUMNS_SNAPSHOT = (
    "created_at",
    "goal_id",
    "id",
    "rejection_reason",
    "status",
    "sub_goals",
    "updated_at",
    "version",
)

PLAN_002_GOAL_PLAN_FIELDS = (
    "trigger",
    "context_digest",
    "revision_of",
    "evidence_refs",
)

MIGRATION_HEAD = "0050"

PLAN_TABLES_SNAPSHOT = ("daily_plans", "goal_plans")

VERSIONS_DIR = BACKEND_ROOT / "migrations" / "versions"


def _imported_prefix_hits(path: Path, prefixes: tuple[str, ...]) -> list[str]:
    return sorted(
        module
        for module in scan.imported_modules(path)
        for prefix in prefixes
        if module == prefix or module.startswith(prefix + ".")
    )


@pytest.mark.parametrize("path", MODEL_LAYER_MODULES, ids=lambda path: path.name)
def test_i6_model_layer_has_no_repository_service_or_application_dependency(path):
    assert _imported_prefix_hits(path, FORBIDDEN_LAYER_PREFIXES) == []


def test_i6_plan_model_imports_only_model_layer_modules():
    app_imports = sorted(
        module
        for module in scan.imported_modules(PLAN_MODEL_PATH)
        if module.startswith("app.")
    )
    assert app_imports
    assert set(app_imports) <= set(PLAN_MODEL_ALLOWED_APP_IMPORTS)
    assert "app.core.db" not in app_imports


def test_i6_plan_model_has_no_io_execution_or_llm_surface():
    assert scan.code_violations(PLAN_MODEL_PATH, PLAN_MODEL_FORBIDDEN_IO_TOKENS) == []
    assert scan.simple_call_names(PLAN_MODEL_PATH) & {
        "open",
        "exec",
        "eval",
        "__import__",
    } == set()


def test_i6_plan_model_declares_values_and_properties_only():
    assert sorted(scan.function_definitions(PLAN_MODEL_PATH)) == [
        "is_bounded",
        "is_terminal",
        "passed",
    ]
    assert scan.simple_call_names(PLAN_MODEL_PATH) <= {"Field", "frozenset", "get_args"}
    assert scan.sort_key_sources(PLAN_MODEL_PATH) == []


def test_i6_plan_settings_module_declares_no_io_surface():
    assert _imported_prefix_hits(PLAN_SETTINGS_PATH, FORBIDDEN_LAYER_PREFIXES) == []
    assert scan.code_violations(PLAN_SETTINGS_PATH, ("SessionLocal", "get_llm")) == []


def test_i6_plan_context_hard_dependency_is_the_tool_surface_type():
    annotations = {
        name: field.annotation for name, field in PlanContext.model_fields.items()
    }
    assert "ToolSurface" in str(annotations["tool_surface"])
    assert PlanContext.model_fields["tool_surface"].is_required()
    assert PlanContext.model_fields["goal"].is_required()
    assert PlanContext.model_fields["budget"].is_required()


def test_i7_migration_chain_head_is_still_0050():
    numbered = sorted(
        int(match.group(1))
        for path in VERSIONS_DIR.glob("*.py")
        if (match := re.match(r"(\d+)_", path.name))
    )
    assert numbered, "未找到迁移文件"
    assert f"{max(numbered):04d}" == MIGRATION_HEAD
    assert max(numbered) == 50


def test_i7_goal_plans_table_carries_no_new_column():
    assert tuple(sorted(GoalPlanRow.__table__.c.keys())) == GOAL_PLAN_COLUMNS_SNAPSHOT
    for field in PLAN_002_GOAL_PLAN_FIELDS:
        assert field not in GoalPlanRow.__table__.c, field
        assert field in goal_model.GoalPlanRecord.model_fields, field


def test_i7_goal_plans_check_constraint_and_indexes_are_unchanged():
    check_names = tuple(
        sorted(
            constraint.name
            for constraint in GoalPlanRow.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        )
    )
    assert check_names == ("ck_goal_plans_status",)
    index_names = tuple(sorted(index.name for index in GoalPlanRow.__table__.indexes))
    assert index_names == ("idx_goal_plans_goal_status",)
    unique_names = {constraint.name for constraint in GoalPlanRow.__table__.constraints}
    assert "uq_goal_plans_goal_version" in unique_names


def test_i7_decision_kind_check_value_set_is_unchanged():
    assert tuple(kind.value for kind in DecisionKind) == (
        "proactive_autonomy",
        "turn_goal",
        "turn_intention",
        "turn_behavior",
        "goal_lifecycle",
    )


def test_i7_no_new_plan_table_exists():
    plan_tables = tuple(sorted(name for name in Base.metadata.tables if "plan" in name))
    assert plan_tables == PLAN_TABLES_SNAPSHOT


def test_plan_002_adds_no_module_to_the_planning_package():
    """原 PLAN-002 断言「计划包只有声明模块」；PLAN-003 ~ PLAN-005 与 PLAN-009 落地后按同一纪律更新清单。"""
    names = sorted(
        path.name
        for path in scan.PLANNING_PACKAGE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert names == [
        "__init__.py",
        "context.py",
        "decompose.py",
        "engine.py",
        "executor_bridge.py",
        "goal_contract.py",
        "memory_policy.py",
        "observer.py",
        "revision.py",
        "revision_listener.py",
        "scheduler.py",
    ]
