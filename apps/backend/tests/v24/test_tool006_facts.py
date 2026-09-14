"""TOOL-006 §5 Step2 / §6.1 / §6.3：工具事实段有界、降级与策略输入面（E2/E3/E4/E8/E11）。"""

import json
import uuid
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.models.action import ActionRecord
from app.models.autonomy import AutonomyVerdict, TriggerSignal
from app.repositories import action_repository
from app.services import autonomy_policy
from app.services.tool.health import ToolHealthTracker
from app.services.tool.registry import ToolRegistry
from tests.v24.tool006_support import (
    NOW,
    USER,
    autonomy_settings,
    builtin_registry,
    registry_with,
    tool_definition,
)

SIGNAL = TriggerSignal(
    type="conversation_inactivity", user_id=USER, detected_at=NOW, dedupe_key="tool006"
)

TRIGGER_BASE_REASON = "触发 conversation_inactivity，存在 user_care 目标"


@pytest.fixture
def registry_on(monkeypatch, v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True)
    registry = builtin_registry()
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry)
    return registry


@pytest.fixture
def stub_registry_env(monkeypatch, v24_tool_env):
    """总闸 on + 自建注册表（不掺内置声明，保证工具事实的有界性断言可复现）。"""
    v24_tool_env(v24_tool_system_enabled=True)

    def _install(*definitions):
        registry = registry_with(*definitions)
        monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry)
        return registry

    return _install


def _act_snapshot(**overrides) -> autonomy_policy.PolicySnapshot:
    values = {
        "last_proactive_at": None,
        "attempt_count": 0,
        "intimacy": 0.6,
        "selected_goal_type": "user_care",
        "goal_degraded": False,
        "extra_flags": {"goal_id": "goal-tool006"},
    }
    values.update(overrides)
    return autonomy_policy.PolicySnapshot(**values)


def _seed_tool_step(
    user_id: str,
    tool_id: str,
    failure_kind: str | None,
    *,
    status: str = "failed",
    created_at: datetime | None = None,
) -> ActionRecord:
    record = ActionRecord(
        id=uuid.uuid4().hex,
        user_id=user_id,
        session_id="s1",
        source="autonomy",
        action_type="create_reminder",
        dedupe_key=f"autonomy:{tool_id}",
        status="failed",
        steps=[
            {
                "index": 0,
                "capability": "reminder",
                "action": "create",
                "params": {},
                "status": status,
                "tool_id": tool_id,
                "result": {"failure_kind": failure_kind, "status": "failed"},
            }
        ],
        created_at=created_at or NOW,
        updated_at=created_at or NOW,
    )
    action_repository.save_record(record)
    return record


# --- §4.1 有界性与形状 ---------------------------------------------------------


def test_tool_facts_shape_and_available_priority_order(stub_registry_env):
    stub_registry_env(
        *(
            tool_definition(f"builtin.test_{index}.create", priority=10 + index)
            for index in range(7)
        )
    )
    facts = autonomy_engine.collect_tool_facts(USER)
    assert set(facts) == {"available", "recent_failures", "breaker_open"}
    assert len(facts["available"]) == autonomy_engine.TOOL_FACTS_AVAILABLE_LIMIT == 5
    assert facts["available"] == [
        "builtin.test_0.create",
        "builtin.test_1.create",
        "builtin.test_2.create",
        "builtin.test_3.create",
        "builtin.test_4.create",
    ]
    assert facts["recent_failures"] == []
    assert facts["breaker_open"] == []


def test_recent_failures_bounded_and_most_recent_first(registry_on, db_session_factory):
    for index in range(4):
        _seed_tool_step(
            USER,
            f"builtin.test_{index}.create",
            "transient",
            created_at=NOW + timedelta(minutes=index),
        )
    facts = autonomy_engine.collect_tool_facts(USER)
    assert (
        len(facts["recent_failures"])
        == autonomy_engine.TOOL_FACTS_RECENT_FAILURE_LIMIT
        == 3
    )
    assert facts["recent_failures"] == [
        {"tool_id": "builtin.test_3.create", "failure_kind": "transient"},
        {"tool_id": "builtin.test_2.create", "failure_kind": "transient"},
        {"tool_id": "builtin.test_1.create", "failure_kind": "transient"},
    ]


def test_recent_failures_dedupe_per_tool(registry_on, db_session_factory):
    _seed_tool_step(USER, "builtin.test_a.create", "transient", created_at=NOW)
    _seed_tool_step(
        USER, "builtin.test_a.create", "permanent", created_at=NOW + timedelta(minutes=1)
    )
    facts = autonomy_engine.collect_tool_facts(USER)
    assert facts["recent_failures"] == [
        {"tool_id": "builtin.test_a.create", "failure_kind": "permanent"}
    ]


def test_succeeded_steps_are_not_failures(registry_on, db_session_factory):
    _seed_tool_step(USER, "builtin.test_ok.create", None, status="succeeded")
    assert autonomy_engine.collect_tool_facts(USER)["recent_failures"] == []


def test_breaker_open_bounded_excludes_available(stub_registry_env):
    """E2：熔断工具进 breaker_open 且不在 available；全熔断时裁决仍不失败。"""
    tool_ids = [f"builtin.test_{index}.create" for index in range(4)]
    registry = stub_registry_env(
        *(tool_definition(tool_id, priority=10) for tool_id in tool_ids)
    )
    for tool_id in tool_ids:
        registry.mark_tripped(tool_id)
    facts = autonomy_engine.collect_tool_facts(USER)
    assert facts["available"] == []
    assert len(facts["breaker_open"]) == autonomy_engine.TOOL_FACTS_BREAKER_LIMIT == 3
    assert facts["breaker_open"] == sorted(tool_ids)[:3]
    assert not set(facts["breaker_open"]) & set(facts["available"])
    verdict = autonomy_policy.evaluate(SIGNAL, _act_snapshot(tool_facts=facts), None, NOW)
    assert verdict.decision == "act"


def test_tool_facts_bounded_by_existing_char_budget(stub_registry_env, monkeypatch):
    """E3：超字符预算经既有 bound_extra 裁剪，仍为合法 dict（不截断成非法 JSON）。"""
    stub_registry_env(
        *(
            tool_definition(f"builtin.long_{index}.create", priority=index)
            for index in range(6)
        )
    )
    monkeypatch.setattr(
        autonomy_engine,
        "get_settings",
        lambda: autonomy_settings(observability_step_extra_max_chars=40),
    )
    facts = autonomy_engine.collect_tool_facts(USER)
    assert isinstance(facts, dict) and facts
    assert "truncated_summary" in facts
    assert json.loads(json.dumps(facts)) == facts


def test_tool_facts_empty_when_master_flag_off(v24_tool_env, db_session_factory):
    v24_tool_env(v24_tool_system_enabled=False)
    _seed_tool_step(USER, "builtin.reminder.create", "timeout")
    assert autonomy_engine.collect_tool_facts(USER) == {}


def test_tool_facts_degrade_to_empty_on_surface_failure(
    registry_on, monkeypatch, db_session_factory
):
    """E4：工具面计算抛异常 → 捕获返回 {}，自治 tick 继续（不抛出）。"""

    def boom(*args, **kwargs):
        raise RuntimeError("surface down")

    monkeypatch.setattr(autonomy_engine, "resolve_autonomy_surface", boom)
    assert autonomy_engine.collect_tool_facts(USER) == {}
    assert "tool_facts" not in autonomy_engine._collect_action_facts(USER)
    trace = type("Trace", (), {"record": lambda self, *a, **k: None})()
    assert autonomy_engine._resolve_tick_capabilities(USER, NOW, trace, {}) is None


def test_empty_registry_yields_empty_facts(monkeypatch, v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True)
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: ToolRegistry())
    assert autonomy_engine.collect_tool_facts(USER) == {
        "available": [],
        "recent_failures": [],
        "breaker_open": [],
    }


def test_registry_absent_degrades_to_empty(monkeypatch, v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True)
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: None)
    assert autonomy_engine.collect_tool_facts(USER) == {}
    assert autonomy_engine._autonomy_binding("create_reminder", NOW) is None


# --- E11 超时失败进工具事实 ----------------------------------------------------


def test_timeout_failure_enters_recent_failures_and_health(registry_on, db_session_factory):
    """E11：`failure_kind=timeout` 进 recent_failures；健康度计一次失败。"""
    tracker = ToolHealthTracker(registry_on, autonomy_settings())
    tracker.record_outcome("builtin.reminder.create", ok=False, failure_kind="timeout")
    _seed_tool_step(USER, "builtin.reminder.create", "timeout")
    facts = autonomy_engine.collect_tool_facts(USER)
    assert facts["recent_failures"] == [
        {"tool_id": "builtin.reminder.create", "failure_kind": "timeout"}
    ]
    health = registry_on.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.consecutive_failures == 1
    assert health.last_failure_at is not None


# --- §4.3 PolicySnapshot 输入面（不新增裁决步骤） ------------------------------


def test_policy_snapshot_tool_facts_default_is_empty_dict():
    assert autonomy_policy.PolicySnapshot().tool_facts == {}


def test_empty_tool_facts_keeps_v23_verdict_bytes():
    """E8：缺省空 dict → 八步裁决与 V2.3.0 逐字节一致。"""
    baseline = autonomy_policy.evaluate(SIGNAL, _act_snapshot(), None, NOW)
    with_empty = autonomy_policy.evaluate(SIGNAL, _act_snapshot(tool_facts={}), None, NOW)
    assert baseline.model_dump() == with_empty.model_dump()
    assert baseline.reason == TRIGGER_BASE_REASON
    verdict = autonomy_policy._apply_tool_adjustments(
        baseline, autonomy_policy.PolicySnapshot()
    )
    assert verdict is baseline


def test_tool_facts_append_reason_without_breaking_gates():
    snapshot = _act_snapshot(
        tool_facts={
            "available": ["builtin.reminder.create"],
            "recent_failures": [{"tool_id": "world.env.query", "failure_kind": "timeout"}],
            "breaker_open": ["builtin.reminder.create"],
        }
    )
    verdict = autonomy_policy.evaluate(SIGNAL, snapshot, None, NOW)
    assert verdict.decision == "act"
    assert verdict.intention == "check_in"
    assert "有工具处于熔断，暂避该途径" in verdict.reason
    assert len(verdict.reason) <= 60


def test_empty_available_tool_facts_do_not_block_act():
    snapshot = _act_snapshot(
        tool_facts={"available": [], "recent_failures": [], "breaker_open": []}
    )
    verdict = autonomy_policy.evaluate(SIGNAL, snapshot, None, NOW)
    assert verdict.decision == "act"
    assert verdict.reason == TRIGGER_BASE_REASON


def test_gates_still_win_over_tool_facts():
    """工具事实是输入面不是闸门：既有闸门（如静音时段）仍先短路。"""
    quiet = NOW.replace(hour=4, minute=0)
    snapshot = _act_snapshot(tool_facts={"breaker_open": ["builtin.reminder.create"]})
    verdict = autonomy_policy.evaluate(SIGNAL, snapshot, None, quiet)
    assert verdict.decision == "ignore"
    assert verdict.reason == "静音时段"


# --- 工具事实与 registry 内存态同源 ---------------------------------------------


def test_health_snapshot_is_read_only_copy(registry_on):
    registry_on.mark_tripped("builtin.reminder.create")
    facts = autonomy_engine.collect_tool_facts(USER)
    assert facts["breaker_open"] == ["builtin.reminder.create"]
    copied = registry_on.health("builtin.reminder.create")["builtin.reminder.create"]
    copied.tripped = False
    assert (
        registry_on.health("builtin.reminder.create")["builtin.reminder.create"].tripped
        is True
    )


def test_binding_absent_for_tool_outside_surface(monkeypatch, v24_tool_env):
    """工具不在自治工具面内 → 无绑定（回退 V9 固定模板）。"""
    v24_tool_env(v24_tool_system_enabled=True)
    channel_only = registry_with(
        tool_definition("channel.feishu.send", namespace="channel")
    )
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: channel_only)
    assert autonomy_engine._autonomy_binding("send_notification", NOW) is None


# --- Flag off 行为快照对照 ------------------------------------------------------


def test_collect_action_facts_identical_to_collect_facts_when_flag_off(
    monkeypatch, override_settings, v24_tool_env
):
    """Flag 全 off：`_collect_action_facts` 输出与既有 `collect_facts` 逐字节一致。"""
    override_settings(action_enabled="true")
    v24_tool_env(v24_tool_system_enabled=False)
    monkeypatch.setattr(
        autonomy_engine, "collect_facts", lambda user_id: {"active_plans": 1}
    )
    assert autonomy_engine._collect_action_facts(USER) == {"active_plans": 1}


def test_collect_action_facts_unchanged_when_tool_facts_empty(
    monkeypatch, override_settings, v24_tool_env
):
    override_settings(action_enabled="true")
    v24_tool_env(v24_tool_system_enabled=True)
    monkeypatch.setattr(
        autonomy_engine, "collect_facts", lambda user_id: {"active_plans": 2}
    )
    monkeypatch.setattr(autonomy_engine, "collect_tool_facts", lambda user_id, ctx=None: {})
    assert autonomy_engine._collect_action_facts(USER) == {"active_plans": 2}


def test_decision_record_carries_tool_facts_only_when_present():
    verdict = AutonomyVerdict(decision="act", reason="触发", trigger=SIGNAL)
    without = autonomy_engine._decision_record(
        verdict=verdict,
        signal=SIGNAL,
        snapshot=_act_snapshot(),
        user_id=USER,
        session_id="s1",
    )
    assert "tool_facts" not in without.input_snapshot
    with_facts = autonomy_engine._decision_record(
        verdict=verdict,
        signal=SIGNAL,
        snapshot=_act_snapshot(
            tool_facts={"available": ["builtin.reminder.create"], "recent_failures": [], "breaker_open": []}
        ),
        user_id=USER,
        session_id="s1",
    )
    assert with_facts.input_snapshot["tool_facts"]["available"] == [
        "builtin.reminder.create"
    ]
