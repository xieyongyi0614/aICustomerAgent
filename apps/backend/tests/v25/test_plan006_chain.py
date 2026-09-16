"""PLAN-006 Step 4 / Step 6：执行链路断言（六闸门 + 五段短路）与授权·校验分层。

覆盖 Task Detail §9.2 I1~I4 / I8 / I9 / I10 与 §9.3 S4 / S5 / S9；对应 §8 Step 4 与 Step 6。

链路口径：**真实编排器**（`action_engine.run_action_planning`）+ 真实 `ToolExecutor`，只把
「五段的入口」与「三道具名闸门函数」包一层记录（`plan006_support` 的探针），判定逻辑零改动；
`PlanExecutorBridge.execute_step` 作为计划侧入口，故断言覆盖「计划步骤 → Action → Tool」全链。

三处与 Task Detail 的核对（按真实源码冻结，已在用例中留痕）

1. **六闸门只有三道具名函数**：`planner.evaluate_gates` 内 `disabled` / `ambiguous_params` /
   `quota_exceeded` 三段是内联判定（无独立函数可打桩）。故「六闸门各一次、顺序固定」由
   `GateOrderProbe`（六段读取点全记录）判定；链路侧另以三道具名函数的调用序 + 各闸门
   端到端拒绝理由共同举证。
2. **① `resolve` 段的失败路径在链路上不可达**：工具可用性由装配期面投影前置（不可用工具
   进不了面 → `assemble_plan` 直接返回 None），故该段的失败路径按 §4.2.4 在**执行器层**注入；
   链路层注入的是 ② `permission` / ③ `validate` 两段与 `confirm_required`。
3. **「额度耗尽不产生 `ActionRecord`」的字面要求与 V9 既有语义不符**：V9 在闸门拒绝时**仍落
   一条 `cancelled` 台账**（闸门裁决必须可事后归因），真正「零 `ActionRecord`」的只有
   `action_enabled=False`（总闸）。本模块两者都断言，并按源码语义留痕。
"""

from datetime import datetime, timedelta

import pytest

from app.application import action_engine
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.models.action import ActionIntent, make_dedupe_key
from app.repositories import action_repository
from app.services.action import planner as planner_mod
from app.services.action.planner import evaluate_gates
from app.services.action.registry import get_capability_registry
from app.services.planning.executor_bridge import PlanExecutorBridge
from app.services.tool.confirmation import get_confirmation_service
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, get_tool_registry
from tests.v24.tool003_support import StubCapability, stub_registry
from tests.v24.tool005_support import untrusted_definition

from . import plan006_support as support
from . import plan005_support as plan5
from .plan006_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    action_chain_on,
    planning_gates_on,
    repo_write_probe,
    tools_on,
)

USER = support.USER
GOAL_ID = support.GOAL_ID

MEMORY_TOOL = support.MEMORY_SAVE
REMINDER_TOOL = support.REMINDER_CREATE
NOTIFICATION_TOOL = support.NOTIFICATION_SEND
UNTRUSTED_TOOL = "user.notes.delete"

WEAK_VALIDATION_REASON = "invalid_step_params"


DEFAULT_MEMORY_PARAMS = {"fact": "小明喜欢喝咖啡"}
DEFAULT_SEND_PARAMS = {"content": "明天开会"}


def _goal():
    """与 `support.USER` 同身份的目标：行动台账按 user_id 查询，身份必须对齐。"""
    return plan5.goal(user_id=USER)


def _bridge(**kwargs) -> PlanExecutorBridge:
    kwargs.setdefault("registry", get_tool_registry())
    kwargs.setdefault("session_resolver", lambda _user_id: None)
    return PlanExecutorBridge(**kwargs)


def _memory_intent(params: dict | None = None) -> ActionIntent:
    payload = dict(DEFAULT_MEMORY_PARAMS if params is None else params)
    return ActionIntent(
        action_type="remember_fact",
        confidence="confident",
        params=payload,
        dedupe_key=make_dedupe_key("remember_fact", payload),
    )


def _send_intent(content: str = "明天开会") -> ActionIntent:
    payload = {"content": content}
    return ActionIntent(
        action_type="send_notification",
        confidence="confident",
        params=payload,
        dedupe_key=make_dedupe_key("send_notification", payload),
    )


def _memory_capability() -> StubCapability:
    return StubCapability(name="memory", action="save", required=["fact"])


def _wire_capability(monkeypatch, capability) -> None:
    monkeypatch.setattr(action_engine, "get_capability_registry", lambda: stub_registry(capability))


def _wire_registry(monkeypatch, registry: ToolRegistry) -> None:
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(planner_mod, "get_tool_registry", lambda: registry)


def _plan_step(
    tool_id: str, *, capability: str = "remember_fact", index: int = 1, **overrides
):
    """计划步骤构造：缺省带上目标工具的必填参数（`remember_fact` → `fact`）。"""
    defaults = DEFAULT_MEMORY_PARAMS if capability == "remember_fact" else DEFAULT_SEND_PARAMS
    params = overrides.pop("params", dict(defaults))
    return plan5.spec(index, capability=capability, tool_id=tool_id, params=params, **overrides)


def _plan(tool_id: str, *, capability: str = "remember_fact", index: int = 1):
    return plan5.plan([_plan_step(tool_id, capability=capability, index=index)])


# --- L1 六闸门 ----------------------------------------------------------------


class TestSixGates:
    """I1 / L1：一次判定完整经过六闸门，顺序固定、各一次（§4.2.3）。"""

    @pytest.fixture
    def probe(self, monkeypatch):
        """六闸门全序探针：三道内联闸门（记录型标量）+ 三道具名闸门（同刻度记录）。"""
        probe = support.GateOrderProbe()
        probe.install_named_gates(monkeypatch)
        return probe

    def test_l1_six_gates_run_once_each_in_the_frozen_order(self, probe):
        decision = evaluate_gates(probe.intent(), probe.snapshot())
        assert decision.allowed is True
        assert probe.log == list(support.GATE_ORDER)

    def test_l1_every_gate_is_independently_reachable(self, probe):
        assert (
            evaluate_gates(probe.intent(), probe.snapshot(action_enabled=False)).reason
            == "disabled"
        )
        assert (
            evaluate_gates(probe.intent(confidence="tentative"), probe.snapshot()).reason
            == "ambiguous_params"
        )
        assert (
            evaluate_gates(
                probe.intent(),
                probe.snapshot(registry=_capability_registry_without_reminder()),
            ).reason
            == "capability_unavailable"
        )
        assert (
            evaluate_gates(probe.intent(), probe.snapshot(active_count=5, max_active=5)).reason
            == "quota_exceeded"
        )

    def test_l1_duplicate_gate_blocks_a_repeated_dedupe_key(self, probe):
        intent = probe.intent()
        snapshot = probe.snapshot(
            records=[
                {
                    "dedupe_key": intent.dedupe_key,
                    "status": "succeeded",
                    "created_at": support.NOW,
                }
            ]
        )
        assert evaluate_gates(intent, snapshot).reason == "duplicate"

    def test_l1_quota_gate_short_circuits_before_effect_check(self, probe):
        decision = evaluate_gates(probe.intent(), probe.snapshot(active_count=5, max_active=5))
        assert decision.reason == "quota_exceeded"
        assert probe.log == [*support.GATE_ORDER[:5]]

    def test_l1_effect_already_satisfied_gate(self, probe):
        decision = evaluate_gates(
            probe.intent(action_type="create_object", params={"object": "牛奶"}),
            probe.snapshot(active_object_names=["冰箱里的牛奶"]),
        )
        assert decision.reason == "effect_already_satisfied"
        assert probe.log == list(support.GATE_ORDER)

    @pytest.mark.parametrize(
        ("cut", "expect"),
        (
            (1, "disabled"),
            (2, "ambiguous_params"),
            (5, "quota_exceeded"),
        ),
    )
    def test_l1_short_circuit_stops_the_following_gates(self, probe, cut, expect):
        snapshot = probe.snapshot(
            action_enabled=cut != 1,
            active_count=5 if cut == 5 else 0,
            max_active=5,
        )
        intent = probe.intent(confidence="tentative" if cut == 2 else "confident")
        assert evaluate_gates(intent, snapshot).reason == expect
        assert probe.log == list(support.GATE_ORDER[:cut])

    @pytest.mark.asyncio
    async def test_l1_the_chain_runs_the_three_named_gates_once_in_order(
        self, db_session_factory, action_chain_on, monkeypatch, gate_function_spy
    ):
        _wire_capability(monkeypatch, _memory_capability())
        record = await action_engine.run_action_planning(USER, _memory_intent(), source="autonomy")
        assert record.status == "succeeded"
        assert gate_function_spy == ["_check_g3", "_check_g4", "_check_g6"]

    @pytest.mark.asyncio
    async def test_l1_the_six_gates_are_reached_through_the_bridge(
        self, db_session_factory, action_chain_on, monkeypatch, gate_function_spy, repo_write_probe
    ):
        """计划侧入口：`PlanExecutorBridge.execute_step` 同样完整经过六闸门。"""
        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)
        plan = _plan(MEMORY_TOOL)
        outcome = await _bridge().execute_step(
            _goal(), plan, plan.sub_goals[0], plan5.ctx(MEMORY_TOOL)
        )
        assert gate_function_spy == ["_check_g3", "_check_g4", "_check_g6"]
        assert outcome.status == "succeeded"
        assert outcome.tool_id == MEMORY_TOOL
        assert capability.calls == [{"fact": "小明喜欢喝咖啡"}]


def _capability_registry_without_reminder():
    return stub_registry(StubCapability(name="memory", action="save", required=["fact"]))


# --- L2 五段短路 --------------------------------------------------------------


class TestFiveSegments:
    """I2 / L2：`ToolExecutor.run` 五段顺序固定、各一次（§4.2.4）。"""

    @pytest.mark.asyncio
    async def test_l2_five_segments_run_once_each_in_order(self, db_session_factory, action_chain_on):
        from app.services.action.executor import CapabilityExecutor

        registry = support.builtin_registry()
        capability = _memory_capability()
        log = support.SegmentLog()
        executor = support.instrumented_executor(
            registry,
            CapabilityExecutor(stub_registry(capability), 2.0),
            get_settings_snapshot(),
            log,
        )
        invocation = _invocation(registry, MEMORY_TOOL)
        execution = await executor.run(registry.resolve(MEMORY_TOOL), invocation, _tool_ctx())
        assert execution.status == "succeeded"
        assert log.log == list(support.SEGMENT_ORDER)
        assert capability.calls == [{"fact": "小明喜欢喝咖啡"}]

    @pytest.mark.asyncio
    async def test_l2_the_chain_runs_the_five_segments_once_each(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        log = support.SegmentLog()
        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)
        monkeypatch.setattr(action_engine, "ToolExecutor", support.executor_class_factory(log))

        plan = _plan(MEMORY_TOOL)
        outcome = await _bridge().execute_step(
            _goal(), plan, plan.sub_goals[0], plan5.ctx(MEMORY_TOOL)
        )
        assert log.log == list(support.SEGMENT_ORDER)
        assert outcome.status == "succeeded"
        assert capability.calls == [{"fact": "小明喜欢喝咖啡"}]
        assert repo_write_probe.outbox == []


# --- L3 / L4 前置段失败零外部调用 ----------------------------------------------


class TestZeroExternalCallsOnPreSegmentFailures:
    """I3 / L3：任一前置段失败 → `invoke` 未触达、零台账写入、零网络。"""

    @pytest.mark.asyncio
    async def test_l3_resolve_segment_failure_never_invokes(
        self, db_session_factory, action_chain_on, override_settings, repo_write_probe
    ):
        """① resolve：执行期工具已被禁用 → 终态 `unavailable`，只经过第一段。"""
        from app.services.action.executor import CapabilityExecutor

        override_settings(v24_tool_disabled_ids=MEMORY_TOOL)
        registry = support.builtin_registry()
        capability = _memory_capability()
        log = support.SegmentLog()
        executor = support.instrumented_executor(
            registry,
            CapabilityExecutor(stub_registry(capability), 2.0),
            get_settings_snapshot(),
            log,
        )
        execution = await executor.run(
            registry.resolve(MEMORY_TOOL), _invocation(registry, MEMORY_TOOL), _tool_ctx()
        )
        assert execution.status == "unavailable"
        assert execution.result["failure_kind"] == "unavailable"
        assert log.log == ["resolve"]
        assert capability.calls == []
        assert repo_write_probe.total == 0

    @pytest.mark.asyncio
    async def test_l3_permission_segment_failure_never_invokes(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """② permission：`user.*` 不受信命名空间 → `denied`，不经 ③④⑤。"""
        from app.services.action.executor import CapabilityExecutor

        registry = ToolRegistry()
        registry.register(untrusted_definition(), get_capability_registry().get("memory"))
        capability = _memory_capability()
        log = support.SegmentLog()
        executor = support.instrumented_executor(
            registry,
            CapabilityExecutor(stub_registry(capability), 2.0),
            get_settings_snapshot(),
            log,
        )
        execution = await executor.run(
            registry.resolve(UNTRUSTED_TOOL), _invocation(registry, UNTRUSTED_TOOL), _tool_ctx()
        )
        assert execution.status == "denied"
        assert execution.permission["decision"] == "deny"
        assert log.log == ["resolve", "permission"]
        assert capability.calls == []

    @pytest.mark.asyncio
    async def test_l3_validate_segment_failure_never_invokes(
        self, db_session_factory, action_chain_on, repo_write_probe
    ):
        """③ validate：参数非法 → `invalid`，不经 ④⑤。"""
        from app.services.action.executor import CapabilityExecutor

        registry = support.builtin_registry()
        capability = _memory_capability()
        log = support.SegmentLog()
        executor = support.instrumented_executor(
            registry,
            CapabilityExecutor(stub_registry(capability), 2.0),
            get_settings_snapshot(),
            log,
        )
        invocation = _invocation(
            registry, MEMORY_TOOL, params={"fact": "x", "memory_type": "not_a_memory_type"}
        )
        execution = await executor.run(registry.resolve(MEMORY_TOOL), invocation, _tool_ctx())
        assert execution.status == "invalid"
        assert execution.validation is not None and execution.validation["passed"] is False
        assert log.log == ["resolve", "permission", "validate"]
        assert capability.calls == []

    @pytest.mark.asyncio
    async def test_l3_chain_denied_writes_only_the_gate_ledger(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """链路层 ②：拒绝 → 台账落 `cancelled/permission_denied`，零能力调用、零 outbox。"""
        registry = ToolRegistry()
        registry.register(untrusted_definition(), get_capability_registry().get("memory"))
        _wire_registry(monkeypatch, registry)
        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)

        record = await action_engine.run_action_planning(USER, _memory_intent(), source="autonomy")

        assert capability.calls == []
        assert record.status == "cancelled"
        assert record.gate_reason == "permission_denied"
        assert record.steps[0]["permission"]["decision"] == "deny"
        assert repo_write_probe.outbox == []
        assert repo_write_probe.distinct_record_ids() == {record.id}
        assert len(action_repository.list_records(USER)) == 1

    @pytest.mark.asyncio
    async def test_l3_chain_invalid_params_writes_only_the_gate_ledger(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)
        record = await action_engine.run_action_planning(
            USER,
            _memory_intent({"fact": "x", "memory_type": "not_a_memory_type"}),
            source="autonomy",
        )
        assert capability.calls == []
        assert record.status == "cancelled"
        assert record.gate_reason == "invalid_params"
        assert repo_write_probe.outbox == []

    @pytest.mark.asyncio
    async def test_l4_confirm_required_has_zero_external_calls(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """I4 / L4：`confirm_required` → 零能力调用、`status="planned"`、确认流已登记。"""
        from tests.v24.tool005_support import notification_capability

        capability = notification_capability()
        _wire_capability(monkeypatch, capability)

        record = await action_engine.run_action_planning(USER, _send_intent(), source="autonomy")

        assert capability.calls == []
        assert record.status == "planned"
        assert record.gate_reason == "pending_confirmation"
        assert record.steps[0]["permission"]["decision"] == "confirm_required"
        assert repo_write_probe.outbox == []
        pending = get_confirmation_service().pending(USER)
        assert len(pending) == 1
        assert pending[0].dedupe_key == record.dedupe_key

    @pytest.mark.asyncio
    async def test_l4_confirm_required_blocks_the_plan_step_without_dispatching_again(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """计划侧：`confirm_required` 归一为 `blocked`，步骤留在计划里等确认。"""
        from tests.v24.tool005_support import notification_capability

        capability = notification_capability()
        _wire_capability(monkeypatch, capability)
        plan = _plan(NOTIFICATION_TOOL, capability="send_notification")
        outcome = await _bridge().execute_step(
            _goal(), plan, plan.sub_goals[0], plan5.ctx(NOTIFICATION_TOOL)
        )
        assert outcome.status == "blocked"
        assert outcome.failure_kind is None
        assert capability.calls == []
        updated = _bridge().reconcile(outcome, plan.sub_goals[0], max_attempts=2)
        assert updated.status == "in_progress"
        assert updated.attempt_count == 0

    @pytest.mark.asyncio
    async def test_l5_weak_validation_rejection_never_reaches_execution(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """L5：规划期弱校验不过的步骤不进入执行——零 `ActionRecord`。"""
        from app.services.planning import decompose as decompose_mod
        from app.services.planning.decompose import TaskDecomposer

        from . import plan004_support as plan4

        proposal = plan4.proposal(
            plan4.step(1, params={"content": "只有内容，缺 due_at"})
        )
        result = TaskDecomposer(registry=support.builtin_registry()).decompose(
            proposal,
            plan4.make_goal(),
            plan4.make_ctx(support.REMINDER_CREATE),
            settings=get_settings_snapshot(),
        )
        assert result.passed is False
        assert any(
            error.startswith(WEAK_VALIDATION_REASON) for error in result.binding_errors
        )
        assert decompose_mod.REASON_INVALID_PARAMS == WEAK_VALIDATION_REASON
        assert repo_write_probe.total == 0
        assert action_repository.list_records(USER) == []


# --- Step 6 授权 / 校验分层 ----------------------------------------------------


class TestAuthorisationAndValidationLayers:
    """I8 / I9 / I10 与 U15：规划期弱校验、执行期强校验唯一权威、授权不重试。"""

    def test_planning_time_weak_validation_only_asks_for_required_params(self):
        """规划期只问「必填齐备」：类型 / 枚举 / 语义一律留给执行期（§5.2）。"""
        from app.services.planning import decompose as decompose_mod

        from . import plan004_support as plan4

        complete_but_illegal = plan4.proposal(
            plan4.step(
                1,
                params={
                    "content": "提醒内容",
                    "due_at": "2026-09-16T09:00:00",
                    "importance": "not_an_importance",
                },
            )
        )
        result = decompose_mod.TaskDecomposer(
            registry=support.builtin_registry()
        ).decompose(
            complete_but_illegal,
            plan4.make_goal(),
            plan4.make_ctx(support.REMINDER_CREATE),
            settings=get_settings_snapshot(),
        )
        assert result.passed is True
        assert result.binding_errors == []

    @pytest.mark.asyncio
    async def test_execution_time_validator_is_the_only_authority(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """同一份非法参数：规划期放行（必填齐备），执行期 `ParamValidator` 拒（唯一权威）。"""
        from app.services.planning import decompose as decompose_mod

        from . import plan004_support as plan4

        params = {"fact": "小明喜欢喝咖啡", "memory_type": "not_a_memory_type"}
        proposal = plan4.proposal(
            plan4.step(1, capability="remember_fact", params=params, tool_id=MEMORY_TOOL)
        )
        decomposed = decompose_mod.TaskDecomposer(
            registry=support.builtin_registry()
        ).decompose(
            proposal,
            plan4.make_goal(),
            plan4.make_ctx(MEMORY_TOOL),
            settings=get_settings_snapshot(),
        )
        assert decomposed.passed is True

        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)
        record = await action_engine.run_action_planning(
            USER, _memory_intent(params), source="autonomy"
        )
        assert capability.calls == []
        assert record.status == "cancelled"
        assert record.gate_reason == "invalid_params"
        assert record.steps[0]["validation"]["passed"] is False

    @pytest.mark.asyncio
    async def test_permission_denied_is_never_retried(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """I9：授权拒绝非瞬时——不重试、无 `next_retry_at`、步骤直接 `failed`。"""
        registry = ToolRegistry()
        registry.register(untrusted_definition(), get_capability_registry().get("memory"))
        _wire_registry(monkeypatch, registry)
        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)

        plan = _plan(UNTRUSTED_TOOL)
        outcome = await _bridge(registry=registry).execute_step(
            _goal(), plan, plan.sub_goals[0], plan5.ctx(UNTRUSTED_TOOL)
        )
        assert outcome.status == "blocked"
        assert outcome.failure_kind == "denied"
        updated = _bridge(registry=registry).reconcile(outcome, plan.sub_goals[0], max_attempts=2)
        assert updated.status == "failed"
        assert updated.attempt_count == 0
        assert outcome.failure_kind not in action_engine.RETRYABLE_FAILURES
        assert updated.failure_note is not None and "denied" in updated.failure_note

        record = action_repository.list_records(USER)[0]
        assert record.attempt == 1
        assert record.next_retry_at is None
        assert capability.calls == []

    @pytest.mark.asyncio
    async def test_confirm_round_approval_resumes_with_the_same_params_and_key(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """I8 ①：批准 → 原记录续跑，参数与幂等键复用原调用（不产生第二条台账）。"""
        from tests.v24.tool005_support import notification_capability

        capability = notification_capability()
        _wire_capability(monkeypatch, capability)
        record = await action_engine.run_action_planning(USER, _send_intent(), source="autonomy")
        request = get_confirmation_service().pending(USER)[0]

        resumed = await action_engine.run_confirmation_round(
            USER, request.request_id, approved=True, session_id="s-plan6"
        )

        assert resumed is not None and resumed.id == record.id
        assert capability.calls == [{"content": "明天开会"}]
        assert resumed.status == "succeeded"
        assert len(action_repository.list_records(USER)) == 1

    @pytest.mark.asyncio
    async def test_confirm_round_denial_turns_the_record_failed(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """I8 ②：否定 → 原记录转 `cancelled/permission_denied`，零外部调用。"""
        from tests.v24.tool005_support import notification_capability

        capability = notification_capability()
        _wire_capability(monkeypatch, capability)
        record = await action_engine.run_action_planning(USER, _send_intent(), source="autonomy")
        request = get_confirmation_service().pending(USER)[0]

        resumed = await action_engine.run_confirmation_round(
            USER, request.request_id, approved=False
        )

        assert capability.calls == []
        assert resumed is not None and resumed.id == record.id
        assert resumed.status == "cancelled"
        assert resumed.gate_reason == "permission_denied"

    @pytest.mark.asyncio
    async def test_expired_confirmation_is_never_executed(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe
    ):
        """I8 ③：TTL 过期 → 批准亦不执行，记录转 `cancelled`。"""
        from app.core.db import TriggerRegistryRow
        import app.repositories.trigger_registry_repository as trigger_repository
        from tests.v24.tool005_support import notification_capability

        capability = notification_capability()
        _wire_capability(monkeypatch, capability)
        await action_engine.run_action_planning(USER, _send_intent(), source="autonomy")
        request = get_confirmation_service().pending(USER)[0]

        stale = datetime.now() - timedelta(hours=48)
        row = trigger_repository.get(request.request_id)
        payload = dict(row.payload)
        payload["expires_at"] = stale.isoformat()
        session = db_session_factory()
        session.query(TriggerRegistryRow).filter(
            TriggerRegistryRow.trigger_key == request.request_id
        ).update({"payload": payload, "due_at": stale})
        session.commit()

        resumed = await action_engine.run_confirmation_round(
            USER, request.request_id, approved=True
        )
        assert capability.calls == []
        assert resumed is not None and resumed.status == "cancelled"

    @pytest.mark.asyncio
    async def test_quota_exhaustion_is_not_relaxed(
        self, db_session_factory, action_chain_on, monkeypatch, repo_write_probe, override_settings
    ):
        """I10：额度未放宽——闸门 5 拒，能力零调用、零 outbox；台账仍留一条裁决记录。

        `action_max_active_per_user` 的合法下限为 1（`validate_action_config`），故额度耗尽的
        构造方式是「上限 1 + 已存在一条 active 台账」，而非把上限设为 0。
        """
        from app.models.action import ActionRecord

        capability = _memory_capability()
        _wire_capability(monkeypatch, capability)
        override_settings(action_max_active_per_user="1")
        action_repository.save_record(
            ActionRecord(
                id=action_repository.new_record_id(),
                user_id=USER,
                action_type="remember_fact",
                status="planned",
                dedupe_key="plan6:existing:1:1",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )

        record = await action_engine.run_action_planning(USER, _memory_intent(), source="autonomy")

        assert capability.calls == []
        assert record.status == "cancelled"
        assert record.gate_reason == "quota_exceeded"
        assert repo_write_probe.outbox == []
        assert record.attempt == 1 and record.next_retry_at is None
        assert len(action_repository.list_records(USER)) == 2

    @pytest.mark.asyncio
    async def test_action_master_gate_off_creates_no_record_at_all(
        self, db_session_factory, action_chain_on, override_settings
    ):
        """总闸 off 才是真正「不产生 `ActionRecord`」的路径（与额度拒绝区分）。"""
        override_settings(action_enabled="false")
        assert await action_engine.run_action_planning(USER, _memory_intent()) is None
        assert action_repository.list_records(USER) == []


def get_settings_snapshot():
    from app.core.settings import get_settings

    return get_settings()


def _tool_ctx(user_id: str = USER) -> ToolContext:
    return ToolContext(
        user_id=user_id,
        now=support.NOW,
        settings=get_settings_snapshot(),
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
    )


def _invocation(
    registry: ToolRegistry, tool_id: str, *, params: dict | None = None, intent=None
):
    from app.models.tool import ToolInvocation

    assert registry.get(tool_id) is not None
    payload = {"fact": "小明喜欢喝咖啡"} if params is None else params
    return ToolInvocation(
        tool_id=tool_id,
        params=payload,
        intent=intent if intent is not None else _memory_intent(payload),
        dedupe_key="plan:plan6-goal:1:1",
        goal_id=GOAL_ID,
    )


@pytest.fixture
def gate_function_spy(monkeypatch):
    """三道具名闸门函数的调用序探针（`planner._check_g3 / _check_g4 / _check_g6`）。"""
    calls: list[str] = []
    for name in support.NAMED_GATE_CHECKS:
        original = getattr(planner_mod, name)

        def _spy(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(planner_mod, name, _spy)
    return calls
