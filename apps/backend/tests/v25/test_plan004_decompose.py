"""PLAN-004 四阶段①②③断言：结构解析 / 工具绑定派生字段 / 判据补全。

覆盖 Task Detail §9.1 的 U1、U2、U5、U6、U7、U8、U9、U10、U15 与 §9.2 的 I2（复用
`validate_sub_goals`）。绑定裁决路径与 tiebreak 可复现见 `test_plan004_binding.py`，
三闸见 `test_plan004_validator.py`。
"""

import pytest

from app.models.action import ACTION_TYPES
from app.models.goal import SubGoalSpec
from app.models.tool import PermissionProfile, ToolDefinition, ToolParameter, ToolSchema
from app.services.planning import decompose as decompose_mod
from app.services.tool.registry import ToolRegistry

from .plan004_support import (
    CHANNEL_SEND,
    ENV_QUERY,
    MEMORY_SAVE,
    NOTIFICATION_SEND,
    REMINDER_CREATE,
    SEARCH_QUERY,
    bind,
    decompose,
    make_ctx,
    make_goal,
    parsed,
    plan004_binding_on,
    proposal,
    settings,
    step,
    tool_criteria,
)


class TestStep1StructureParsing:
    """U1：形状合法 / 序号不连续 / 前向依赖 / 超深嵌套 / 空列表。"""

    def test_legal_proposal_parses_into_ordered_specs(self):
        specs = parsed(step(1), step(2, depends_on=[1]))
        assert [spec.index for spec in specs] == [1, 2]
        assert isinstance(specs[0], SubGoalSpec)
        assert specs[0].capability in ACTION_TYPES

    def test_sub_goals_reuse_validate_sub_goals_for_depth_cap(self):
        """I2：深度封顶由既有 `validate_sub_goals` 承担（本模块零重复实现）。"""
        specs = parsed(step(1), step(2, parent_index=1), max_depth=2)
        assert [spec.parent_index for spec in specs] == [None, 1]
        with pytest.raises(ValueError, match="嵌套超过 2 层"):
            parsed(step(1), step(2, parent_index=1), step(3, parent_index=2), max_depth=2)

    def test_discontinuous_index_is_rejected(self):
        with pytest.raises(ValueError, match="序号不连续"):
            parsed(step(2))

    def test_forward_dependency_is_rejected(self):
        with pytest.raises(ValueError, match="前向引用"):
            parsed(step(1, depends_on=[2]), step(2))

    def test_empty_sub_goals_is_shaped_illegal(self):
        with pytest.raises(ValueError, match="没有 Sub-Goal 步骤"):
            decompose_mod._parse_structure(proposal(), max_depth=2)
        with pytest.raises(ValueError, match="没有 Sub-Goal 步骤"):
            decompose()  # 一步都没有 → decompose 上抛（§6.6 不吞）

    def test_unknown_parent_reference_is_rejected(self):
        with pytest.raises(ValueError, match="父引用缺失或前向"):
            parsed(step(1), step(2, parent_index=3))


class TestStep2CriteriaWhitelist:
    """U2：判据四元组白名单（type / source / path / op）各一负例，由既有校验承担。"""

    @pytest.mark.parametrize(
        "criteria",
        [
            {"type": "telepathy", "capability": "create_reminder"},
            {"type": "field_equals", "source": "dream", "path": "x", "value": 1},
            {"type": "threshold_reached", "source": "state", "path": "luck", "op": ">=", "value": 1},
            {"type": "threshold_reached", "source": "state", "path": "mood", "op": "==", "value": 1},
        ],
        ids=["type", "source", "path", "op"],
    )
    def test_criteria_outside_whitelist_is_rejected(self, criteria):
        with pytest.raises(ValueError):
            parsed(step(1, criteria=criteria))


class TestStep2KindDerivation:
    """U6：`kind` 三条推导规则。"""

    def test_bound_step_is_tool(self):
        result = decompose(step(1))
        assert result.passed, result.binding_errors
        assert result.steps[0].kind == decompose_mod.STEP_KIND_TOOL
        assert result.steps[0].tool_id == REMINDER_CREATE

    def test_unbound_leaf_is_observe(self):
        ctx = make_ctx(REMINDER_CREATE)
        result = decompose(step(1, capability="query_search", params={"query": "天气"}), ctx=ctx)
        spec = result.steps[0]
        assert spec.tool_id is None
        assert spec.kind == decompose_mod.STEP_KIND_OBSERVE
        assert spec.binding_reason is None
        assert spec.expected_effects == ()

    def test_parent_step_is_composite(self):
        result = decompose(step(1), step(2, parent_index=1))
        parent, child = result.steps
        assert parent.kind == decompose_mod.STEP_KIND_COMPOSITE
        assert parent.tool_id is None
        assert child.kind == decompose_mod.STEP_KIND_TOOL
        assert [binding.step_index for binding in result.bindings] == [2]


class TestStep2EffectProjection:
    """U7：`expected_effects` 取值约束（⊆ `TOOL_EFFECT_KINDS`）。"""

    def test_effects_are_projected_from_side_effects(self):
        result = decompose(
            step(1, capability="remember_fact", params={"fact": "x"}),
            step(2, capability="query_environment"),
        )
        assert result.steps[0].expected_effects == ("memory",)
        assert result.steps[1].expected_effects == ()

    def test_effects_outside_the_value_set_are_rejected(self):
        result = decompose(step(1))
        spec = result.steps[0]
        spec.expected_effects = ("teleport",)
        errors = decompose_mod.PlanValidator.validate_binding([spec], make_ctx().tool_surface)
        assert errors and errors[0].startswith(decompose_mod.REASON_INVALID_EFFECTS)


class TestStep2DerivedPolicies:
    """U8 与 §4.2.1 的 `retry_policy` / `on_failure` 推导规则。"""

    def test_default_on_failure_does_not_amplify(self):
        result = decompose(step(1), step(2))
        assert [spec.on_failure for spec in result.steps] == ["skip", "skip"]

    def test_sole_predecessor_is_upgraded_to_abort(self):
        result = decompose(step(1), step(2, depends_on=[1]))
        assert result.steps[0].on_failure == decompose_mod._ON_FAILURE_BLOCKING
        assert result.steps[1].on_failure == "skip"

    def test_explicit_on_failure_is_honoured(self):
        result = decompose(
            step(1, on_failure="continue"),
            step(2, depends_on=[1], on_failure="replan"),
        )
        assert result.steps[0].on_failure == "continue"
        assert result.steps[1].on_failure == "replan"

    def test_retry_policy_follows_idempotency_and_binding(self):
        ctx = make_ctx(REMINDER_CREATE)
        result = decompose(
            step(1), step(2, capability="query_search", params={"query": "x"}), ctx=ctx
        )
        bound, unbound = result.steps
        assert bound.retry_policy == "once"
        assert unbound.retry_policy == "none"

    def test_explicit_retry_policy_is_honoured(self):
        result = decompose(step(1, retry_policy="until_budget"))
        assert result.steps[0].retry_policy == "until_budget"

    def test_non_idempotent_tool_is_not_retried(self):
        registry = ToolRegistry()
        definition = ToolDefinition(
            id="ext.api.flaky",
            name="非幂等",
            description="PLAN-004 单测声明",
            namespace="ext.api",
            capability="search",
            action="query",
            input_schema=ToolSchema(
                parameters=[ToolParameter(name="query", type="string", required=True)]
            ),
            permission=PermissionProfile(level="sensitive", scope=("ext",)),
            side_effects=("send_external",),
            idempotency="none",
        )
        registry.register(definition)
        result = decompose(
            step(1, capability="query_search", params={"query": "x"}),
            ctx=make_ctx(definition.id),
            registry=registry,
        )
        assert result.steps[0].tool_id == definition.id
        assert result.steps[0].retry_policy == "none"


class TestStep3CriteriaCompletion:
    """U9 / U15：`tool` 事实源的白名单收敛与组合判据递归。"""

    def test_declared_observation_keys_win(self):
        result = decompose(
            step(1, criteria=tool_criteria("condition"), observation_keys=["condition"]),
            ctx=make_ctx(REMINDER_CREATE),
        )
        assert result.steps[0].observation_keys == ("condition",)
        assert result.criteria_errors == []
        assert result.passed, result.binding_errors

    def test_undeclared_key_stays_outside_the_whitelist(self):
        """绝不放任：未在 `observation_keys` 声明的键不进白名单（运行期不可判定，绝不默认 True）。"""
        result = decompose(
            step(
                1,
                criteria={
                    "type": "all_of",
                    "children": [tool_criteria("condition"), tool_criteria("temperature")],
                },
                observation_keys=["condition"],
            ),
            ctx=make_ctx(REMINDER_CREATE),
        )
        assert result.steps[0].observation_keys == ("condition",)
        assert "temperature" not in result.steps[0].observation_keys

    def test_undeclared_keys_are_derived_from_referenced_paths(self):
        result = decompose(
            step(1, criteria=tool_criteria("condition")),
            ctx=make_ctx(REMINDER_CREATE),
        )
        assert result.steps[0].observation_keys == ("condition",)

    def test_composite_criteria_merge_child_keys_in_declaration_order(self):
        criteria = {
            "type": "all_of",
            "children": [tool_criteria("b"), tool_criteria("a"), tool_criteria("b")],
        }
        result = decompose(step(1, criteria=criteria), ctx=make_ctx(REMINDER_CREATE))
        assert result.steps[0].observation_keys == ("b", "a")

        any_of = {"type": "any_of", "children": [tool_criteria("c"), tool_criteria("d")]}
        merged = decompose(step(1, criteria=any_of), ctx=make_ctx(REMINDER_CREATE))
        assert merged.steps[0].observation_keys == ("c", "d")

    def test_action_succeeded_tool_source_contributes_no_key(self):
        result = decompose(
            step(1, criteria={"type": "action_succeeded", "capability": "create_reminder"}),
            ctx=make_ctx(REMINDER_CREATE),
        )
        assert result.steps[0].observation_keys == ()

    def test_unbound_step_keeps_an_empty_whitelist(self):
        result = decompose(
            step(1, criteria=tool_criteria("condition")),
            ctx=make_ctx(SEARCH_QUERY),
        )
        assert result.steps[0].tool_id is None
        assert result.steps[0].observation_keys == ()

    def test_non_tool_sources_contribute_no_key(self):
        criteria = {
            "type": "field_equals",
            "source": "world",
            "path": "weather",
            "value": "sunny",
        }
        result = decompose(step(1, criteria=criteria), ctx=make_ctx(REMINDER_CREATE))
        assert result.steps[0].observation_keys == ()

    def test_step_without_decidable_criteria_does_not_fail_the_stage(self):
        """无判据的步骤不在本阶段报错（G1 由粒度判据裁决，见 `test_plan004_granularity.py`）。"""
        spec = SubGoalSpec.model_validate(
            {
                "index": 1,
                "description": "无判据步骤",
                "capability": "create_reminder",
                "params": {},
                "criteria": {},
            }
        )
        steps, errors = decompose_mod._complete_criteria([spec], [])
        assert errors == []
        assert steps[0].observation_keys == ()

    def test_composite_criteria_nested_twice_is_rejected(self):
        criteria = {
            "type": "all_of",
            "children": [
                {"type": "any_of", "children": [tool_criteria("condition")]},
            ],
        }
        with pytest.raises(ValueError, match="只允许一层嵌套"):
            parsed(step(1, criteria=criteria))


class TestStep3Q4Freeze:
    """U10：Q4 冻结（`fact_source="tool"` 下 `threshold_reached` 拒绝）的双层落地。"""

    THRESHOLD_TOOL = {
        "type": "threshold_reached",
        "source": "tool",
        "path": "tension",
        "op": ">=",
        "value": 1,
    }

    def test_stage1_model_layer_rejects_the_combination(self):
        """第一层（PLAN-002 的 `validate_criteria`）：dict 路径上由模型层先拒。"""
        with pytest.raises(ValueError, match="不支持事实源 'tool'"):
            decompose(step(1, criteria=dict(self.THRESHOLD_TOOL)))
        with pytest.raises(ValueError, match="不支持事实源 'tool'"):
            parsed(step(1, criteria=dict(self.THRESHOLD_TOOL)))

    def test_stage3_defends_specs_that_skip_stage1(self):
        """第二层（本任务的纵深防御）：未经 ① 构造的步骤在 ③ 记可读中文理由。"""
        spec = SubGoalSpec.model_validate(
            {
                "index": 1,
                "description": "阈值步骤",
                "capability": "create_reminder",
                "params": {},
                "criteria": dict(self.THRESHOLD_TOOL),
            }
        )
        steps, errors = decompose_mod._complete_criteria([spec], [])
        assert len(errors) == 1
        assert errors[0].startswith(decompose_mod.REASON_CRITERIA_UNSUPPORTED)
        assert "threshold_reached 判据不支持事实源 'tool'" in errors[0]
        assert steps[0].observation_keys == ()

    def test_composite_children_are_checked_recursively(self):
        spec = SubGoalSpec.model_validate(
            {
                "index": 1,
                "description": "组合判据步骤",
                "capability": "create_reminder",
                "params": {},
                "criteria": {
                    "type": "any_of",
                    "children": [dict(self.THRESHOLD_TOOL), tool_criteria("condition")],
                },
            }
        )
        _, errors = decompose_mod._complete_criteria([spec], [])
        assert len(errors) == 1
        assert errors[0].startswith(decompose_mod.REASON_CRITERIA_UNSUPPORTED)

    def test_threshold_reached_on_other_sources_stays_allowed(self):
        criteria = {
            "type": "threshold_reached",
            "source": "state",
            "path": "mood",
            "op": ">=",
            "value": 0.5,
        }
        spec = SubGoalSpec.model_validate(
            {
                "index": 1,
                "description": "阈值步骤",
                "capability": "create_reminder",
                "params": {},
                "criteria": criteria,
            }
        )
        _, errors = decompose_mod._complete_criteria([spec], [])
        assert errors == []


class TestBindingFailurePath:
    """U5：不可绑定步骤记 `capability_binding_missing` 且 `tool_id = None`。"""

    def test_tool_off_surface_marks_the_step_unbound(self):
        ctx = make_ctx(REMINDER_CREATE)
        result = decompose(
            step(1, capability="query_search", params={"query": "x"}),
            step(2),
            ctx=ctx,
        )
        assert result.passed is False
        assert len(result.binding_errors) == 1
        assert result.binding_errors[0].startswith(decompose_mod.REASON_BINDING_MISSING)
        assert result.steps[0].tool_id is None
        assert result.steps[1].tool_id == REMINDER_CREATE

    def test_unaligned_capability_is_marked_unbound(self):
        result = decompose(step(1, capability="teleport_user"))
        assert result.steps[0].tool_id is None
        assert result.binding_errors[0].startswith(decompose_mod.REASON_BINDING_MISSING)
        assert result.bindings == []

    def test_registry_unavailable_marks_every_step(self, monkeypatch):
        """§6.6：`registry` 为 `None` 且绑定生效 → 全部步骤记 `capability_binding_missing`。"""
        from app.services.planning.decompose import decomposer as decompose_impl

        monkeypatch.setattr(decompose_impl, "get_tool_registry", lambda: None)
        result = decompose_mod.TaskDecomposer().decompose(
            proposal(step(1), step(2)),
            make_goal(),
            make_ctx(),
            settings=settings(),
        )
        assert len(result.binding_errors) == 2
        assert all(
            error.startswith(decompose_mod.REASON_BINDING_MISSING)
            for error in result.binding_errors
        )
        assert [spec.tool_id for spec in result.steps] == [None, None]
        assert result.bindings == []


def test_binding_helper_writes_back_derived_fields():
    specs = parsed(step(1, capability="remember_fact", params={"fact": "x"}))
    work, bindings, errors = bind(specs)
    assert errors == []
    assert [binding.step_index for binding in bindings] == [1]
    assert work[0].tool_id == MEMORY_SAVE
    assert work[0].expected_effects == ("memory",)
    assert bindings[0].binding.tool_id == MEMORY_SAVE


def test_env_query_tool_binds_on_the_synthetic_surface():
    result = decompose(step(1, capability="query_environment"), ctx=make_ctx(ENV_QUERY))
    assert result.steps[0].tool_id == ENV_QUERY
    assert result.steps[0].expected_effects == ()


def test_multi_tool_capability_binds_the_notification_tool_on_the_autonomous_surface():
    result = decompose(
        step(1, capability="send_notification", params={"content": "x"}),
        ctx=make_ctx(NOTIFICATION_SEND),
    )
    assert result.steps[0].tool_id == NOTIFICATION_SEND
    assert CHANNEL_SEND not in [spec.tool_id for spec in result.steps]


class TestScenarioTravelPlan:
    """S1：「帮我规划一次旅行」四步拆解端到端（记录 → 查天气 → 提前提醒 → 当天提醒）。"""

    FOUR_STEPS = (
        step(1, capability="remember_fact", params={"fact": "九月去海边"}),
        step(2, capability="query_environment"),
        step(
            3,
            capability="create_reminder",
            params={"content": "订酒店", "due_at": "2026-09-17T09:00:00"},
        ),
        step(
            4,
            capability="send_notification",
            params={"content": "今天出发"},
            depends_on=[2, 3],
        ),
    )

    def test_four_steps_bind_converge_and_pass_the_budget(self):
        result = decompose(*self.FOUR_STEPS)
        assert result.passed, result.binding_errors + result.criteria_errors
        assert [spec.index for spec in result.steps] == [1, 2, 3, 4]
        assert [spec.tool_id for spec in result.steps] == [
            MEMORY_SAVE,
            ENV_QUERY,
            REMINDER_CREATE,
            NOTIFICATION_SEND,
        ]
        assert [spec.binding_reason for spec in result.steps] == [
            decompose_mod.BINDING_REASON_CAPABILITY_MAP,
            decompose_mod.BINDING_REASON_CAPABILITY_MAP,
            decompose_mod.BINDING_REASON_CAPABILITY_MAP,
            decompose_mod.BINDING_REASON_TOOL_SELECTOR,
        ]
        assert [spec.kind for spec in result.steps] == ["tool"] * 4
        assert [binding.step_index for binding in result.bindings] == [1, 2, 3, 4]
        assert [binding.binding.definition.id for binding in result.bindings] == [
            MEMORY_SAVE,
            ENV_QUERY,
            REMINDER_CREATE,
            NOTIFICATION_SEND,
        ]
        assert result.budget_errors == []

    def test_declared_tool_criteria_converge_the_observation_keys(self):
        criteria = {
            "type": "all_of",
            "children": [
                {"type": "action_succeeded", "capability": "query_environment"},
                tool_criteria("env.weather"),
            ],
        }
        result = decompose(
            step(1, capability="query_environment", criteria=criteria),
            ctx=make_ctx(ENV_QUERY),
        )
        assert result.steps[0].observation_keys == ("env.weather",)
        assert result.steps[0].tool_id == ENV_QUERY


class TestWeakValidationAtPlanTime:
    """S5：必填参数缺失的步骤在规划期即被拒（不进入执行）；类型 / 格式留给执行期。"""

    def test_missing_required_param_is_rejected(self):
        result = decompose(step(1, capability="create_reminder", params={"content": "只给内容"}))
        assert result.passed is False
        assert len(result.binding_errors) == 1
        assert result.binding_errors[0].startswith(decompose_mod.REASON_INVALID_PARAMS)
        assert "due_at" in result.binding_errors[0]
        assert result.steps[0].tool_id == REMINDER_CREATE

    def test_type_and_semantics_are_left_to_the_execution_time_validator(self):
        """弱校验只问齐备：类型错误（`due_at` 非时间串）在规划期**不**被拒。"""
        result = decompose(
            step(
                1,
                capability="create_reminder",
                params={"content": "内容", "due_at": "不是时间"},
            )
        )
        assert result.passed, result.binding_errors

    def test_unbound_step_is_not_weak_validated(self):
        result = decompose(
            step(1, capability="query_search", params={}), ctx=make_ctx(REMINDER_CREATE)
        )
        assert all(
            error.startswith(decompose_mod.REASON_BINDING_MISSING)
            for error in result.binding_errors
        )
