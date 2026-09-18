"""TOOL-006 §5 Step1 / §6.1 / §6.3：自治工具面接入（Profile 收窄、断层 B7 关闭与 E1/E9/E10/E12）。"""

import pytest

from app.application import autonomy_engine
from app.application.agent_runtime import profiles
from app.services import decision_pipeline
from app.services.tool import registry as tool_registry_module
from tests.v24.tool006_support import (
    LATE_NIGHT,
    NOW,
    USER,
    RecordingTrace,
    autonomy_context,
    builtin_registry,
    registry_with,
    surface_of,
    tool_definition,
)

EXPECTED_AUTONOMOUS_STAGES = (
    "perception",
    "state_update",
    "state_snapshot",
    "goal_check",
    "goal_stack",
    "goal_supply",
    "goal_advance",
    "memory_retrieval",
    "reflection_check",
    "decision",
    "world_experience",
)


@pytest.fixture
def registry_on(monkeypatch, v24_tool_env):
    """总闸 on：注入内置声明注册表（惰性单例按 env 语境重建）。"""
    v24_tool_env()
    registry = builtin_registry()
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry)
    return registry


# --- §4.2 自治工具面：总闸门控 -------------------------------------------------


def test_surface_narrowed_by_run_profile_on_tick(registry_on):
    registry_on.register(
        tool_definition("channel.feishu.push", namespace="channel", priority=200)
    )
    surface = autonomy_engine.resolve_autonomy_surface(USER, NOW)
    assert surface.run_kind == "autonomous_tick"
    assert "channel.feishu.send" not in surface.tool_ids
    assert "channel.feishu.push" not in surface.tool_ids
    assert all(not tool_id.startswith("channel.") for tool_id in surface.tool_ids)
    assert "builtin.reminder.create" in surface.tool_ids
    assert "world.env.query" in surface.tool_ids
    channel_exclusions = [
        item for item in surface.excluded if item["tool_id"].startswith("channel.")
    ]
    assert {item["reason"] for item in channel_exclusions} == {
        "run_profile:autonomous_tick 无用户在线，不投放通道类工具",
        "tool_status:disabled",
    }


def test_surface_order_follows_priority_then_id(registry_on):
    surface = autonomy_engine.resolve_autonomy_surface(USER, NOW)
    priorities = [registry_on.get(tool_id).priority for tool_id in surface.tool_ids]
    assert priorities == sorted(priorities)
    assert surface.tool_ids[:3] == (
        "builtin.reminder.create",
        "builtin.reminder.cancel",
        "builtin.memory.save",
    )


def test_tick_capabilities_pass_surface_and_record_trace(registry_on):
    trace = RecordingTrace()
    capabilities = autonomy_engine._resolve_tick_capabilities(USER, NOW, trace, {})
    surface = autonomy_engine.resolve_autonomy_surface(USER, NOW)
    assert capabilities == list(surface.tool_ids)
    assert capabilities and all(
        not tool_id.startswith("channel.") for tool_id in capabilities
    )
    assert RecordingTrace.names(trace) == [autonomy_engine.AUTONOMY_TOOL_SURFACE_STEP]
    extra = trace.calls[0]
    assert extra["run_kind"] == "autonomous_tick"
    assert extra["tool_ids"] == list(surface.tool_ids)
    assert extra["surface_hash"] == surface.surface_hash


def test_trace_step_carries_tool_facts(registry_on):
    facts = {
        "available": ["builtin.reminder.create"],
        "recent_failures": [],
        "breaker_open": [],
    }
    trace = RecordingTrace()
    autonomy_engine._resolve_tick_capabilities(USER, NOW, trace, facts)
    assert trace.calls[0]["tool_facts"] == facts
    # TOOL-010｜`builtin.search.query` 走路线 B，默认被可用性降级维度裁掉（E1）。
    assert [item["tool_id"] for item in trace.calls[0]["excluded"]] == [
        "builtin.search.query",
        "channel.feishu.send",
    ]


def test_capabilities_distinguish_empty_surface_from_none(monkeypatch, v24_tool_env):
    """E1：总闸 on 但注册表为空 → capabilities=[]（非 None），决策仍正常（silence 兜底）。"""
    v24_tool_env(TOOL_SYSTEM_ENABLED=True)
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry_with())
    trace = RecordingTrace()
    assert autonomy_engine._resolve_tick_capabilities(USER, NOW, trace, {}) == []
    assert RecordingTrace.names(trace) == [autonomy_engine.AUTONOMY_TOOL_SURFACE_STEP]
    candidates = decision_pipeline.collect_candidates(capabilities=[])
    assert [candidate.source for candidate in candidates] == ["silence"]


def test_capability_candidates_appear_in_pipeline_audit(registry_on):
    capabilities = autonomy_engine._resolve_tick_capabilities(USER, NOW, RecordingTrace(), {})
    result = decision_pipeline.run_pipeline(
        trigger_intention="check_in", capabilities=capabilities, now=NOW
    )
    capability_candidates = [
        candidate
        for candidate in result.audit["candidates"]
        if candidate["source"] == "capability"
    ]
    assert capability_candidates
    assert {candidate["tool_id"] for candidate in capability_candidates} == set(capabilities)


# --- §2.2 日时段收窄（E9）与当前时刻投影（E12） --------------------------------


def test_late_night_drops_social_tag(registry_on):
    social = tool_definition(
        "world.social.chat", namespace="world", tags=("social",), priority=5
    )
    registry = registry_with(
        social,
        tool_definition(
            "world.env.query",
            namespace="world",
            capability="environment_query",
            action="query",
            parameters=[],
        ),
    )
    day_surface = surface_of(registry, autonomy_context(now=NOW))
    night_surface = surface_of(
        registry, autonomy_context(now=LATE_NIGHT, world={"part_of_day": "late_night"})
    )
    assert "world.social.chat" in day_surface.tool_ids
    assert "world.social.chat" not in night_surface.tool_ids
    assert any(
        item["reason"].startswith("part_of_day") for item in night_surface.excluded
    )


def test_surface_projects_at_call_time_without_backfill(monkeypatch, registry_on):
    """E12：工具面按调用时刻的语境投影，不缓存、不回溯历史。"""
    social = tool_definition("world.social.chat", namespace="world", tags=("social",))
    monkeypatch.setattr(
        autonomy_engine, "get_tool_registry", lambda: registry_with(social)
    )
    day = autonomy_engine.resolve_autonomy_surface(USER, ctx=autonomy_context(now=NOW))
    night = autonomy_engine.resolve_autonomy_surface(
        USER, ctx=autonomy_context(now=LATE_NIGHT, world={"part_of_day": "late_night"})
    )
    assert day.surface_hash != night.surface_hash
    assert day.tool_ids == ("world.social.chat",)
    assert night.tool_ids == ()


def test_event_driven_profile_and_autonomous_stage_sequence_unchanged(registry_on):
    """E10：本任务不改 event_driven 只读收窄，也不改 autonomous_tick 阶段序列。"""
    registry = builtin_registry()
    event_surface = surface_of(registry, run_kind="event_driven")
    assert "world.env.query" in event_surface.tool_ids
    assert "builtin.reminder.create" not in event_surface.tool_ids
    assert "world.object.move" not in event_surface.tool_ids
    assert profiles.get_profile("autonomous_tick").stages == EXPECTED_AUTONOMOUS_STAGES


# --- Flag off 冻结面 ----------------------------------------------------------


def test_missing_world_facts_degrade_to_no_part_of_day_narrowing(registry_on):
    """TOOL-007 未装配世界事实：日时段维度降级不裁剪，不误裁社交类工具。"""
    monkeypatch_registry = registry_with(
        tool_definition("world.social.chat", namespace="world", tags=("social",))
    )
    surface = surface_of(monkeypatch_registry, autonomy_context(now=LATE_NIGHT))
    assert surface.tool_ids == ("world.social.chat",)
    assert surface.excluded == ()
