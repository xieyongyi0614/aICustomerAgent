"""PLAN-004 阶段④与三闸断言：形状 / 绑定 / 预算三闸纯函数、理由码、职责不重叠。

覆盖 Task Detail §9.1 的 U11、U12、U13 与 §9.2 的 I1、I6（零 IO 探针）。
理由码对齐 PLAN-003 §4.2.4 七道闸与 architecture §8.6（契约纪律 D4）。
"""

import socket

import pytest

from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.models.goal import SubGoalSpec
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import goal_repository
from app.services import goal_planning
from app.services.planning import context as plan_context
from app.services.planning import decompose as decompose_mod
from app.services.planning import engine as plan_engine
from app.services.tool.registry import get_tool_registry

from .plan004_support import (
    REMINDER_CREATE,
    decompose,
    make_ctx,
    plan004_binding_on,
    step,
)

VALIDATOR = decompose_mod.PlanValidator


def spec(index: int = 1, **overrides) -> SubGoalSpec:
    """直接构造步骤（绕过 ① 的 dict 路径）：三闸的输入可以是**已落库 / 上游构造**的步骤。"""
    payload = {
        "index": index,
        "description": f"步骤{index}",
        "capability": "create_reminder",
        "params": {},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    }
    payload.update(overrides)
    return SubGoalSpec.model_validate(payload)


def chain(length: int) -> list[SubGoalSpec]:
    """N 个互不依赖的叶子步（形状闸的合法输入；未绑定故绑定闸会另判）。"""
    return [spec(index) for index in range(1, length + 1)]


def bound_chain(length: int, **overrides) -> list[SubGoalSpec]:
    """N 个绑定合法的叶子步（绑定闸的合法输入）。"""
    return [
        spec(
            index,
            tool_id=REMINDER_CREATE,
            binding_reason=decompose_mod.BINDING_REASON_CAPABILITY_MAP,
            expected_effects=("world",),
            **overrides,
        )
        for index in range(1, length + 1)
    ]


def deep_chain(depth: int) -> list[SubGoalSpec]:
    """自造超深嵌套（`validate_sub_goals` 会拒，故只用于三闸直测）；父步 `kind=composite`。"""
    return [
        spec(
            index,
            parent_index=None if index == 1 else index - 1,
            kind="composite" if index < depth else "tool",
            tool_id=None if index < depth else REMINDER_CREATE,
            binding_reason=None
            if index < depth
            else decompose_mod.BINDING_REASON_CAPABILITY_MAP,
        )
        for index in range(1, depth + 1)
    ]


class TestShapeGate:
    """§8 Step 4.1：序号 / 依赖 / 父引用 / 深度 / `kind` 与父子结构相合。"""

    def test_legal_steps_pass(self):
        assert VALIDATOR.validate_shape(chain(3), max_depth=2) == []

    def test_discontinuous_index_is_reported(self):
        errors = VALIDATOR.validate_shape([spec(2), spec(2)], max_depth=2)
        assert errors
        assert all(error.startswith(decompose_mod.REASON_INVALID_SHAPE) for error in errors)
        assert any("序号不连续" in error for error in errors)

    def test_forward_and_unknown_dependencies_are_reported(self):
        forward = VALIDATOR.validate_shape(
            [spec(1, depends_on=[2]), spec(2, depends_on=[1])], max_depth=2
        )
        assert any("前向引用" in error for error in forward)
        unknown = VALIDATOR.validate_shape([spec(1, depends_on=[0])], max_depth=2)
        assert any("不存在" in error for error in unknown)

    def test_unknown_and_forward_parents_are_reported(self):
        forward = VALIDATOR.validate_shape([spec(1, parent_index=1)], max_depth=2)
        assert any("前向引用" in error for error in forward)
        unknown = VALIDATOR.validate_shape(
            [spec(2), spec(3, parent_index=1)], max_depth=2
        )
        assert any("父步 1 不存在" in error for error in unknown)

    def test_depth_cap_is_enforced(self):
        errors = VALIDATOR.validate_shape(deep_chain(3), max_depth=2)
        assert any("嵌套 3 层" in error for error in errors)
        assert VALIDATOR.validate_shape(deep_chain(2), max_depth=2) == []

    def test_kind_must_match_the_parent_structure(self):
        parent_without_children = VALIDATOR.validate_shape(
            [spec(1, kind="composite")], max_depth=2
        )
        assert any("没有子步" in error for error in parent_without_children)
        parent_must_be_composite = VALIDATOR.validate_shape(
            [spec(1, kind="tool"), spec(2, parent_index=1)], max_depth=2
        )
        assert any("必须为 composite" in error for error in parent_must_be_composite)
        assert (
            VALIDATOR.validate_shape(
                [spec(1, kind="composite"), spec(2, parent_index=1)], max_depth=2
            )
            == []
        )


class TestBindingGate:
    """§8 Step 4.2：`kind="tool"` 必须带合法且在面上的 `tool_id`；效果集取值合法。"""

    def test_legal_binding_passes(self):
        bound = spec(1, tool_id=REMINDER_CREATE, kind="tool", expected_effects=("world",))
        assert VALIDATOR.validate_binding([bound], make_ctx().tool_surface) == []

    def test_missing_tool_id_is_reported(self):
        errors = VALIDATOR.validate_binding([spec(1, kind="tool")], make_ctx().tool_surface)
        assert errors[0].startswith(decompose_mod.REASON_BINDING_MISSING)

    def test_malformed_tool_id_is_unresolvable(self):
        errors = VALIDATOR.validate_binding(
            [spec(1, kind="tool", tool_id="NotATool")], make_ctx().tool_surface
        )
        assert errors[0].startswith(decompose_mod.REASON_TOOL_UNRESOLVABLE)

    def test_tool_outside_the_surface_is_reported(self):
        errors = VALIDATOR.validate_binding(
            [spec(1, kind="tool", tool_id="builtin.reminder.create")],
            ToolSurface(run_kind=RUN_KIND_AUTONOMOUS_TICK, tool_ids=("world.env.query",)),
        )
        assert errors[0].startswith(decompose_mod.REASON_TOOL_OFF_SURFACE)

    def test_missing_surface_rejects_every_tool_step(self):
        errors = VALIDATOR.validate_binding([spec(1, kind="tool", tool_id=REMINDER_CREATE)], None)
        assert errors[0].startswith(decompose_mod.REASON_TOOL_OFF_SURFACE)

    def test_non_tool_kind_must_not_carry_a_binding(self):
        errors = VALIDATOR.validate_binding(
            [spec(1, kind="observe", tool_id=REMINDER_CREATE)], make_ctx().tool_surface
        )
        assert errors[0].startswith(decompose_mod.REASON_INVALID_BINDING)

    def test_binding_reason_must_be_one_of_three(self):
        errors = VALIDATOR.validate_binding(
            [
                spec(
                    1,
                    kind="tool",
                    tool_id=REMINDER_CREATE,
                    binding_reason="guessed_by_llm",
                )
            ],
            make_ctx().tool_surface,
        )
        assert errors[0].startswith(decompose_mod.REASON_INVALID_BINDING)

    def test_expected_effects_must_stay_within_the_value_set(self):
        illegal = spec(1, kind="tool", tool_id=REMINDER_CREATE)
        illegal.expected_effects = ("teleport",)
        errors = VALIDATOR.validate_binding([illegal], make_ctx().tool_surface)
        assert errors[0].startswith(decompose_mod.REASON_INVALID_EFFECTS)
        assert "TOOL_EFFECT_KINDS" in errors[0]


class TestBudgetGate:
    """U13：步数 / 深度 / 尝试上限 / TTL 各一负例。"""

    def budget(self, **overrides) -> dict[str, int]:
        budget = {
            decompose_mod.BUDGET_MAX_STEPS: 5,
            decompose_mod.BUDGET_MAX_DEPTH: 2,
            decompose_mod.BUDGET_STEP_MAX_ATTEMPTS: 2,
            decompose_mod.BUDGET_TTL_HOURS: 168,
            decompose_mod.BUDGET_GOAL_WINDOW_HOURS: 168,
        }
        budget.update(overrides)
        return budget

    def test_legal_budget_passes(self):
        assert VALIDATOR.validate_budget(chain(2), 1, self.budget()) == []

    def test_step_count_overflow_is_reported(self):
        errors = VALIDATOR.validate_budget(chain(6), 1, self.budget())
        assert len(errors) == 1
        assert errors[0].startswith(decompose_mod.REASON_COUNT_EXCEEDED)

    def test_depth_overflow_is_reported(self):
        errors = VALIDATOR.validate_budget(deep_chain(3), 1, self.budget())
        assert errors[0].startswith(decompose_mod.REASON_DEPTH_EXCEEDED)

    def test_attempt_limit_overflow_is_reported(self):
        retrying = [spec(1, retry_policy="until_budget")]
        assert VALIDATOR.validate_budget(retrying, 1, self.budget()) == []
        errors = VALIDATOR.validate_budget(
            retrying, 1, self.budget(**{decompose_mod.BUDGET_STEP_MAX_ATTEMPTS: 0})
        )
        assert errors[0].startswith(decompose_mod.REASON_STEP_ATTEMPTS_EXCEEDED)
        bounded = [spec(1, retry_policy="once")]
        assert (
            VALIDATOR.validate_budget(
                bounded, 1, self.budget(**{decompose_mod.BUDGET_STEP_MAX_ATTEMPTS: 0})
            )
            == []
        )

    def test_ttl_overflow_is_reported(self):
        errors = VALIDATOR.validate_budget(chain(1), 1, self.budget(**{"ttl_hours": 200}))
        assert errors[0].startswith(decompose_mod.REASON_TTL_EXCEEDED)
        assert "超出目标激活窗" in errors[0]

    def test_ttl_must_be_positive(self):
        errors = VALIDATOR.validate_budget(chain(1), 1, self.budget(**{"ttl_hours": 0}))
        assert errors[0].startswith(decompose_mod.REASON_TTL_EXCEEDED)

    def test_plan_versions_must_be_positive(self):
        errors = VALIDATOR.validate_budget(chain(1), 0, self.budget())
        assert errors[0].startswith(decompose_mod.REASON_PLAN_VERSIONS_INVALID)

    def test_missing_budget_keys_fail_closed(self):
        errors = VALIDATOR.validate_budget(chain(1), 1, {})
        assert errors
        assert all(isinstance(error, str) for error in errors)


class TestReasonCodeTable:
    """契约纪律 D4：理由码与 PLAN-003 §4.2.4 / architecture §8.6 对照。"""

    def test_shared_reason_codes_come_from_the_frozen_gate_table(self):
        assert decompose_mod.GATE_REASONS == (
            goal_planning.REASON_INVALID_SHAPE,
            "plan_tool_unresolvable",
            "plan_tool_off_surface",
            "capability_binding_missing",
            goal_planning.REASON_COUNT_EXCEEDED,
        )
        assert decompose_mod.REASON_INVALID_SHAPE == "invalid_sub_goal_shape"
        assert decompose_mod.REASON_COUNT_EXCEEDED == "subgoal_count_exceeded"

    def test_extended_reason_codes_are_declared_explicitly(self):
        assert decompose_mod.EXTENDED_REASONS == (
            "plan_depth_exceeded",
            "plan_step_attempts_exceeded",
            "plan_ttl_exceeded",
            "plan_versions_invalid",
            "invalid_step_binding",
            "invalid_expected_effects",
            "invalid_step_params",
            "plan_criteria_unsupported",
        )

    def test_reasons_are_readable_code_colon_detail_pairs(self):
        errors = VALIDATOR.validate_shape(deep_chain(3), max_depth=2)
        code, _, detail = errors[0].partition(":")
        assert code in decompose_mod.GATE_REASONS + decompose_mod.EXTENDED_REASONS
        assert detail


class TestGatesDoNotOverlap:
    """U12：形状闸不管绑定、绑定闸不管预算、预算闸不管形状（交叉用例）。"""

    SHAPE_BROKEN = deep_chain(3)
    BINDING_BROKEN = [spec(1, kind="tool")]
    BUDGET_BROKEN = bound_chain(6)

    def test_shape_gate_ignores_binding_and_budget(self):
        assert VALIDATOR.validate_shape(self.BINDING_BROKEN, max_depth=2) == []
        assert VALIDATOR.validate_shape(self.BUDGET_BROKEN, max_depth=2) == []

    def test_binding_gate_ignores_shape_and_budget(self):
        surface = make_ctx().tool_surface
        assert VALIDATOR.validate_binding(self.SHAPE_BROKEN, surface) == []
        assert VALIDATOR.validate_binding(self.BUDGET_BROKEN, surface) == []

    def test_budget_gate_ignores_shape_and_binding(self):
        budget = {
            decompose_mod.BUDGET_MAX_STEPS: 5,
            decompose_mod.BUDGET_MAX_DEPTH: 5,
            decompose_mod.BUDGET_STEP_MAX_ATTEMPTS: 2,
            decompose_mod.BUDGET_TTL_HOURS: 168,
            decompose_mod.BUDGET_GOAL_WINDOW_HOURS: 168,
        }
        assert VALIDATOR.validate_budget(self.BINDING_BROKEN, 1, budget) == []
        assert VALIDATOR.validate_budget(self.SHAPE_BROKEN, 1, budget) == []


class TestGatesArePureFunctions:
    """U11 / I6：三闸零 IO、零 LLM、零 `get_settings()` 直调；返回值恒为 `list[str]`。"""

    def test_gates_call_no_io_surface(self, monkeypatch):
        counts = {"db": 0, "net": 0, "llm": 0, "settings": 0}

        def forbid(key):
            def _boom(*_args, **_kwargs):
                counts[key] += 1
                raise AssertionError(f"PlanValidator 不得触达 {key}")

            return _boom

        import app.core.db as db_module
        from app.application.agent_runtime import llm_gateway
        from app.core import settings as settings_module

        monkeypatch.setattr(db_module, "SessionLocal", forbid("db"))
        monkeypatch.setattr(socket.socket, "connect", forbid("net"))
        monkeypatch.setattr(socket, "create_connection", forbid("net"))
        monkeypatch.setattr(llm_gateway, "acquire", forbid("llm"))
        monkeypatch.setattr(settings_module, "get_settings", forbid("settings"))

        surface = make_ctx().tool_surface
        assert VALIDATOR.validate_shape(bound_chain(3), max_depth=2) == []
        assert VALIDATOR.validate_binding(bound_chain(3), surface) == []
        assert VALIDATOR.validate_budget(
            chain(3),
            1,
            {
                decompose_mod.BUDGET_MAX_STEPS: 5,
                decompose_mod.BUDGET_MAX_DEPTH: 2,
                decompose_mod.BUDGET_STEP_MAX_ATTEMPTS: 2,
                decompose_mod.BUDGET_TTL_HOURS: 168,
                decompose_mod.BUDGET_GOAL_WINDOW_HOURS: 168,
            },
        ) == []
        assert counts == {"db": 0, "net": 0, "llm": 0, "settings": 0}

    @pytest.mark.parametrize(
        "gate",
        ["validate_shape", "validate_binding", "validate_budget"],
    )
    def test_gates_always_return_a_list_of_strings(self, gate):
        calls = {
            "validate_shape": lambda: VALIDATOR.validate_shape(chain(1), max_depth=0),
            "validate_binding": lambda: VALIDATOR.validate_binding(chain(1), None),
            "validate_budget": lambda: VALIDATOR.validate_budget(chain(1), 0, {}),
        }
        errors = calls[gate]()
        assert isinstance(errors, list)
        assert errors and all(isinstance(error, str) for error in errors)


class TestDecomposeFeedsTheEngine:
    """I1：`decompose` 的产物与 `PlanningEngine` 七道闸同源——同一份 `sub_goals` 两边都过。

    PLAN-003 的引擎不绑定（`tool_id` 由提案携带、只做闸门 5 / 6 判定），故本用例以
    「提案携带 LLM 建议的 `tool_id` 提示 + `decompose` 确定性重推」验证两侧结果一致。
    """

    @pytest.fixture
    def planning_on(self, override_settings):
        override_settings(
            v25_planning_enabled="true",
            v25_plan_context_enabled="true",
            v25_plan_step_binding_enabled="true",
            v24_tool_system_enabled="true",
            world_enabled="false",
            observability_persist_enabled="false")

    def _context(self, goal) -> PlanContext:
        from app.core.settings import get_settings

        return PlanContext(
            goal=goal,
            tool_surface=ToolSurface(
                run_kind=RUN_KIND_AUTONOMOUS_TICK, tool_ids=(REMINDER_CREATE,)
            ),
            budget=plan_context.plan_budget(get_settings()),
        )

    async def test_decomposed_steps_pass_the_three_gates_and_land_validated(
        self, db_session_factory, planning_on, make_goal, stub_planning_llm
    ):
        goal = make_goal(description="拆解与引擎同源目标")
        raw = step(
            1,
            capability="create_reminder",
            params={"content": "带伞", "due_at": "2026-09-17T08:00:00"},
            tool_id=REMINDER_CREATE,
        )
        surface = ToolSurface(
            run_kind=RUN_KIND_AUTONOMOUS_TICK, tool_ids=(REMINDER_CREATE,)
        )
        result = decompose(raw, ctx=make_ctx(REMINDER_CREATE))
        assert result.passed, result.binding_errors + result.budget_errors
        assert VALIDATOR.validate_shape(result.steps, max_depth=2) == []
        assert VALIDATOR.validate_binding(result.steps, surface) == []
        assert (
            VALIDATOR.validate_budget(
                result.steps, 1, decompose_mod._plan_budget_limits(make_ctx(), _settings())
            )
            == []
        )
        assert result.steps[0].tool_id == REMINDER_CREATE
        assert get_tool_registry().resolve(result.steps[0].tool_id) is not None

        stub_planning_llm(sub_goals=[raw])
        outcome = await plan_engine.PlanningEngine().plan(
            goal, self._context(goal), trigger=goal_planning.TRIGGER_CREATED
        )
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        stored = goal_repository.get_plan(outcome.plan.id)
        assert [spec.tool_id for spec in stored.sub_goals] == [
            result.steps[0].tool_id
        ]


def _settings():
    from app.core.settings import get_settings

    return get_settings()


def test_plan_budget_limits_project_settings_and_context():
    from types import SimpleNamespace

    from app.core.settings import get_settings

    settings = get_settings()
    budget = decompose_mod._plan_budget_limits(make_ctx(), settings)
    assert budget == {
        decompose_mod.BUDGET_MAX_STEPS: min(
            settings.v25_plan_max_steps, settings.v2_autonomy_subgoal_max_count
        ),
        decompose_mod.BUDGET_MAX_DEPTH: min(
            settings.v25_plan_max_depth, settings.v2_autonomy_subgoal_max_depth
        ),
        decompose_mod.BUDGET_STEP_MAX_ATTEMPTS: settings.v25_plan_step_max_attempts,
        decompose_mod.BUDGET_TTL_HOURS: settings.v25_plan_ttl_hours,
        decompose_mod.BUDGET_GOAL_WINDOW_HOURS: settings.v2_autonomy_goal_max_active_hours,
    }
    narrowed = decompose_mod._plan_budget_limits(
        SimpleNamespace(tool_surface=make_ctx().tool_surface, budget={"max_steps": 2}),
        settings,
    )
    assert narrowed[decompose_mod.BUDGET_MAX_STEPS] == 2
    assert narrowed[decompose_mod.BUDGET_MAX_DEPTH] == min(
        settings.v25_plan_max_depth, settings.v2_autonomy_subgoal_max_depth
    )
