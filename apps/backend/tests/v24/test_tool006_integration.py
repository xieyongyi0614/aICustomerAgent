"""TOOL-006 §6.2 / §6.3：自治 tick 实传工具面、端到端工具链、三账对齐与额度对照（E6/E7）。"""

import inspect
from datetime import timedelta

import pytest

from app.application import (
    action_engine,
    autonomy_engine,
    life_loop,
    outbox_consumer,
    world_engine,
)
from app.application.post_process import reset_user_write_locks
from app.character.asuna.action import PROACTIVE_ACTION_MAP
from app.core import llm_factory
from app.models.action import ActionIntent
from app.models.autonomy import PROACTIVE_INTENTION_MAP, AutonomyVerdict, TriggerSignal
from app.repositories import (
    action_repository,
    decision_repository,
    loop_run_repository,
    outbox_repository,
    world_repository,
)
from app.services import decision_pipeline, trigger_evaluator
from app.services.tool.executor import ToolExecutor
from tests.v24.tool006_support import (
    NOW,
    SESSION,
    USER,
    await_until,
    builtin_registry,
    normalized_source,
    seed_tick_fixture,
)

USER_OFF = "u-tool006-off"
USER_ON = "u-tool006-on"
TOOL_ID = "builtin.reminder.create"

V23_PRODUCE_SOURCE = (
    "async def _produce_autonomy_action( verdict, user_id: str, session_id: str, now: datetime "
    ") -> bool: \"\"\"自治产行动分支（autonomy-integration.md §4）：默认关，仅命中开启才求值。\"\"\" "
    "settings = get_settings() if not settings.autonomy_action_enabled: return False "
    "action_type = PROACTIVE_ACTION_MAP.get(verdict.intention or \"\") "
    "if action_type is None: return False "
    "if _autonomy_action_today(user_id, now) >= settings.autonomy_action_daily_limit: "
    "logger.info(\"自治产行动日额度已满：%s\", user_id) return False "
    "intent = ActionIntent( action_type=action_type, confidence=\"confident\", "
    "params=_params_for_autonomy_action(action_type, now), "
    "dedupe_key=f\"autonomy:{action_type}:{now.date().isoformat()}\", ) "
    "record = await run_action_planning( user_id, intent, session_id=session_id, source=\"autonomy\" ) "
    "return record is not None"
)


@pytest.fixture(autouse=True)
def _clean_trigger_state():
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


def _verdict(user_id: str, intention: str = "check_in") -> AutonomyVerdict:
    return AutonomyVerdict(
        decision="act",
        reason="触发检查，存在 user_care 目标",
        trigger=TriggerSignal(
            type="conversation_inactivity",
            user_id=user_id,
            detected_at=NOW,
            dedupe_key=f"tool006:{user_id}",
        ),
        goal_id="goal-tool006",
        intention=intention,
    )


async def _produce(user_id: str) -> bool:
    """产一次自治行动；调用方负责世界已就绪（G3 世界依赖闸需要 world 存在）。"""
    return await autonomy_engine._produce_autonomy_action(
        _verdict(user_id), user_id, session_id=SESSION, now=NOW
    )


def _ensure_world(*user_ids: str) -> None:
    for user_id in user_ids:
        world_engine.ensure_world(user_id)


def _autonomy_records(user_id: str) -> list:
    return [
        record
        for record in action_repository.list_records(user_id, limit=50)
        if record.source == "autonomy"
    ]


def _spy_pipeline(monkeypatch) -> list[dict]:
    captured: list[dict] = []
    real = decision_pipeline.run_pipeline

    def spy(**kwargs):
        captured.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(decision_pipeline, "run_pipeline", spy)
    return captured


def _seed_active_record(user_id: str) -> None:
    record = action_engine.new_record(
        ActionIntent(action_type="create_reminder", confidence="confident", params={}),
        user_id,
        SESSION,
    )
    record.status = "planned"
    action_repository.save_record(record)


def _outbox_rows(user_id: str) -> list:
    return [
        row
        for row in outbox_repository.list_recent(limit=50)
        if (row.payload or {}).get("user_id") == user_id
    ]


def _world_events(user_id: str) -> list:
    return world_repository.list_events(
        world_repository.world_id_for(user_id), order="created_at_desc"
    )


# --- §5 Step1：自治 tick 首次实传工具面 -----------------------------------------


@pytest.mark.asyncio
async def test_tick_passes_surface_capabilities_into_pipeline(
    db_session_factory, fake_llm, monkeypatch, override_settings, v24_tool_env
):
    """断层 B7 关闭：自治 tick 的工具面首次进入决策管线候选（审计可见）。"""
    override_settings(
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        V21_AGENT_RUNTIME_ENABLED="true",
        OBSERVABILITY_PERSIST_ENABLED="true",
    )
    v24_tool_env(v24_tool_system_enabled=True)
    captured = _spy_pipeline(monkeypatch)
    seed_tick_fixture()
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered = await autonomy_engine.tick(user_ids=[USER], llm=llm, now=NOW)
    finally:
        reset_user_write_locks()
    assert len(delivered) == 1

    assert captured, "自治 tick 必须调用决策管线"
    capabilities = captured[-1]["capabilities"]
    surface = autonomy_engine.resolve_autonomy_surface(USER, NOW)
    assert capabilities == list(surface.tool_ids)
    assert capabilities and all(not tool_id.startswith("channel.") for tool_id in capabilities)

    assert await await_until(
        lambda: any(
            row.decision == "act"
            for row in decision_repository.search(user_id=USER, kind="proactive_autonomy")
        )
    )
    record = next(
        row
        for row in decision_repository.search(user_id=USER, kind="proactive_autonomy")
        if row.decision == "act"
    )
    capability_candidates = [
        candidate
        for candidate in (record.candidates or {}).get("candidates", [])
        if candidate["source"] == "capability"
    ]
    assert {candidate["tool_id"] for candidate in capability_candidates} == set(capabilities)

    session = __import__(
        "app.services.trace_collector", fromlist=["get_trace_collector"]
    ).get_trace_collector().get(delivered[0])
    step = next(s for s in session.steps if s.name == autonomy_engine.AUTONOMY_TOOL_SURFACE_STEP)
    assert step.extra["run_kind"] == "autonomous_tick"
    assert step.extra["tool_ids"] == capabilities


@pytest.mark.asyncio
async def test_tick_keeps_capabilities_none_when_flag_off(
    db_session_factory, fake_llm, monkeypatch, override_settings, v24_tool_env
):
    override_settings(
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        V21_AGENT_RUNTIME_ENABLED="true",
        OBSERVABILITY_PERSIST_ENABLED="true",
    )
    v24_tool_env(v24_tool_system_enabled=False)
    captured = _spy_pipeline(monkeypatch)
    seed_tick_fixture()
    llm = fake_llm(response=["忙完了吗？"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered = await autonomy_engine.tick(user_ids=[USER], llm=llm, now=NOW)
    finally:
        reset_user_write_locks()
    assert len(delivered) == 1
    assert captured[-1]["capabilities"] is None
    session = __import__(
        "app.services.trace_collector", fromlist=["get_trace_collector"]
    ).get_trace_collector().get(delivered[0])
    assert autonomy_engine.AUTONOMY_TOOL_SURFACE_STEP not in [s.name for s in session.steps]


# --- §6.2 端到端链路 + 三账对齐 -------------------------------------------------


@pytest.mark.asyncio
async def test_autonomy_decision_to_world_write_through_outbox(
    db_session_factory, override_settings, v24_tool_env
):
    """Autonomous Decision → Create Action → Execute Tool → Receive Result →
    Update World State（唯一合法路径：effects(world) → outbox → world_engine）。"""
    override_settings(
        V2_LIFE_LOOP_ENABLED="true",
        V2_ACTION_OUTBOX_ENABLED="true",
        V21_AGENT_RUNTIME_ENABLED="true",
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        AUTONOMY_ACTION_ENABLED="true",
        OBSERVABILITY_PERSIST_ENABLED="true",
    )
    v24_tool_env(v24_tool_system_enabled=True)
    seed_tick_fixture()
    _ensure_world(USER)
    trigger_evaluator.register_followup(USER, NOW - timedelta(minutes=1), "下午面试")

    stats = await life_loop.run_life_loop_tick(now=NOW)
    assert stats["user_cycles"] == 1 and stats["aborted"] == 0

    records = _autonomy_records(USER)
    assert len(records) == 1
    record = records[0]
    assert record.status == "succeeded"
    assert record.dedupe_key == f"autonomy:create_reminder:{NOW.date().isoformat()}"
    assert record.params["content"] == "休息一下"
    assert record.params["importance"] == "normal"
    assert record.steps[0]["tool_id"] == TOOL_ID
    assert record.steps[0]["status"] == "succeeded"

    rows = _outbox_rows(USER)
    assert len(rows) == 1
    assert rows[0].idempotency_key == record.id
    assert rows[0].payload["world_ops"], "工具结果必须经 outbox 延迟投递世界写入"

    outbox_consumer.consume_pending(now=NOW)
    pending = outbox_repository.list_pending(now=NOW)
    assert all(row.idempotency_key != record.id for row in pending)
    events = [event for event in _world_events(USER) if event.type == "reminder"]
    assert events
    assert events[0].payload["outbox_action_id"] == record.id

    # 三账对齐：loop_runs（Run）/ decision_records（决策）/ action_records（行动与工具执行）
    runs = loop_run_repository.list_recent(user_id=USER, run_kind="autonomous_tick")
    assert runs and runs[0].kind == "autonomy" and runs[0].status == "done"
    run = runs[0]
    assert "decision" in [step["step"] for step in run.steps]

    assert await await_until(
        lambda: bool(
            decision_repository.search(user_id=USER, kind="proactive_autonomy")
        )
    )
    decision = next(
        row
        for row in decision_repository.search(user_id=USER, kind="proactive_autonomy")
        if row.decision == "act"
    )
    assert decision.trigger == "scheduled_followup"
    decision_intention = PROACTIVE_INTENTION_MAP[decision.input_snapshot["selected_goal_type"]]
    assert PROACTIVE_ACTION_MAP[decision_intention] == record.action_type
    assert decision.conversation_id == record.session_id
    assert (run.user_id, decision.user_id, record.user_id) == (USER, USER, USER)
    assert run.trigger_type
    assert decision.input_snapshot["tool_facts"]["available"]
    assert record.steps[0]["tool_id"] in decision.input_snapshot["tool_facts"]["available"]


def test_tool_execution_path_never_writes_world_directly():
    """静态断言：工具执行路径不含任何直接世界写（世界写只经 outbox 消费器）。"""
    for source in (
        inspect.getsource(action_engine._execute_plan_via_tools),
        inspect.getsource(ToolExecutor),
    ):
        assert "world_engine" not in source
        assert "world_repository" not in source


# --- §6.2 额度未放宽（V2.3.0 对照） ---------------------------------------------


@pytest.mark.asyncio
async def test_daily_limit_not_relaxed_by_tool_system(
    db_session_factory, override_settings, v24_tool_env
):
    override_settings(
        V2_LIFE_LOOP_ENABLED="true",
        V2_ACTION_OUTBOX_ENABLED="true",
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        AUTONOMY_ACTION_ENABLED="true",
        AUTONOMY_ACTION_DAILY_LIMIT="1",
    )
    _ensure_world(USER_OFF, USER_ON)
    v24_tool_env(v24_tool_system_enabled=False)
    off = (await _produce(USER_OFF), await _produce(USER_OFF))
    v24_tool_env(v24_tool_system_enabled=True)
    on = (await _produce(USER_ON), await _produce(USER_ON))

    assert off == on == (True, False)
    assert autonomy_engine._autonomy_action_today(USER_OFF, NOW) == 1
    assert autonomy_engine._autonomy_action_today(USER_ON, NOW) == 1
    assert [record.status for record in _autonomy_records(USER_OFF)] == [
        record.status for record in _autonomy_records(USER_ON)
    ]


@pytest.mark.asyncio
async def test_max_active_per_user_not_relaxed_by_tool_system(
    db_session_factory, override_settings, v24_tool_env
):
    override_settings(
        V2_LIFE_LOOP_ENABLED="true",
        V2_ACTION_OUTBOX_ENABLED="true",
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        AUTONOMY_ACTION_ENABLED="true",
        AUTONOMY_ACTION_DAILY_LIMIT="5",
        ACTION_MAX_ACTIVE_PER_USER="1",
    )
    _ensure_world(USER_OFF, USER_ON)
    _seed_active_record(USER_OFF)
    _seed_active_record(USER_ON)
    v24_tool_env(v24_tool_system_enabled=False)
    await _produce(USER_OFF)
    v24_tool_env(v24_tool_system_enabled=True)
    await _produce(USER_ON)

    off_record = _autonomy_records(USER_OFF)[0]
    on_record = _autonomy_records(USER_ON)[0]
    assert (off_record.status, off_record.gate_reason) == (
        on_record.status,
        on_record.gate_reason,
    ) == ("cancelled", "quota_exceeded")
    assert off_record.steps == [] and on_record.steps == []


@pytest.mark.asyncio
async def test_daily_limit_hit_produces_no_tool_call(
    db_session_factory, override_settings, v24_tool_env
):
    """E7：命中日额度上限 → 记录日志、不产行动、不消耗工具调用。"""
    override_settings(
        V2_LIFE_LOOP_ENABLED="true",
        V2_ACTION_OUTBOX_ENABLED="true",
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        AUTONOMY_ACTION_ENABLED="true",
        AUTONOMY_ACTION_DAILY_LIMIT="1",
    )
    v24_tool_env(v24_tool_system_enabled=True)
    _ensure_world(USER_ON)
    assert await _produce(USER_ON) is True
    assert await _produce(USER_ON) is False
    assert len(_autonomy_records(USER_ON)) == 1
    assert _autonomy_records(USER_ON)[0].steps
    assert len(_outbox_rows(USER_ON)) == 1
    assert not [event for event in _world_events(USER_ON) if event.type == "reminder"]


# --- §6.3 E6：执行前重新判状态 ------------------------------------------------


@pytest.mark.asyncio
async def test_tool_tripped_between_surface_and_execution(
    monkeypatch, db_session_factory, override_settings, v24_tool_env
):
    """E6：同一 tick 内工具面与执行时状态不一致 → 执行前重新判状态 → unavailable，
    不产生行动副作用（无世界写入、无 outbox 登记）。"""
    override_settings(
        V2_LIFE_LOOP_ENABLED="true",
        V2_ACTION_OUTBOX_ENABLED="true",
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        AUTONOMY_ACTION_ENABLED="true",
    )
    v24_tool_env(v24_tool_system_enabled=True)
    registry = builtin_registry()
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(action_engine, "get_tool_registry", lambda: registry)

    _ensure_world(USER)
    surface = autonomy_engine.resolve_autonomy_surface(USER, NOW)
    assert TOOL_ID in surface.tool_ids
    registry.mark_tripped(TOOL_ID)

    assert await _produce(USER) is True
    record = _autonomy_records(USER)[0]
    assert (record.status, record.gate_reason) == ("cancelled", "capability_unavailable")
    assert record.steps[0]["status"] == "skipped"
    assert all(
        not (row.payload or {}).get("world_ops") for row in _outbox_rows(USER)
    )
    assert not [event for event in _world_events(USER) if event.type == "reminder"]


# --- §6.2 冻结面：形态不变 / 零 diff / 预算不变 --------------------------------


def test_produce_autonomy_action_shape_unchanged():
    """`_produce_autonomy_action` 形态不变（diff 断言）：与 V2.3.0 源码归一化后逐字一致。"""
    assert normalized_source(autonomy_engine._produce_autonomy_action) == V23_PRODUCE_SOURCE


def test_decision_pipeline_untouched_by_tool006():
    """`decision_pipeline.py` 无 TOOL-006 输入面：本任务只改调用方传参。

    TOOL-009 追加的是 `tool_insights`（工具效能 Insight 只读反哺），非 TOOL-006 面。
    """
    source = inspect.getsource(decision_pipeline)
    assert "autonomy_engine" not in source
    assert "tool_facts" not in source
    signature = inspect.signature(decision_pipeline.run_pipeline)
    assert list(signature.parameters) == [
        "stack",
        "snapshot",
        "trigger_intention",
        "trigger_goal_id",
        "capabilities",
        "chat_response",
        "chat_response_intention",
        "chat_response_goal_id",
        "run",
        "now",
        "world_impacts",
        "world_schedule",
        "tool_insights",
    ]
    assert signature.parameters["capabilities"].default is None
    assert signature.parameters["tool_insights"].default is None


def test_llm_gateway_budget_tier_and_math_unchanged():
    """`llm_gateway` 预算档位与数学不变：自治仍是 background 档，无新增输入面。"""
    from app.application.agent_runtime import llm_gateway, profiles

    source = inspect.getsource(llm_gateway)
    assert "tool_facts" not in source
    assert "capabilities" not in source
    profile = profiles.get_profile("autonomous_tick")
    assert profile.budget_tier == "background"
    assert TOOL_ID not in inspect.getsource(autonomy_engine._produce_autonomy_action)
