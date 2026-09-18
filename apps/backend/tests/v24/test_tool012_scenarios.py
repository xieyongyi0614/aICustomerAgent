"""TOOL-012 端到端场景集 S1~S10（TOOL-012 §2.3 场景表）。

全部离线可跑：LLM 打桩 / 通道打桩 / 内存 SQLite；期望值一律取自既有实现
（`tests/v24/SCENARIO-TEST.md` 逐条给出代码依据）。本文件与 `test_tool_acceptance.py`
的 Gate 判定互补：Gate 判"能不能"，场景判"用起来是什么样"。
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.settings import get_settings
from app.models.tool import (
    PermissionProfile,
    ToolDefinition,
    ToolParameter,
    ToolSchema,
)
from tests.v24 import tool012_support as support
from tests.v24.tool002_support import MAPPING_TABLE
from tests.v24.tool003_support import (
    StubCapability,
    build_executor,
    stub_registry,
)
from tests.v24.tool005_support import SENSITIVE_TOOL_ID, grant, invocation, snapshot
from tests.v24.tool010_support import builtin_registry

pytestmark = pytest.mark.xdist_group("tool012")

USER = "u-tool012-scenario"
SESSION = "s-tool012-scenario"

GRANT_FREE_LEVELS: tuple[str, ...] = ("safe", "normal")

TOOL_LEVELS: dict[str, str] = {row["tool_id"]: row["level"] for row in MAPPING_TABLE}

PRIVILEGED_TOOL_IDS: frozenset[str] = frozenset(
    tool_id for tool_id, level in TOOL_LEVELS.items() if level not in GRANT_FREE_LEVELS
)
"""P0-1：总闸 on + 权限子闸 off 时特权档默认拒绝；要到达能力必须补权限子闸与授权快照。"""


def _env_reaching_capability(tool_id: str, base_env: dict) -> dict:
    """特权档额外打开权限子闸（子闸 off 时那些工具根本走不到能力实现）。"""
    if tool_id not in PRIVILEGED_TOOL_IDS:
        return dict(base_env)
    return {**base_env, "TOOL_PERMISSION_ENABLED": True}


def _grant_snapshot_for(tool_id: str, settings):
    """特权档的授权快照（通配范围覆盖任意声明 scope）；免授权档不需要快照。"""
    if tool_id not in PRIVILEGED_TOOL_IDS:
        return None
    return snapshot(grants=[grant(tool_id, ("*",))], settings=settings)

MASTER_ON = {"TOOL_SYSTEM_ENABLED": True}
CHANNEL_ON = {
    "TOOL_SYSTEM_ENABLED": True,
    "TOOL_CHANNEL_ENABLED": True,
    "FEISHU_ENABLED": True,
}
PERMISSION_ON = {**MASTER_ON, "TOOL_PERMISSION_ENABLED": True}
FULL_ON = {
    "TOOL_SYSTEM_ENABLED": True,
    "TOOL_PERMISSION_ENABLED": True,
    "TOOL_SCHEMA_VALIDATION_ENABLED": True,
    "TOOL_OBSERVATION_ENABLED": True,
    "TOOL_SURFACE_ENABLED": True,
    "TOOL_MEMORY_ENABLED": True,
    "TOOL_REFLECTION_ENABLED": True,
    "TOOL_CHANNEL_ENABLED": True,
    "FEISHU_ENABLED": True,
}


FAR_FUTURE = "2026-12-31T09:00:00"


@pytest.fixture(autouse=True)
def _clean_mutable_registries():
    from app.application import life_loop
    from app.services import trigger_evaluator
    from app.services.reflection import triggers

    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()
    triggers.reset_trigger_state()
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()
    triggers.reset_trigger_state()


def _context(user_id: str = USER, now=None, settings=None):
    from app.services.action.registry import ExecutionContext

    return ExecutionContext(
        user_id=user_id,
        record_id="act-tool012-scenario",
        now=now or support._now(),
        settings=settings,
    )


def _stubs_for(registry) -> list[StubCapability]:
    """按注册表声明逐条造能力替身（capability/action 从声明读取，不硬编码）。"""
    seen: set[tuple[str, str]] = set()
    stubs: list[StubCapability] = []
    for definition in registry.list():
        key = (definition.capability, definition.action)
        if key in seen:
            continue
        seen.add(key)
        stubs.append(StubCapability(name=definition.capability, action=definition.action))
    return stubs


def _executor(registry, capability, settings, *, timeout: float = 5.0):
    return build_executor(registry, capability, settings=settings, timeout_seconds=timeout)


def _run(executor, tool_id, params, ctx, *, snapshot_=None):
    binding = executor.registry.resolve(tool_id)
    inv = invocation(tool_id, params)
    return asyncio.run(
        executor.run(binding, inv, ctx, permission_snapshot=snapshot_)
    )


# --- S1 前台工具调用（10 例） ---------------------------------------------------


S1_TOOL_IDS: tuple[str, ...] = support.BUILTIN_TOOL_IDS

S1_PARAMS: dict[str, object] = {
    "content": "在吗",
    "due_at": FAR_FUTURE,
    "importance": "normal",
    "target": "开会",
    "fact": "用户喜欢西瓜",
    "object": "水杯",
    "location": "home.living_room",
    "dimension": "weather",
    "query": "天气",
    "recipient": "ou_asuna",
}


@pytest.mark.parametrize("tool_id", S1_TOOL_IDS)
def test_s1_foreground_tool_call_reaches_capability(monkeypatch, tool_id):
    """用户消息 → 工具选择 → 执行 → 结果归一（每个声明工具各一例）。

    P0-1 后特权档（sensitive 及以上）需要权限子闸 + 授权快照才能到达能力实现。
    """
    env = CHANNEL_ON if tool_id == "channel.feishu.send" else MASTER_ON
    support.apply_flag_env(monkeypatch, _env_reaching_capability(tool_id, env))
    settings = get_settings()
    registry = builtin_registry()
    definition = registry.get(tool_id)
    stub = StubCapability(name=definition.capability, action=definition.action)
    executor = _executor(registry, stub, settings)

    execution = _run(
        executor,
        tool_id,
        dict(S1_PARAMS),
        _context(settings=settings),
        snapshot_=_grant_snapshot_for(tool_id, settings),
    )

    assert execution.tool_id == tool_id
    assert execution.capability == definition.capability
    assert execution.action == definition.action
    assert execution.status == "succeeded"
    assert stub.calls and stub.calls[0]["content"] == "在吗"
    assert execution.result["status"] == "succeeded"
    assert execution.duration_ms is not None


def test_s1_foreground_tool_call_result_carries_observation(monkeypatch):
    """前台工具结果归一：观测闸 on 时 `world.event_id` 等观察键进入结果契约。"""
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_OBSERVATION_ENABLED": True}
    )
    settings = get_settings()
    registry = builtin_registry()
    stub = StubCapability(
        name="reminder",
        action="create",
        behavior=lambda params, ctx: __import__(
            "app.models.action", fromlist=["CapabilityResult"]
        ).CapabilityResult(
            status="succeeded", payload={"world_event_id": "ev-tool012"}
        ),
    )
    executor = _executor(registry, stub, settings)

    execution = _run(
        executor,
        "builtin.reminder.create",
        {"content": "开会", "due_at": "2026-12-31T09:00:00"},
        _context(settings=settings),
    )

    assert execution.result["observations"]["world.event_id"] == "ev-tool012"
    assert execution.result["effects"][0]["kind"] == "world"


# --- S2 参数校验（13 例） -------------------------------------------------------


def _scenario_definition() -> ToolDefinition:
    return ToolDefinition(
        id="builtin.tool012.scenario",
        name="场景探针",
        description="S2 参数校验场景探针",
        namespace="builtin",
        capability="reminder",
        action="create",
        input_schema=ToolSchema(
            semantic_validators=(
                "future_datetime",
                "location_exists",
                "object_in_inventory",
                "recipient_authorized",
                "content_within_budget",
            ),
            parameters=[
                ToolParameter(name="content", type="string", required=True),
                ToolParameter(name="due_at", type="datetime", required=True),
                ToolParameter(name="location", type="string"),
                ToolParameter(name="object", type="string"),
                ToolParameter(name="recipient", type="string"),
                ToolParameter(
                    name="importance", type="string", enum=("low", "normal", "high")
                ),
                ToolParameter(name="repeat", type="integer", min=0, max=7),
                ToolParameter(name="note", type="string", max_length=5),
                ToolParameter(name="code", type="string", pattern=r"^[A-Z]{3}$"),
                ToolParameter(name="email", type="string", format="email"),
            ],
        ),
        permission=PermissionProfile(level="normal", scope=("world",), confirm="never"),
        side_effects=("write_world",),
    )


S2_STRUCTURAL: dict[str, dict] = {
    "missing_required": {},
    "type_mismatch": {"content": "在吗", "repeat": "abc"},
    "enum_invalid": {"content": "在吗", "importance": "urgent"},
    "range_violated": {"content": "在吗", "repeat": 99},
    "length_violated": {"content": "在吗", "note": "超出上限的内容"},
    "pattern_mismatch": {"content": "在吗", "code": "abc"},
    "format_invalid": {"content": "在吗", "email": "not-an-email"},
    "unknown_param": {"content": "在吗", "undeclared": "x"},
}

S2_SEMANTIC: dict[str, tuple[dict, dict]] = {
    "not_future": ({"content": "在吗", "due_at": "2020-01-01T00:00:00"}, {}),
    "location_not_found": (
        {"content": "在吗", "location": "火星基地"},
        {"world": {"locations": ["home.living_room"], "world_enabled": True}},
    ),
    "object_not_in_inventory": (
        {"content": "在吗", "object": "水杯"},
        {"world": {"world_enabled": True}, "inventory": []},
    ),
    "recipient_not_authorized": (
        {"content": "在吗", "recipient": "陌生人"},
        {"authorized_recipients": ["小林"]},
    ),
    "content_over_budget": ({"content": "长" * 4001}, {}),
}


def _s2_executor(settings):
    from app.services.action.executor import CapabilityExecutor
    from app.services.tool.executor import ToolExecutor
    from app.services.tool.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(_scenario_definition())
    capability = StubCapability(name="reminder", action="create", required=["content"])
    return (
        ToolExecutor(
            registry,
            CapabilityExecutor(stub_registry(capability), 5.0),
            settings=settings,
        ),
        capability,
    )


def _s2_context(**overrides):
    from app.services.tool.context import ToolContext

    values = {
        "user_id": USER,
        "now": support._now(),
        "world": {"locations": ["home.living_room"]},
        "inventory": ["水杯"],
        "authorized_recipients": ["小林"],
    }
    values.update(overrides)
    return ToolContext(**values)


@pytest.mark.parametrize("code,params", S2_STRUCTURAL.items())
def test_s2_structural_failure_blocks_execution(monkeypatch, code, params):
    """结构失败在执行前拦下：能力零调用 + 字段级理由。"""
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_SCHEMA_VALIDATION_ENABLED": True}
    )
    settings = get_settings()
    executor, capability = _s2_executor(settings)

    execution = _run(
        executor, "builtin.tool012.scenario", params, _context(settings=settings)
    )

    assert execution.status == "invalid"
    assert capability.calls == []
    assert code in {issue["code"] for issue in execution.validation["structural"]}
    issue = next(
        item for item in execution.validation["structural"] if item["code"] == code
    )
    assert issue["message"]


@pytest.mark.parametrize("code,case", S2_SEMANTIC.items())
def test_s2_semantic_failure_blocks_execution(monkeypatch, code, case):
    """语义失败在执行前拦下：世界事实被当事实用（非降级放行）。"""
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_SCHEMA_VALIDATION_ENABLED": True}
    )
    settings = get_settings()
    executor, capability = _s2_executor(settings)
    params, overrides = case
    params = {"due_at": FAR_FUTURE, **params}

    execution = _run(
        executor,
        "builtin.tool012.scenario",
        params,
        _s2_context(**overrides),
    )

    assert execution.status == "invalid"
    assert execution.validation["structural"] == []
    assert code in {issue["code"] for issue in execution.validation["semantic"]}
    assert capability.calls == []


# --- S3 权限与确认（5 例） ------------------------------------------------------


def _confirmation_service(settings):
    from app.services.tool.confirmation import ConfirmationService, reset_session_grants

    reset_session_grants()
    return ConfirmationService(settings)


def _confirm_decision(scope=("self",), kind="first_time"):
    from app.services.tool.permission import (
        DECISION_CONFIRM_REQUIRED,
        PermissionDecision,
    )

    return PermissionDecision(
        decision=DECISION_CONFIRM_REQUIRED,
        level="sensitive",
        reason="first_time_confirmation",
        confirm_prompt="要我现在把这条消息发出去吗？",
        scope_required=tuple(scope),
        confirm_kind=kind,
    )


def test_s3_default_deny_without_grant(monkeypatch):
    """① 默认拒绝：无授权 → 首次确认（pending_confirmation），能力零调用。"""
    support.apply_flag_env(monkeypatch, PERMISSION_ON)
    settings = get_settings()
    capability = StubCapability(name="notification", action="send", required=["content"])
    executor = _executor(builtin_registry(), capability, settings)

    execution = _run(
        executor,
        SENSITIVE_TOOL_ID,
        {"content": "在吗"},
        _context(settings=settings),
        snapshot_=snapshot(grants=[], settings=settings),
    )

    assert execution.status == "pending_confirmation"
    assert execution.permission["reason"] == "first_time_confirmation"
    assert capability.calls == []


def test_s3_first_time_confirmation_registers_pending_row(
    db_session_factory, monkeypatch
):
    """② 首次确认：登记待确认行（trigger_registry 复用），本轮零外发。"""
    support.apply_flag_env(monkeypatch, PERMISSION_ON)
    settings = get_settings()
    service = _confirmation_service(settings)
    now = support._now()

    request = service.request(
        invocation(SENSITIVE_TOOL_ID, {"content": "明天开会"}),
        _confirm_decision(),
        _context(now=now, settings=settings),
    )

    assert request is not None
    assert request.is_pending()
    assert request.prompt
    assert service.get(request.request_id) is not None
    assert [item.request_id for item in service.pending(USER, now)] == [
        request.request_id
    ]


def test_s3_grant_reuse_within_ttl(monkeypatch):
    """③ TTL 复用：批准落 grant 后同工具再次调用直接放行（grant_matched）。"""
    support.apply_flag_env(monkeypatch, PERMISSION_ON)
    settings = get_settings()
    capability = StubCapability(name="notification", action="send", required=["content"])
    executor = _executor(builtin_registry(), capability, settings)
    granted = snapshot(
        grants=[{"tool_id": SENSITIVE_TOOL_ID, "scope": ["self"], "expires_at": None}],
        settings=settings,
    )

    first = _run(
        executor,
        SENSITIVE_TOOL_ID,
        {"content": "在吗"},
        _context(settings=settings),
        snapshot_=granted,
    )
    second = _run(
        executor,
        SENSITIVE_TOOL_ID,
        {"content": "在吗"},
        _context(settings=settings),
        snapshot_=granted,
    )

    assert first.status == second.status == "succeeded"
    assert first.permission["reason"] == "grant_matched"
    assert len(capability.calls) == 2


def test_s3_expired_grant_returns_to_confirmation(monkeypatch):
    """④ 过期：grant 过期不匹配 → 回到首次确认（不静默放行）。"""
    support.apply_flag_env(monkeypatch, PERMISSION_ON)
    settings = get_settings()
    capability = StubCapability(name="notification", action="send", required=["content"])
    executor = _executor(builtin_registry(), capability, settings)
    now = support._now()

    execution = _run(
        executor,
        SENSITIVE_TOOL_ID,
        {"content": "在吗"},
        _context(now=now, settings=settings),
        snapshot_=snapshot(
            grants=[
                {
                    "tool_id": SENSITIVE_TOOL_ID,
                    "scope": ["self"],
                    "expires_at": now - timedelta(hours=1),
                }
            ],
            settings=settings,
            now=now,
        ),
    )

    assert execution.status == "pending_confirmation"
    assert capability.calls == []


def test_s3_denied_request_marks_cancelled_and_never_grants(
    db_session_factory, monkeypatch
):
    """⑤ 否定：拒绝请求置终态，且不留长期授权。"""
    support.apply_flag_env(monkeypatch, PERMISSION_ON)
    settings = get_settings()
    service = _confirmation_service(settings)
    now = datetime.now()
    request = service.request(
        invocation(SENSITIVE_TOOL_ID, {"content": "明天开会"}),
        _confirm_decision(),
        _context(now=now, settings=settings),
    )

    outcome = service.resolve(request.request_id, approved=False)

    assert outcome.status == "denied"
    assert service.get(request.request_id).is_pending() is False
    assert service.grant_records(USER, now) == []


# --- S4 自治调用（三账对齐，1 例） ----------------------------------------------


def test_s4_autonomy_tick_three_ledgers_aligned(
    db_session_factory, override_settings, monkeypatch
):
    """自治 tick → 工具面收窄 → 意图 → 执行 → 世界写入；三账对齐。"""
    from app.application import (
        action_engine,
        autonomy_engine,
        life_loop,
        outbox_consumer,
        world_engine,
    )
    from app.models.autonomy import PROACTIVE_INTENTION_MAP
    from app.character.asuna.action import PROACTIVE_ACTION_MAP
    from app.repositories import (
        action_repository,
        decision_repository,
        loop_run_repository,
        outbox_repository,
        world_repository,
    )
    from app.services import trigger_evaluator
    from tests.v24.tool006_support import NOW, await_until, seed_tick_fixture

    override_settings(
        ACTION_OUTBOX_ENABLED="true",
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        AUTONOMY_ACTION_ENABLED="true",
        OBSERVABILITY_PERSIST_ENABLED="true")
    support.apply_flag_env(monkeypatch, {"TOOL_SYSTEM_ENABLED": True})
    seed_tick_fixture()
    world_engine.ensure_world("u-tool006")
    trigger_evaluator.register_followup(
        "u-tool006", NOW - timedelta(minutes=1), "下午面试"
    )

    stats = asyncio.run(life_loop.run_life_loop_tick(now=NOW))

    assert stats["user_cycles"] == 1 and stats["aborted"] == 0
    records = [
        record
        for record in action_repository.list_records("u-tool006", limit=50)
        if record.source == "autonomy"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.status == "succeeded"
    assert record.steps[0]["tool_id"] == "builtin.reminder.create"
    assert record.steps[0]["status"] == "succeeded"

    rows = outbox_repository.list_recent(limit=50)
    assert any(row.idempotency_key == record.id for row in rows)
    outbox_consumer.consume_pending(now=NOW)

    world = world_repository.get_world("u-tool006")
    events = [
        event
        for event in world_repository.list_events(world.world_id, limit=100)
        if event.type == "reminder"
    ]
    assert events and events[0].payload["outbox_action_id"] == record.id

    runs = loop_run_repository.list_recent(user_id="u-tool006", run_kind="autonomous_tick")
    assert runs and runs[0].kind == "autonomy" and runs[0].status == "done"
    assert asyncio.run(
        await_until(
            lambda: bool(
                decision_repository.search(
                    user_id="u-tool006", kind="proactive_autonomy"
                )
            )
        )
    )
    decision = next(
        row
        for row in decision_repository.search(
            user_id="u-tool006", kind="proactive_autonomy"
        )
        if row.decision == "act"
    )
    intention = PROACTIVE_INTENTION_MAP[
        decision.input_snapshot["selected_goal_type"]
    ]
    assert PROACTIVE_ACTION_MAP[intention] == record.action_type
    assert (runs[0].user_id, decision.user_id, record.user_id) == (
        "u-tool006",
        "u-tool006",
        "u-tool006",
    )
    assert record.steps[0]["tool_id"] in decision.input_snapshot["tool_facts"]["available"]
    assert action_engine is not None and autonomy_engine is not None


# --- S5 世界契约（2 例） --------------------------------------------------------


def test_s5_tool_writes_world_only_through_outbox(
    db_session_factory, override_settings, monkeypatch
):
    """工具写世界先落 outbox，消费后才出现世界事件。"""
    override_settings(
        ACTION_ENABLED="true",
        WORLD_ENABLED="true",
        ACTION_OUTBOX_ENABLED="true")
    support.apply_flag_env(monkeypatch, MASTER_ON)
    from app.application import action_engine, outbox_consumer, world_engine
    from app.repositories import outbox_repository, world_repository

    world = world_engine.ensure_world(USER)
    before = len(world_repository.list_events(world.world_id, limit=100))
    intent = support.action_intent(
        "create_reminder",
        {"content": "明天开会", "due_at": (support._now() + timedelta(minutes=30)).isoformat()},
    )

    record = asyncio.run(
        action_engine.run_action_planning(USER, intent, session_id=SESSION)
    )

    assert record is not None and record.status == "succeeded"
    assert len(world_repository.list_events(world.world_id, limit=100)) == before
    assert any(
        row.idempotency_key == record.id for row in outbox_repository.list_recent(limit=50)
    )

    outbox_consumer.consume_pending(now=support._now())

    assert len(world_repository.list_events(world.world_id, limit=100)) == before + 1


def test_s5_direct_world_write_in_tool_body_is_statically_blocked():
    """直写世界被静态拦截：注入违规样本必被捕获（扫描非空转）。"""
    from tests.v24.test_tool_world_guard import scan_source

    sample = (
        "from app.repositories import world_repository\n"
        "def tidy(user_id):\n"
        "    return world_repository.create_event(user_id, 'x')\n"
    )
    violations = scan_source(sample, filename="negative_sample.py")

    assert violations
    assert {item.kind for item in violations}


# --- S6 记忆分层（4 例） --------------------------------------------------------


def _deliver_record(tool_id: str, params: dict, *, status: str = "succeeded"):
    from app.models.action import ActionRecord, make_dedupe_key

    return ActionRecord(
        id=f"act-tool012-{tool_id}-{status}",
        user_id=USER,
        character_id="asuna",
        session_id=SESSION,
        action_type="create_reminder",
        status=status,
        params=params,
        dedupe_key=make_dedupe_key("create_reminder", params),
        steps=[{"index": 0, "tool_id": tool_id, "status": status}],
    )


def test_s6_read_only_tool_deposits_nothing(
    db_session_factory, override_settings, monkeypatch
):
    """读类工具零沉淀：`world.env.query` 不产生记忆行。"""
    override_settings(ACTION_MEMORY_POLICY_ENABLED="true")
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_MEMORY_ENABLED": True}
    )
    from app.services.action import memory_bridge
    from tests.v24.tool008_support import memory_count

    delivered = memory_bridge.deliver(
        _deliver_record("world.env.query", {"dimension": "weather"}), USER
    )

    assert delivered is None
    assert memory_count(USER) == 0


def test_s6_important_result_deposits_candidate(
    db_session_factory, override_settings, monkeypatch
):
    """重要结果沉淀：`builtin.reminder.cancel` 成功 → memories 落 1 行。"""
    override_settings(ACTION_MEMORY_POLICY_ENABLED="true", memory_importance_threshold=0.5)
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_MEMORY_ENABLED": True}
    )
    from app.services.action import memory_bridge
    from tests.v24.tool008_support import memory_contents, memory_count

    delivered = memory_bridge.deliver(
        _deliver_record("builtin.reminder.cancel", {"target": "开会"}), USER
    )

    assert delivered is not None
    assert memory_count(USER) == 1
    assert memory_contents(USER)[0] == "用户不想再被提醒：开会"


def test_s6_untrusted_source_rejected_by_policy(
    db_session_factory, override_settings, monkeypatch
):
    """R1 拒收：来源 ai_inferred 的候选（外发类工具）不入库。"""
    override_settings(ACTION_MEMORY_POLICY_ENABLED="true")
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_MEMORY_ENABLED": True}
    )
    from app.services.action import memory_bridge
    from tests.v24.tool008_support import memory_count

    delivered = memory_bridge.deliver(
        _deliver_record("builtin.notification.send", {"content": "在吗"}), USER
    )

    assert delivered is None
    assert memory_count(USER) == 0


def test_s6_idempotent_redelivery_is_skipped(
    db_session_factory, override_settings, monkeypatch
):
    """幂等：已登记 memory 效果的行动不重复投递。"""
    override_settings(ACTION_MEMORY_POLICY_ENABLED="true")
    support.apply_flag_env(
        monkeypatch, {**MASTER_ON, "TOOL_MEMORY_ENABLED": True}
    )
    from app.services.action import memory_bridge
    from tests.v24.tool008_support import memory_count

    record = _deliver_record("builtin.reminder.cancel", {"target": "开会"})
    record.result = {
        "status": "succeeded",
        "effects": [{"kind": "memory", "ref": "mem-already"}],
    }

    assert memory_bridge.deliver(record, USER) is None
    assert memory_count(USER) == 0


# --- S7 反思效能（2 例） --------------------------------------------------------


def test_s7_tool_failure_evidence_triggers_at_threshold(
    db_session_factory, override_settings, monkeypatch
):
    """失败证据达阈值才进窗：同 tool_id 同 failure_kind 连续计数触发。"""
    override_settings()
    support.apply_flag_env(
        monkeypatch,
        {**MASTER_ON, "TOOL_REFLECTION_ENABLED": True},
    )
    from datetime import datetime as _datetime

    from app.services.reflection import evidence as reflection_evidence, triggers
    from tests.v24.tool009_support import fake_tool_package, tool_evidence_window

    monkeypatch.setattr(
        reflection_evidence,
        "aggregate_tool_evidence",
        lambda user_id, *, now=None, trace=None: fake_tool_package(
            [tool_evidence_window()]
        ),
    )
    triggers.reset_trigger_state()
    now = _datetime(2026, 9, 14, 12, 0, 0)
    threshold = get_settings().reflection_event_threshold
    tool_id = "builtin.notification.send"

    outcomes = [
        triggers.observe_tool_evidence(
            USER, tool_id=tool_id, failure_kind="transient", now=now
        )
        for _ in range(threshold)
    ]

    assert outcomes == [False] * (threshold - 1) + [True]


def test_s7_tool_insight_does_not_trip_tool_breaker(monkeypatch):
    """隔离断言：反思证据不自动改工具状态（注册表快照不变）。"""
    from tests.v24.tool009_support import registry_snapshot

    support.apply_flag_env(monkeypatch, MASTER_ON)
    registry = builtin_registry()
    before = registry_snapshot(registry)

    from app.services.reflection import triggers

    triggers.observe_tool_evidence(
        USER, tool_id="builtin.notification.send", failure_kind="transient"
    )

    assert registry_snapshot(registry) == before
    assert registry.effective_status("builtin.notification.send") == "enabled"


# --- S8 通道工具（3 例） --------------------------------------------------------


def test_s8_channel_send_requires_confirmation(monkeypatch):
    """发送需确认：无授权时通道工具停在 pending_confirmation，适配器零调用。"""
    support.apply_flag_env(monkeypatch, {**CHANNEL_ON, "TOOL_PERMISSION_ENABLED": True})
    settings = get_settings()
    from tests.v24.tool010_support import RecordingAdapter, reset_runtime_state
    from app.services.tool import channel_tools

    reset_runtime_state()
    adapter = RecordingAdapter()
    channel_tools.register_channel_adapter("feishu", adapter)
    capability = StubCapability(name="channel_feishu", action="send", required=["content"])
    executor = _executor(builtin_registry(), capability, settings)

    execution = _run(
        executor,
        "channel.feishu.send",
        {"content": "在吗", "recipient": "ou_asuna"},
        _context(settings=settings),
        snapshot_=snapshot(grants=[], settings=settings),
    )

    assert execution.status == "pending_confirmation"
    assert execution.permission["reason"] == "first_time_confirmation"
    assert adapter.messages == []


def test_s8_split_text_invariant_holds():
    """切分不变式：`"".join(parts) == text`（沿用既有 outbound 实现）。"""
    from app.channels.feishu.outbound import split_text

    text = "亚丝娜" * 500
    parts = split_text(text, 200)

    assert "".join(parts) == text
    assert all(len(part) <= 200 for part in parts)


def test_s8_channel_error_maps_to_failure_kind():
    """错误映射：通道错误码 → 失败类型（可重试性判定同表）。"""
    from app.channels.base import ChannelErrorKind
    from app.services.tool.channel_tools import (
        CHANNEL_ERROR_FAILURE_KINDS,
        failure_kind_for,
        is_retryable,
    )

    assert set(CHANNEL_ERROR_FAILURE_KINDS) == {kind.value for kind in ChannelErrorKind}
    assert failure_kind_for(ChannelErrorKind.AUTH) == "permanent"
    assert failure_kind_for(ChannelErrorKind.RATE_LIMITED) == "transient"
    assert is_retryable("transient") is True
    assert is_retryable("permanent") is False


# --- S9 扩展性（3 例） ----------------------------------------------------------


def test_s9_new_builtin_declaration_enters_pipeline(monkeypatch):
    """内置四步：只加声明即可被工具面 / 校验 / 执行器接住。"""
    support.apply_flag_env(monkeypatch, MASTER_ON)
    settings = get_settings()
    from app.services.tool.registry import ToolRegistry
    from app.services.tool.context import ToolContext
    from app.services.tool.surface import ToolSurfaceResolver
    from app.services.tool.validator import ParamValidator

    registry = builtin_registry()
    definition = ToolDefinition(
        id="builtin.tool012.newtool",
        name="新增工具",
        description="S9 新增内置工具探针",
        when_to_use="验收探针使用",
        namespace="builtin",
        capability="reminder",
        action="create",
        input_schema=ToolSchema(
            parameters=[
                ToolParameter(name="content", type="string", required=True),
                ToolParameter(name="due_at", type="datetime", required=True),
            ]
        ),
        permission=PermissionProfile(level="normal", scope=("world",), confirm="never"),
        side_effects=("write_world",),
        tags=("reminder", "world"),
        priority=15,
    )
    registry.register(definition)
    assert isinstance(registry, ToolRegistry)

    surface = ToolSurfaceResolver(registry, settings).resolve(
        "foreground_chat", ToolContext(user_id=USER, settings=settings)
    )
    assert definition.id in surface.tool_ids
    assert ParamValidator().validate(
        definition, {"content": "在吗", "due_at": "2026-12-31T09:00:00"}
    ).passed


def test_s9_external_api_tool_costs_one_manifest(tmp_path):
    """外部一 YAML：单清单文件产出 1 个 `ext.api.*` 工具。"""
    from tests.v24.tool011_support import (
        WEATHER_ENV,
        WEATHER_HOST,
        load_manifests,
        weather_manifest,
    )

    settings = support.tool_settings(
        tool_external_api_enabled=True, tool_ext_allowed_hosts=WEATHER_HOST
    )
    registry, index, report = load_manifests(
        tmp_path,
        manifests={"weather.yaml": weather_manifest()},
        settings=settings,
        environ={WEATHER_ENV: "test-value"},
    )

    assert report.loaded == ["ext.api.weather.current"]
    assert index.tool_ids() == ("ext.api.weather.current",)
    assert registry.get("ext.api.weather.current") is not None


def test_s9_user_dsl_rejects_arbitrary_code():
    """DSL 负例：用户自定义工具不得携带任意代码 / 网络 / 文件访问。"""
    from app.services.tool.dsl import validate_steps

    negative = [
        {
            "capability": "subprocess",
            "action": "run",
            "params_map": {"cmd": "{params.content}"},
        }
    ]
    errors = validate_steps(negative)

    assert errors

    shell_steps = [
        {
            "capability": "reminder",
            "action": "create",
            "params_map": {"content": "{params.content}", "due_at": "https://evil.example.com"},
        }
    ]
    assert validate_steps(shell_steps)


# --- S10 多 tick 韧性（3 例） ---------------------------------------------------


def test_s10_tool_failure_records_failure_kind(monkeypatch):
    """工具失败归一：failure_kind 落执行结果，健康度记一次失败。

    P0-1：`builtin.notification.send` 属特权档，需权限子闸 + 授权快照才走到能力。
    """
    support.apply_flag_env(
        monkeypatch,
        _env_reaching_capability(
            SENSITIVE_TOOL_ID, {**MASTER_ON, "TOOL_OBSERVATION_ENABLED": True}
        ),
    )
    settings = get_settings()
    from app.models.action import CapabilityResult

    capability = StubCapability(
        name="notification",
        action="send",
        required=["content"],
        behavior=lambda params, ctx: CapabilityResult(
            status="failed", payload={"failure_kind": "transient"}, error="上游抖动"
        ),
    )
    executor = _executor(builtin_registry(), capability, settings)

    execution = _run(
        executor,
        SENSITIVE_TOOL_ID,
        {"content": "在吗"},
        _context(settings=settings),
        snapshot_=_grant_snapshot_for(SENSITIVE_TOOL_ID, settings),
    )

    assert execution.status == "failed"
    assert execution.result["failure_kind"] == "transient"
    health = executor.registry.health(SENSITIVE_TOOL_ID)[SENSITIVE_TOOL_ID]
    assert health.consecutive_failures == 1


def test_s10_breaker_trips_and_half_opens(monkeypatch):
    """熔断半开：达阈值熔断 → 冷却后半开（可用）→ 再失败立即重熔。"""
    from app.services.tool.health import ToolHealthTracker

    support.apply_flag_env(monkeypatch, MASTER_ON)
    settings = get_settings()
    registry = builtin_registry()
    clock = {"now": datetime(2026, 9, 14, 12, 0, 0)}
    tracker = ToolHealthTracker(registry, settings, clock=lambda: clock["now"])

    for _ in range(settings.tool_breaker_threshold):
        tracker.record_outcome(SENSITIVE_TOOL_ID, ok=False, failure_kind="transient")

    assert tracker.is_tripped(SENSITIVE_TOOL_ID, clock["now"]) is True
    assert registry.effective_status(SENSITIVE_TOOL_ID) == "disabled"

    clock["now"] = clock["now"] + timedelta(
        seconds=settings.tool_breaker_cooldown_seconds + 1
    )
    assert tracker.is_tripped(SENSITIVE_TOOL_ID, clock["now"]) is False
    assert registry.effective_status(SENSITIVE_TOOL_ID) == "enabled"

    tracker.record_outcome(SENSITIVE_TOOL_ID, ok=False, failure_kind="transient")
    assert tracker.is_tripped(SENSITIVE_TOOL_ID, clock["now"]) is True


def test_s10_long_offline_then_autonomy_catch_up():
    """长离线后自治：>7 天折叠为单条 long_gap，短间隔走 daily。"""
    from app.services.world import catch_up

    today = support._now().date()
    long_plan = catch_up.compute_catch_up_plan(
        last_covered=today - timedelta(days=15),
        today=today,
        max_days=get_settings().catch_up_max_days,
    )
    short_plan = catch_up.compute_catch_up_plan(
        last_covered=today - timedelta(days=3),
        today=today,
        max_days=get_settings().catch_up_max_days,
    )

    assert long_plan.mode == "long_gap"
    assert long_plan.days_behind == 15
    assert short_plan.mode == "daily"
    assert len(short_plan.missing_days) == 2
