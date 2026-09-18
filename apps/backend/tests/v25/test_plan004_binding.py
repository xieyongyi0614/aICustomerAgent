"""PLAN-004 阶段②工具绑定断言：tiebreak 可复现 / 裁决路径 / 规划期与执行期一致。

覆盖 Task Detail §9.1 的 U3、U4、§9.2 的 I5、I7 与 §9.3 的 S2、S3。

**为什么把「绑定」与「选择」分开测**：绑定必须是**确定性**的（同输入同输出），否则重复运行
会产生不一致的 `tool_id`，使幂等键与审计失去意义（Task Detail §1.3 点名的头号写错处）。
本模块的 U3 即为该风险的守卫。
"""

from app.models.action import ActionIntent
from app.models.plan import PLAN_STEP_ACTION_CONFIDENCE
from app.services.planning import decompose as decompose_mod
from app.services.tool.context import ToolContext
from app.services.tool.surface import (
    SELECTION_REASON_CHANNEL_RECIPIENT,
    SELECTION_REASON_PRIORITY_ORDER,
    ToolSelector,
    ToolSurfaceResolver,
)

from .plan004_support import (
    CHANNEL_SEND,
    NOTIFICATION_SEND,
    REMINDER_CREATE,
    RUN_KIND_AUTONOMOUS,
    RUN_KIND_FOREGROUND,
    bind,
    bound_surface,
    builtin_registry,
    decompose,
    make_ctx,
    parsed,
    plan004_binding_on,
    step,
    tool_surface,
)

CHANNEL_FLAGS = {
    "feishu_enabled": "true",
    "feishu_app_id": "plan4-app",
    "feishu_app_secret": "plan4-secret",
    "feishu_verification_token": "plan4-token",
}


def _surface_context(*, channel_on: bool) -> ToolContext:
    from types import SimpleNamespace

    settings = SimpleNamespace(
        feishu_enabled=channel_on,
        tool_surface_max_tools=12,
        world_enabled=True,
    )
    return ToolContext(user_id="plan4-user", settings=settings)


def _notification_intent(*, recipient: bool) -> ActionIntent:
    params = {"content": "出门带伞"}
    if recipient:
        params["recipient"] = "user-1"
    return ActionIntent(
        action_type="send_notification",
        confidence=PLAN_STEP_ACTION_CONFIDENCE,
        params=params,
    )


class TestTiebreakDeterminism:
    """U3 / S2：一能力多工具的 tiebreak 可复现（priority + `tool_id` 字典序）。"""

    def test_repeated_runs_are_identical(self):
        registry = builtin_registry()
        surface = tool_surface(NOTIFICATION_SEND, CHANNEL_SEND)
        ctx = make_ctx(NOTIFICATION_SEND, CHANNEL_SEND)
        spec = step(
            1,
            capability="send_notification",
            params={"content": "x", "recipient": "user-1"},
        )
        outputs = {
            (
                bindings[0].binding.tool_id,
                bindings[0].binding_reason,
                work[0].kind,
                work[0].expected_effects,
            )
            for work, bindings, _ in (
                bind(
                    parsed(dict(spec)),
                    ctx,
                    registry=registry,
                    selector=ToolSelector(registry),
                )
                for _ in range(5)
            )
        }
        assert outputs == {(CHANNEL_SEND, "tool_selector", "tool", ("external",))}

    def test_recipient_free_intent_falls_back_to_priority_order(self):
        registry = builtin_registry()
        surface = tool_surface(NOTIFICATION_SEND, CHANNEL_SEND)
        selection = ToolSelector(registry).select_with_reason(
            _notification_intent(recipient=False), surface
        )
        assert selection.binding.tool_id == NOTIFICATION_SEND
        assert selection.reason == SELECTION_REASON_PRIORITY_ORDER

    def test_recipient_aware_branch_prefers_the_channel_tool(self):
        registry = builtin_registry()
        surface = tool_surface(NOTIFICATION_SEND, CHANNEL_SEND)
        selection = ToolSelector(registry).select_with_reason(
            _notification_intent(recipient=True), surface
        )
        assert selection.binding.tool_id == CHANNEL_SEND
        assert selection.reason == SELECTION_REASON_CHANNEL_RECIPIENT


class TestBindingReasonPaths:
    """U4：`tool_selector` / `capability_map` / `fallback` 三条路径各一例。"""

    def test_single_declared_tool_uses_the_capability_map(self):
        result = decompose(step(1))
        assert result.steps[0].tool_id == REMINDER_CREATE
        assert result.steps[0].binding_reason == decompose_mod.BINDING_REASON_CAPABILITY_MAP

    def test_multi_declared_tool_uses_the_selector(self):
        result = decompose(
            step(1, capability="send_notification", params={"content": "x"}),
            ctx=make_ctx(NOTIFICATION_SEND, CHANNEL_SEND),
        )
        assert result.steps[0].binding_reason == decompose_mod.BINDING_REASON_TOOL_SELECTOR

    def test_unmapped_action_type_uses_the_legacy_fallback(self):
        """`ACTION_TOOL_MAP` 未覆盖时的兜底：仍由 `ToolSelector` 按 `(capability, action)` 寻回。"""
        registry = builtin_registry()
        legacy_selector = ToolSelector(registry, tool_map={})
        result = decompose(step(1), selector=legacy_selector)
        assert result.steps[0].tool_id == REMINDER_CREATE
        assert result.steps[0].binding_reason == decompose_mod.BINDING_REASON_FALLBACK


class TestPlanningMatchesExecutionSelection:
    """I7 / S3：规划期绑定与执行期选择同函数同规则、同结果。"""

    def test_binding_equals_the_execution_selector(self):
        registry = builtin_registry()
        surface = tool_surface(REMINDER_CREATE)
        result = decompose(step(1), ctx=make_ctx(REMINDER_CREATE), registry=registry)
        selection = ToolSelector(registry).select_with_reason(
            ActionIntent(
                action_type="create_reminder",
                confidence=PLAN_STEP_ACTION_CONFIDENCE,
                params={},
            ),
            surface,
        )
        assert result.steps[0].tool_id == selection.binding.tool_id
        assert result.bindings[0].binding.capability == selection.binding.capability
        assert result.bindings[0].binding.action == selection.binding.action

    def test_channel_excluded_surface_still_binds_a_live_tool(self):
        """S3：通道被时段剔除后面上只剩一个候选——绑定唯一，**不产生死步骤**。"""
        registry = builtin_registry()
        autonomous = ToolSurfaceResolver(registry).resolve(
            RUN_KIND_AUTONOMOUS, _surface_context(channel_on=True)
        )
        assert CHANNEL_SEND not in autonomous.tool_ids
        result = decompose(
            step(1, capability="send_notification", params={"content": "x"}),
            ctx=make_ctx(*autonomous.tool_ids),
        )
        assert result.steps[0].tool_id == NOTIFICATION_SEND
        assert result.binding_errors == []

    def test_channel_enabled_surface_exposes_both_candidates(self, override_settings):
        override_settings(**CHANNEL_FLAGS)
        registry = builtin_registry()
        foreground = ToolSurfaceResolver(registry).resolve(
            RUN_KIND_FOREGROUND, _surface_context(channel_on=True)
        )
        assert {NOTIFICATION_SEND, CHANNEL_SEND} <= set(foreground.tool_ids)
        result = decompose(
            step(
                1,
                capability="send_notification",
                params={"content": "x", "recipient": "user-1"},
            ),
            ctx=make_ctx(*foreground.tool_ids),
            registry=registry,
        )
        assert result.steps[0].tool_id == CHANNEL_SEND
        assert result.steps[0].binding_reason == decompose_mod.BINDING_REASON_TOOL_SELECTOR


class TestRegistryIsReadOnly:
    """I5：绑定只读 `ToolRegistry`——注册表快照（声明 / 健康度 / 运行期禁用）零改动。"""

    def test_registry_snapshot_is_unchanged_by_binding(self):
        registry = builtin_registry()

        def snapshot():
            return (
                tuple(definition.id for definition in registry.list()),
                tuple(
                    (tool_id, registry.effective_status(tool_id))
                    for tool_id in sorted(registry.health())
                ),
                tuple(sorted(registry.runtime_disabled_ids())),
                tuple(
                    (tool_id, record.model_dump())
                    for tool_id, record in sorted(registry.health().items())
                ),
            )

        before = snapshot()
        _work, bindings, errors = bind(
            parsed(step(1), step(2, capability="remember_fact", params={"fact": "x"})),
            ctx=make_ctx(*bound_surface().tool_ids),
            registry=registry,
        )
        assert errors == []
        assert len(bindings) == 2
        assert snapshot() == before


class TestBindingIsFlagGated:
    """§8 Step 6：绑定子闸 off 时阶段②整体跳过（`bindings` 空、派生字段不写）。"""

    def test_disabled_binding_returns_no_binding(self):
        specs = parsed(step(1))
        work, bindings, errors = bind(specs, registry=builtin_registry(), enabled=False)
        assert bindings == [] and errors == []
        assert work[0].tool_id is None
        assert work[0].kind == "tool"
        assert work[0].binding_reason is None
        assert work[0].expected_effects == ()
