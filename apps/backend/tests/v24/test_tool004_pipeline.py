"""TOOL-004 §6.1/§6.2：决策候选接线、计划装配双路径与第 9 步内部增强。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.character.asuna.action import ACTION_CAPABILITY_MAP, ACTION_TOOL_MAP
from app.application import post_process
from app.models.action import ActionIntent
from app.models.tool import ToolSurface
from app.services import decision_pipeline
from app.services.action import planner
from app.services.tool.context import WORLD_ENABLED_KEY, ToolContext
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.world_context import apply_world_facts
from app.services.observability.collector import TurnTraceSession
from tests.v24.tool004_support import (
    NOW,
    RUN_KIND_FOREGROUND_CHAT,
    builtin_registry,
    registry_with,
    surface_context,
    tool_definition,
    tool_settings,
)

V9_STEP_KEYS = {"index", "capability", "action", "params", "status", "result"}


def intent(action_type: str = "create_reminder", **params) -> ActionIntent:
    return ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=params or {"content": "开会", "due_at": "2026-09-15T08:00:00"},
    )


# --- 目标类型解析（§4.3） --------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("builtin.reminder.create", "user_care"),
        ("builtin.reminder.cancel", "user_care"),
        ("builtin.notification.send", "user_care"),
        ("channel.feishu.send", "user_care"),
        ("builtin.memory.save", "conversation"),
        ("builtin.search.query", "conversation"),
        ("world.object.move", "scene"),
        ("world.env.query", "scene"),
        ("reminder", "user_care"),
        ("world_action", "scene"),
        ("unknown.tool.thing", ""),
    ],
)
def test_resolve_goal_type_from_tool_id(name, expected):
    assert decision_pipeline.resolve_goal_type_from_tool_id(name) == expected


def test_goal_type_hints_cover_declared_tool_map():
    for tool_ids in ACTION_TOOL_MAP.values():
        for tool_id in tool_ids:
            assert decision_pipeline.resolve_goal_type_from_tool_id(tool_id)


def test_legacy_capability_of_derives_from_action_maps():
    assert decision_pipeline.legacy_capability_of("builtin.reminder.create") == "reminder"
    assert decision_pipeline.legacy_capability_of("world.object.move") == "world_action"
    assert decision_pipeline.legacy_capability_of("channel.feishu.send") == "notification"
    assert decision_pipeline.legacy_capability_of("reminder") == "reminder"
    assert decision_pipeline.legacy_capability_of("unknown.tool.thing") is None


# --- 候选携带 tool_id ------------------------------------------------------


def test_capability_candidates_carry_tool_id_and_resolved_type():
    candidates = decision_pipeline.collect_candidates(
        capabilities=["builtin.reminder.create", "world.env.query"]
    )
    capability_candidates = [c for c in candidates if c.source == "capability"]
    assert [c.payload["tool_id"] for c in capability_candidates] == [
        "builtin.reminder.create",
        "world.env.query",
    ]
    assert [c.payload["type"] for c in capability_candidates] == ["user_care", "scene"]
    assert [c.payload["capability"] for c in capability_candidates] == [
        "reminder",
        "environment_query",
    ]


def test_legacy_capability_name_stays_supported():
    candidates = decision_pipeline.collect_candidates(capabilities=["reminder"])
    capability_candidate = next(c for c in candidates if c.source == "capability")
    assert capability_candidate.payload == {
        "tool_id": "reminder",
        "capability": "reminder",
        "type": "user_care",
    }


def test_audit_carries_tool_id_only_when_present():
    result = decision_pipeline.run_pipeline(
        capabilities=["builtin.reminder.create"], chat_response=True, run=None, now=NOW
    )
    capability_row = next(
        c for c in result.audit["candidates"] if c["source"] == "capability"
    )
    assert capability_row["tool_id"] == "builtin.reminder.create"
    assert capability_row["scores"] and capability_row["gates"]
    assert capability_row["won"] is False
    silence_row = next(c for c in result.audit["candidates"] if c["source"] == "silence")
    assert "tool_id" not in silence_row


def test_tool_candidates_enter_scoring_and_gates():
    result = decision_pipeline.run_pipeline(
        capabilities=list(ACTION_TOOL_MAP["create_reminder"]),
        chat_response=True,
        run=None,
        now=NOW,
    )
    row = next(c for c in result.audit["candidates"] if c["source"] == "capability")
    assert row["priority"] == "P3"
    assert set(row["scores"]) == {
        "goal_alignment",
        "state_fit",
        "relationship_fit",
        "timing",
        "interest",
        "cost",
    }
    assert len(row["gates"]) == 4


def test_foreground_chat_response_always_wins_with_tool_candidates():
    result = decision_pipeline.run_pipeline(
        capabilities=list(ACTION_TOOL_MAP["create_reminder"])
        + list(ACTION_TOOL_MAP["query_environment"]),
        chat_response=True,
        chat_response_intention="comfort_user",
        run=None,
        now=NOW,
    )
    assert result.winner.source == "chat_response"
    assert sum(1 for c in result.audit["candidates"] if c["won"]) == 1


def test_scoring_matches_legacy_capability_scores():
    tool_result = decision_pipeline.run_pipeline(
        capabilities=["builtin.reminder.create"], run=None, now=NOW
    )
    legacy_result = decision_pipeline.run_pipeline(
        capabilities=["reminder"], run=None, now=NOW
    )
    tool_row = next(c for c in tool_result.audit["candidates"] if c["source"] == "capability")
    legacy_row = next(
        c for c in legacy_result.audit["candidates"] if c["source"] == "capability"
    )
    assert tool_row["scores"] == legacy_row["scores"]


# --- 计划装配：off 路径逐字节一致 -------------------------------------------


def _snapshot(settings, *, world_available=True, tool_context=None):
    from app.services.action.registry import CapabilityRegistry
    from app.services.action import capabilities as capability_module

    registry = CapabilityRegistry()
    capability_module.register_builtin(registry)
    return planner.GateSnapshot(
        settings=settings,
        registry=registry,
        world_available=world_available,
        now=NOW,
        tool_context=tool_context,
    )


def test_plan_assembly_off_path_rejects_invalid_params():
    snapshot = _snapshot(tool_settings())
    assert planner.assemble_plan(intent(params={"content": "开会"}), snapshot, NOW) is None


# --- 计划装配：on 路径 ------------------------------------------------------


def test_plan_assembly_on_path_uses_tool_binding(monkeypatch):
    registry = builtin_registry()
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    snapshot = _snapshot(tool_settings())
    plan = planner.assemble_plan(intent(), snapshot, NOW, goal_id="g-2")
    assert plan is not None
    step = plan.steps[0]
    assert step.capability == "reminder" and step.action == "create"
    assert set(step.model_dump()) == V9_STEP_KEYS


def test_plan_assembly_world_facts_disabled_yields_no_binding(monkeypatch):
    registry = builtin_registry()
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    settings = tool_settings()
    facts = {
        "world": {WORLD_ENABLED_KEY: False},
        "inventory": [],
        "situations": [],
        "scene": {},
        "relationship": {},
    }
    tool_context = apply_world_facts(
        ToolContext(user_id="u-pipe", now=NOW, settings=settings), facts
    )
    snapshot = _snapshot(settings, tool_context=tool_context)
    moving = intent("move_object", object="牛奶", location="home.kitchen")
    assert planner.assemble_plan(moving, snapshot, NOW) is None


def test_plan_assembly_on_path_respects_runtime_disable(monkeypatch):
    registry = builtin_registry()
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    snapshot = _snapshot(tool_settings())
    assert planner.assemble_plan(intent(), snapshot, NOW) is not None
    assert registry.set_runtime_disabled("builtin.reminder.create") is True
    assert planner.assemble_plan(intent(), snapshot, NOW) is None


def test_plan_assembly_on_path_uses_preread_surface(monkeypatch):
    registry = builtin_registry()
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    snapshot = _snapshot(tool_settings())
    snapshot.tool_surface = ToolSurface(run_kind=RUN_KIND_FOREGROUND_CHAT, tool_ids=())
    assert planner.assemble_plan(intent(), snapshot, NOW) is None
    snapshot.tool_surface = ToolSurface(
        run_kind=RUN_KIND_FOREGROUND_CHAT, tool_ids=("builtin.reminder.create",)
    )
    assert planner.assemble_plan(intent(), snapshot, NOW) is not None


def test_preread_tool_context_is_used_for_projection(monkeypatch):
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.social.checkin", tags=("social",), priority=20),
    )
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    snapshot = _snapshot(tool_settings())
    snapshot.tool_context = surface_context(world={"part_of_day": "late_night"})
    surface = planner.resolve_surface(snapshot)
    assert surface.tool_ids == ("builtin.reminder.create",)
    assert surface.excluded == (
        {"tool_id": "builtin.social.checkin", "reason": "part_of_day:late_night"},
    )
    assert surface.surface_hash


# --- 第 9 步：步骤形状与内部增强 -------------------------------------------


def test_post_process_step_sequence_shape_is_frozen():
    names = [handler.__name__ for handler in post_process.STEP_HANDLERS]
    assert names == [
        "run_scene_update",
        "run_state_update",
        "run_goal_review",
        "run_summary",
        "run_memory_extract",
        "run_ledger_extraction",
        "run_ledger_confirmation",
        "run_budget_observer",
        "run_evaluation",
        "run_world_update",
        "run_character_action_sync",
        "run_action_planning",
        # 通道收敛声明（2026-09-30，台账 §5.2）：新增收尾评估步（非 tool 域改脏）。
        "run_memory_evaluate",
    ]
    assert len(names) == 13


def _post_process_ctx(trace, *, action_intent=None):
    return post_process.PostProcessContext(
        session_id="s-tool",
        user_id="u-tool",
        user_input="明天早上八点提醒我开会",
        ai_reply="好呀",
        state=SimpleNamespace(messages=[], user_id="u-tool"),
        analysis=SimpleNamespace(),
        trace=trace,
        selected_goal=SimpleNamespace(goal=SimpleNamespace(id="g-1", type="user_care")),
        intention=SimpleNamespace(intention="comfort_user"),
        action_intent=action_intent
        or intent(),
    )


@pytest.fixture
def _no_action_engine(monkeypatch):
    calls: list[dict] = []

    async def _fake(user_id, action_intent, session_id=None, goal_id=None, source="conversation"):
        calls.append({"user_id": user_id, "goal_id": goal_id, "action_type": action_intent.action_type})
        return None

    import app.application.action_engine as action_engine

    monkeypatch.setattr(action_engine, "run_action_planning", _fake)
    return calls


@pytest.mark.asyncio
async def test_step_nine_is_unchanged_when_surface_flag_is_off(
    monkeypatch, override_settings, _no_action_engine, v24_tool_env
):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_SURFACE_ENABLED=False)
    override_settings()

    def _forbidden(*args, **kwargs):
        raise AssertionError("子闸关闭时不得调用决策管线")

    monkeypatch.setattr(decision_pipeline, "run_pipeline", _forbidden)
    trace = TurnTraceSession(user_id="u-tool")
    ctx = _post_process_ctx(trace)
    await post_process.run_action_planning(ctx)
    assert _no_action_engine and _no_action_engine[0]["goal_id"] == "g-1"
    step = next(item for item in trace.steps if item.name == "action_planning")
    assert step.extra == {}


@pytest.mark.asyncio
async def test_step_nine_with_surface_flag_on_feeds_capabilities_and_audits(
    monkeypatch, override_settings, _no_action_engine, v24_tool_env
):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_SURFACE_ENABLED=True)
    override_settings(observability_persist_enabled=True)

    registry = builtin_registry()
    monkeypatch.setattr(
        "app.services.tool.registry.get_tool_registry", lambda: registry
    )
    captured: dict = {}
    records: list = []

    real_run_pipeline = decision_pipeline.run_pipeline

    def _capture(**kwargs):
        captured.update(kwargs)
        return real_run_pipeline(**kwargs)

    monkeypatch.setattr(decision_pipeline, "run_pipeline", _capture)
    monkeypatch.setattr(
        "app.application.observability.on_decision", lambda record: records.append(record)
    )
    trace = TurnTraceSession(user_id="u-tool")
    ctx = _post_process_ctx(trace)
    await post_process.run_action_planning(ctx)

    assert captured["capabilities"] == list(
        ToolSurfaceResolver(registry).resolve(
            RUN_KIND_FOREGROUND_CHAT, surface_context()
        ).tool_ids
    )
    assert captured["chat_response"] is True

    step = next(item for item in trace.steps if item.name == "action_planning")
    surface_payload = step.extra["tool_surface"]
    assert surface_payload["run_kind"] == RUN_KIND_FOREGROUND_CHAT
    assert surface_payload["surface_hash"]
    assert set(surface_payload["tool_ids"]) == set(captured["capabilities"])
    assert surface_payload["excluded"]

    assert len(records) == 1
    record = records[0]
    assert record.decision == "tool_surface"
    assert record.reason == surface_payload["surface_hash"]
    assert record.candidates["winner"] == "chat_response"
    tool_rows = [
        row for row in record.candidates["candidates"] if row["source"] == "capability"
    ]
    assert tool_rows and all(row["tool_id"] for row in tool_rows)
    assert all(row["scores"] and row["gates"] and row["won"] is False for row in tool_rows)
    assert sum(1 for row in record.candidates["candidates"] if row["won"]) == 1


@pytest.mark.asyncio
async def test_step_nine_surface_failure_does_not_break_action_planning(
    monkeypatch, override_settings, _no_action_engine, v24_tool_env
):
    v24_tool_env(TOOL_SYSTEM_ENABLED=True, TOOL_SURFACE_ENABLED=True)
    override_settings()

    def _boom(**kwargs):
        raise RuntimeError("decision pipeline down")

    monkeypatch.setattr(decision_pipeline, "run_pipeline", _boom)
    monkeypatch.setattr(
        "app.services.tool.registry.get_tool_registry", builtin_registry
    )
    trace = TurnTraceSession(user_id="u-tool")
    await post_process.run_action_planning(_post_process_ctx(trace))
    assert _no_action_engine and _no_action_engine[0]["user_id"] == "u-tool"
    step = next(item for item in trace.steps if item.name == "action_planning")
    assert step.extra == {}


@pytest.mark.asyncio
async def test_step_nine_without_intent_is_noop(override_settings):
    override_settings()
    trace = TurnTraceSession(user_id="u-tool")
    ctx = _post_process_ctx(trace, action_intent=None)
    ctx.action_intent = None
    await post_process.run_action_planning(ctx)
    assert trace.steps == []


def test_registered_capability_map_still_matches_v9():
    assert set(ACTION_CAPABILITY_MAP) == set(ACTION_TOOL_MAP)
    assert ACTION_CAPABILITY_MAP["create_reminder"] == ("reminder", "create")


def test_intent_params_are_not_mutated_by_assembly(monkeypatch):
    registry = builtin_registry()
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    snapshot = _snapshot(tool_settings())
    original = intent()
    before = dict(original.params)
    planner.assemble_plan(original, snapshot, NOW)
    assert original.params == before


def test_plan_expiry_uses_snapshot_settings(monkeypatch):
    registry = builtin_registry()
    monkeypatch.setattr(planner, "get_tool_registry", lambda: registry)
    settings = tool_settings()
    snapshot = _snapshot(settings)
    moment = datetime(2026, 9, 14, 8, 0, 0)
    plan = planner.assemble_plan(intent(), snapshot, moment)
    assert plan.expires_at == moment + timedelta(minutes=settings.action_plan_expires_minutes)
