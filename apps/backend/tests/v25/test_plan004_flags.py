"""PLAN-004 阶段策略位与回归断言（Task Detail §8 Step 6 / §9.2 I8~I11 / §9.3 S6）。

语义反转（v25 去门控）：绑定子闸 `plan_step_binding_enabled` 已删，绑定生效只取决于
保留的策略位 `plan_tool_required`（默认 on）。本模块**不导入** `plan004_binding_on`
夹具：off 态用例显式把策略位钉到 `false`（H.6 裁决保留的合法策略态），「off 时零绑定、
落库形状与 V2.4.0 逐字节一致」继续被钉住。
"""

import re
from pathlib import Path

from tests.support.schema_pins import MIGRATION_HEAD
from app.models.goal import validate_sub_goals
from app.repositories import goal_repository
from app.services.planning import decompose as decompose_mod

from .plan004_support import (
    REMINDER_CREATE,
    builtin_registry,
    decompose,
    make_ctx,
    make_goal,
    proposal,
    settings,
    step,
    tool_criteria,
)


VERSIONS_DIR = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"

EXTENSION_FIELDS = (
    "tool_id",
    "kind",
    "retry_policy",
    "on_failure",
    "expected_effects",
    "observation_keys",
    "binding_reason",
)

V2_4_0_DEFAULTS = {
    "tool_id": None,
    "kind": "tool",
    "retry_policy": "once",
    "on_failure": "skip",
    "expected_effects": (),
    "observation_keys": (),
    "binding_reason": None,
}


class TestBindingSubGateOff:
    """I8 / S6（策略位 off 态）：`plan_tool_required=false` → 不写 `tool_id`，绑定只在执行期发生。"""

    def test_no_binding_and_no_derived_fields_are_written(self, override_settings):
        override_settings(plan_tool_required="false")
        result = decompose(step(1), step(2, depends_on=[1]))
        assert result.bindings == []
        assert result.binding_errors == []
        assert result.passed
        for spec in result.steps:
            for field_name, default in V2_4_0_DEFAULTS.items():
                assert getattr(spec, field_name) == default, (spec.index, field_name)

    def test_llm_tool_id_hint_is_passed_through_untouched(self, override_settings):
        """退化为 V2.4.0：提示原样保留（绑定与否是执行期 `ToolSelector` 的事）。"""
        override_settings(plan_tool_required="false")
        result = decompose(step(1, tool_id=REMINDER_CREATE))
        assert [spec.tool_id for spec in result.steps] == [REMINDER_CREATE]
        assert result.steps[0].binding_reason is None

    def test_landed_shape_is_byte_identical_to_the_v2_4_0_parse(self, override_settings):
        """I10：off 时 `sub_goals` 落库形状与 V2.4.0（= 既有解析产物）逐字节一致。"""
        override_settings(plan_tool_required="false")
        raw = [
            step(1),
            step(2, depends_on=[1]),
            step(3, capability="remember_fact", params={"fact": "x"}, parent_index=1),
        ]
        expected = validate_sub_goals([dict(item) for item in raw], max_depth=2)
        result = decompose(*raw)
        assert [spec.model_dump_json() for spec in result.steps] == [
            spec.model_dump_json() for spec in expected
        ]
        assert [spec.model_dump() for spec in result.steps] == [
            spec.model_dump() for spec in expected
        ]

    def test_declared_extension_fields_are_not_overwritten_when_off(self, override_settings):
        """off 时阶段②整段跳过：声明过的字段也不改写（含 observation_keys 的声明权威）。"""
        override_settings(plan_tool_required="false")
        result = decompose(
            step(
                1,
                tool_id=REMINDER_CREATE,
                kind="observe",
                retry_policy="none",
                on_failure="continue",
                observation_keys=["condition"],
                criteria=tool_criteria("condition"),
            )
        )
        spec = result.steps[0]
        assert spec.kind == "observe"
        assert spec.retry_policy == "none"
        assert spec.on_failure == "continue"
        assert spec.observation_keys == ("condition",)
        assert spec.binding_reason is None


class TestToolRequiredOff:
    """I9：`plan_tool_required` off → 允许无面规划并退化为 V2.4.0 行为。"""

    def test_surface_less_planning_stays_unbound_without_errors(self, override_settings):
        override_settings(plan_tool_required="false")
        result = decompose(step(1), ctx=make_ctx())
        assert result.bindings == []
        assert result.binding_errors == []
        assert result.passed
        assert [spec.tool_id for spec in result.steps] == [None]

    def test_binding_follows_the_tool_required_policy_bit(self, override_settings):
        """绑定生效判据收敛为单一策略位（绑定子闸已删）：默认 on，显式 off 才退化。"""
        assert decompose_mod._binding_enabled(settings()) is True
        override_settings(plan_tool_required="false")
        assert decompose_mod._binding_enabled(settings()) is False

    def test_checked_in_registry_is_read_only_when_binding_is_active(self):
        result = decompose(
            step(1), ctx=make_ctx(REMINDER_CREATE), registry=builtin_registry()
        )
        assert result.steps[0].tool_id == REMINDER_CREATE


class TestQ4FreezeIsRecorded:
    """§10.3 Q4 冻结留痕：`fact_source="tool"` × `threshold_reached` 组合语义冻结为「拒绝」。"""

    def test_extended_reason_code_is_declared(self):
        assert decompose_mod.REASON_CRITERIA_UNSUPPORTED == "plan_criteria_unsupported"
        assert (
            decompose_mod.REASON_CRITERIA_UNSUPPORTED in decompose_mod.EXTENDED_REASONS
        )

    def test_the_model_layer_already_holds_the_freeze(self):
        from app.models.goal import CRITERION_TOOL_FACT_SOURCE, SubGoalSpec

        assert CRITERION_TOOL_FACT_SOURCE == "tool"
        try:
            SubGoalSpec.validate_criteria(
                {
                    "type": "threshold_reached",
                    "source": "tool",
                    "path": "tension",
                    "op": ">=",
                    "value": 1,
                }
            )
        except ValueError as error:
            assert "保持值集最小" in str(error)
        else:
            raise AssertionError("模型层应拒绝 threshold_reached + fact_source='tool'")


class TestZeroMigrationAndZeroWrite:
    """I11：迁移链头 `0046`；本任务零写入（拆解只产内存态结果）。"""

    def test_migration_chain_head_matches_pin(self):
        numbered = sorted(
            int(match.group(1))
            for path in VERSIONS_DIR.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert numbered, "未找到迁移文件"
        assert f"{max(numbered):04d}" == MIGRATION_HEAD
        assert max(numbered) == int(MIGRATION_HEAD)

    def test_decompose_writes_nothing_to_the_plan_face(
        self, db_session_factory, make_goal
    ):
        goal = make_goal(description="零写库目标")
        decomposer = decompose_mod.TaskDecomposer(registry=builtin_registry())
        result = decomposer.decompose(
            proposal(step(1)),
            make_goal(),
            make_ctx(),
            settings=settings(),
        )
        assert result.steps
        assert goal_repository.count_plans(goal.id) == 0
        assert goal_repository.get_latest_plan(goal.id) is None

    def test_decompose_module_has_no_repository_dependency(self):
        imported = _imported_modules(Path(decompose_mod.__file__).parent)
        assert not [
            module
            for module in imported
            if module.startswith(("app.repositories", "app.application", "sqlalchemy"))
        ]
        assert "app.core.db" not in imported


def _imported_modules(path: Path) -> set[str]:
    import ast

    files = (
        sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
        if path.is_dir()
        else [path]
    )
    modules: set[str] = set()
    for source_file in files:
        for node in ast.walk(ast.parse(source_file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
    return modules
