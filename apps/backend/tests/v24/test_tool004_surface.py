"""TOOL-004 §6.1/§6.3：工具面六维投影、排序截断、哈希与零 IO（E1、E3~E6、E13、E14）。"""

import logging
from pathlib import Path

import pytest

from app.character.asuna.action import ACTION_CAPABILITY_MAP, ACTION_TOOL_MAP
from app.character.asuna.tool import (
    SURFACE_RULES,
    SurfaceRule,
    relationship_stage_rank,
)
from app.models.tool import ToolSurface
from app.services.tool import surface as surface_module
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.surface import (
    SURFACE_LIMIT_REASON,
    ToolSurfacePolicy,
    ToolSurfaceResolver,
    surface_hash,
)
from tests.v24.tool002_support import BUILTIN_TOOL_IDS
from tests.v24.tool004_support import (
    NOW,
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
    builtin_registry,
    install_io_probe,
    notification_send_parameters,
    registry_with,
    surface_context,
    tool_definition,
    tool_settings,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

SURFACE_LOGGER = "app.services.tool.surface"

READ_ONLY_IDS = ("world.env.query", "builtin.search.query")

# TOOL-010：`builtin.search.query` 走路线 B（无可用检索来源、保持 unavailable），
# 工具面按 §6.3 E1 默认裁剪（reason=`unavailable:source_not_configured`），
# 因此实际进面的只读工具只剩环境查询。
SURFACED_READ_ONLY_IDS = ("world.env.query",)


def resolve(registry, ctx, *, settings=None) -> ToolSurface:
    return ToolSurfaceResolver(registry, settings).resolve(ctx.run_kind, ctx)


def reasons_for(surface: ToolSurface) -> dict[str, str]:
    return {item["tool_id"]: item["reason"] for item in surface.excluded}


# --- E1 注册表缺失 -----------------------------------------------------------


def test_e1_registry_absent_returns_empty_surface():
    ctx = surface_context()
    empty = ToolSurfaceResolver(None, ctx.settings).resolve(ctx.run_kind, ctx)
    assert empty.tool_ids == ()
    assert empty.excluded == ()
    assert empty.run_kind == RUN_KIND_FOREGROUND_CHAT
    assert empty.surface_hash
    again = ToolSurfaceResolver(None, ctx.settings).resolve(ctx.run_kind, ctx)
    assert again.surface_hash == empty.surface_hash


# --- 维度一｜Run Profile -----------------------------------------------------


def test_run_profile_foreground_keeps_channel_and_autonomous_tick_cuts_it():
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition(
            "channel.feishu.send",
            namespace="channel",
            capability="notification",
            action="send",
            tags=("channel", "feishu"),
            side_effects=("send_external",),
            priority=20,
            parameters=notification_send_parameters(),
        ),
    )
    foreground = resolve(
        registry, surface_context(run_kind=RUN_KIND_FOREGROUND_CHAT)
    )
    autonomous = resolve(registry, surface_context(run_kind=RUN_KIND_AUTONOMOUS_TICK))
    assert "channel.feishu.send" in foreground.tool_ids
    assert "channel.feishu.send" not in autonomous.tool_ids
    assert reasons_for(autonomous)["channel.feishu.send"].startswith("run_profile:")


def test_run_profile_event_driven_keeps_read_only_tools():
    surface = resolve(
        builtin_registry(), surface_context(run_kind=RUN_KIND_EVENT_DRIVEN)
    )
    assert surface.tool_ids == SURFACED_READ_ONLY_IDS
    excluded = reasons_for(surface)
    assert set(excluded) == set(BUILTIN_TOOL_IDS) - set(SURFACED_READ_ONLY_IDS)
    assert excluded["channel.feishu.send"] == "tool_status:disabled"
    assert excluded["builtin.search.query"] == "unavailable:source_not_configured"
    assert all(
        reason.startswith("run_profile:")
        for tool_id, reason in excluded.items()
        if tool_id not in ("channel.feishu.send", "builtin.search.query")
    )


def test_run_profile_projections_differ_across_profiles():
    registry = builtin_registry()
    ctx = surface_context()
    surfaces = {
        run_kind: resolve(registry, surface_context(run_kind=run_kind))
        for run_kind in (
            RUN_KIND_FOREGROUND_CHAT,
            RUN_KIND_AUTONOMOUS_TICK,
            RUN_KIND_EVENT_DRIVEN,
        )
    }
    hashes = {item.surface_hash for item in surfaces.values()}
    assert len(hashes) == 3
    assert surfaces[RUN_KIND_FOREGROUND_CHAT].tool_ids != surfaces[
        RUN_KIND_EVENT_DRIVEN
    ].tool_ids
    assert ctx.run_kind == RUN_KIND_FOREGROUND_CHAT


# --- 维度二｜日时段 ---------------------------------------------------------


def test_part_of_day_late_night_cuts_channel_and_social_tag():
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition(
            "channel.feishu.send",
            namespace="channel",
            capability="notification",
            action="send",
            tags=("channel", "feishu"),
            side_effects=("send_external",),
            priority=20,
            parameters=notification_send_parameters(),
        ),
        tool_definition("builtin.social.checkin", tags=("social",), priority=30),
    )
    late = resolve(registry, surface_context(world={"part_of_day": "late_night"}))
    morning = resolve(registry, surface_context(world={"part_of_day": "morning"}))
    assert late.tool_ids == ("builtin.reminder.create",)
    assert reasons_for(late) == {
        "channel.feishu.send": "part_of_day:late_night",
        "builtin.social.checkin": "part_of_day:late_night",
    }
    assert set(morning.tool_ids) == {
        "builtin.reminder.create",
        "channel.feishu.send",
        "builtin.social.checkin",
    }
    assert late.surface_hash != morning.surface_hash


# --- 维度三｜场景 -----------------------------------------------------------


def test_scene_focused_tone_cuts_ambient_and_casual_keeps_it():
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.ambient.note", tags=("ambient",), priority=20),
    )
    focused = resolve(registry, surface_context(scene={"tone_bias": "focused"}))
    casual = resolve(registry, surface_context(scene={"tone_bias": "casual"}))
    assert focused.tool_ids == ("builtin.reminder.create",)
    assert reasons_for(focused) == {"builtin.ambient.note": "scene:focused"}
    assert "builtin.ambient.note" in casual.tool_ids
    assert casual.excluded == ()


def test_scene_dimension_is_default_open_for_ambient():
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.ambient.note", tags=("ambient",), priority=20),
    )
    relaxed = resolve(registry, surface_context(scene={"tone_bias": "relaxed"}))
    assert "builtin.ambient.note" in relaxed.tool_ids


# --- 维度四｜关系阶段 -------------------------------------------------------


def test_relationship_stage_below_friend_cuts_intimate_tag():
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.intimate.share", tags=("intimate",), priority=20),
    )
    stranger = resolve(registry, surface_context(relationship={"stage": "stranger"}))
    friend = resolve(registry, surface_context(relationship={"stage": "friend"}))
    partner = resolve(registry, surface_context(relationship={"stage": "partner"}))
    assert stranger.tool_ids == ("builtin.reminder.create",)
    assert reasons_for(stranger) == {"builtin.intimate.share": "relationship_stage:stranger"}
    assert "builtin.intimate.share" in friend.tool_ids
    assert "builtin.intimate.share" in partner.tool_ids
    assert stranger.surface_hash != friend.surface_hash
    assert relationship_stage_rank("stranger") < relationship_stage_rank("friend")


# --- 维度五｜世界可用性 -----------------------------------------------------


def test_world_disabled_cuts_world_namespace():
    registry = builtin_registry()
    on = resolve(registry, surface_context(settings=tool_settings(world_enabled=True)))
    off = resolve(registry, surface_context(settings=tool_settings(world_enabled=False)))
    world_ids = {item.id for item in registry.list(namespace="world")}
    assert world_ids & set(on.tool_ids)
    assert not (world_ids & set(off.tool_ids))
    assert all(
        reasons_for(off)[tool_id] == "world_unavailable" for tool_id in world_ids
    )


# --- 维度六｜工具状态 -------------------------------------------------------


def test_tool_status_covers_code_runtime_and_breaker():
    registry = builtin_registry()
    assert reasons_for(resolve(registry, surface_context()))["channel.feishu.send"] == (
        "tool_status:disabled"
    )
    registry.unregister("channel.feishu.send")
    registry.register(
        tool_definition("builtin.reminder.legacy", status="deprecated", priority=15)
    )
    registry.set_runtime_disabled("builtin.reminder.create")
    registry.mark_tripped("builtin.reminder.cancel")
    excluded = reasons_for(resolve(registry, surface_context()))
    assert excluded["builtin.reminder.legacy"] == "tool_status:deprecated"
    assert excluded["builtin.reminder.create"] == "tool_status:disabled"
    assert excluded["builtin.reminder.cancel"] == "tool_status:tripped"


def test_runtime_disabled_is_reversible_and_survives_effective_status():
    registry = builtin_registry()
    assert registry.effective_status("builtin.reminder.create") == "enabled"
    assert registry.set_runtime_disabled("builtin.reminder.create") is True
    assert registry.effective_status("builtin.reminder.create") == "disabled"
    assert registry.runtime_disabled_ids() == frozenset({"builtin.reminder.create"})
    assert registry.clear_runtime_disabled("builtin.reminder.create") is True
    assert registry.effective_status("builtin.reminder.create") == "enabled"
    assert registry.runtime_disabled_ids() == frozenset()


def test_runtime_disable_ignores_unregistered_tool():
    registry = builtin_registry()
    assert registry.set_runtime_disabled("builtin.ghost.tool") is False
    assert registry.clear_runtime_disabled("builtin.ghost.tool") is False
    assert registry.runtime_disabled_ids() == frozenset()


# --- E3 首条命中短路 -------------------------------------------------------


def test_e3_first_hit_wins_single_entry_per_tool():
    surface = resolve(
        builtin_registry(), surface_context(run_kind=RUN_KIND_AUTONOMOUS_TICK)
    )
    ids = [item["tool_id"] for item in surface.excluded]
    assert len(ids) == len(set(ids))
    assert reasons_for(surface)["channel.feishu.send"] == "tool_status:disabled"


# --- E4 上限截断 -----------------------------------------------------------


def test_e4_surface_limit_keeps_lowest_priority_and_lists_overflow():
    registry = registry_with(
        *(tool_definition(f"builtin.tool_{index}", priority=index) for index in range(1, 6))
    )
    ctx = surface_context(settings=tool_settings(v24_tool_surface_max_tools=1))
    surface = resolve(registry, ctx)
    assert surface.tool_ids == ("builtin.tool_1",)
    overflow = {
        item["tool_id"]: item["reason"]
        for item in surface.excluded
    }
    assert overflow == {
        "builtin.tool_2": SURFACE_LIMIT_REASON,
        "builtin.tool_3": SURFACE_LIMIT_REASON,
        "builtin.tool_4": SURFACE_LIMIT_REASON,
        "builtin.tool_5": SURFACE_LIMIT_REASON,
    }


def test_surface_rule_max_tools_overrides_global(monkeypatch):
    monkeypatch.setitem(
        surface_module.SURFACE_RULES,
        RUN_KIND_FOREGROUND_CHAT,
        SurfaceRule(run_kind=RUN_KIND_FOREGROUND_CHAT, max_tools=2, reason="测试上限"),
    )
    surface = resolve(
        builtin_registry(),
        surface_context(settings=tool_settings(v24_tool_surface_max_tools=99)),
    )
    assert len(surface.tool_ids) == 2
    assert [item["reason"] for item in surface.excluded].count(SURFACE_LIMIT_REASON) > 0


# --- 排序与哈希确定性 -------------------------------------------------------


def test_order_is_priority_then_tool_id_lexicographic():
    registry = registry_with(
        tool_definition("builtin.zeta", priority=5),
        tool_definition("builtin.alpha", priority=5),
        tool_definition("builtin.mid", priority=1),
    )
    surface = resolve(registry, surface_context())
    assert surface.tool_ids == ("builtin.mid", "builtin.alpha", "builtin.zeta")


def test_surface_hash_is_reproducible_and_input_sensitive():
    registry = builtin_registry()
    ctx = surface_context()
    first = resolve(registry, ctx)
    second = resolve(registry, surface_context())
    assert first.surface_hash == second.surface_hash
    assert first.tool_ids == second.tool_ids
    autonomous = resolve(registry, surface_context(run_kind=RUN_KIND_AUTONOMOUS_TICK))
    assert autonomous.surface_hash != first.surface_hash
    late = resolve(registry, surface_context(world={"part_of_day": "late_night"}))
    assert late.surface_hash != first.surface_hash
    assert surface_hash(RUN_KIND_FOREGROUND_CHAT, ctx, SURFACE_RULES[RUN_KIND_FOREGROUND_CHAT], 12, ("a", "b")) != surface_hash(
        RUN_KIND_FOREGROUND_CHAT, ctx, SURFACE_RULES[RUN_KIND_FOREGROUND_CHAT], 12, ("b", "a")
    )


def test_repeated_resolution_is_byte_identical():
    registry = builtin_registry()
    ctx = surface_context(world={"part_of_day": "late_night"})
    snapshots = [resolve(registry, ctx).model_dump() for _ in range(3)]
    assert snapshots[0] == snapshots[1] == snapshots[2]


# --- E5 世界事实缺省降级 ---------------------------------------------------


def test_e5_empty_world_degrades_without_cutting(caplog):
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.social.checkin", tags=("social",), priority=20),
    )
    with caplog.at_level(logging.INFO, logger=SURFACE_LOGGER):
        surface = resolve(registry, surface_context())
    assert surface.excluded == ()
    assert "builtin.social.checkin" in surface.tool_ids
    assert "surface_part_of_day_degraded" in caplog.text


# --- E6 未注册 Run Profile -------------------------------------------------


def test_e6_unknown_run_kind_uses_default_rule_and_warns(caplog):
    registry = registry_with(tool_definition("builtin.reminder.create", priority=10))
    with caplog.at_level(logging.WARNING, logger=SURFACE_LOGGER):
        surface = resolve(
            registry, surface_context(run_kind="unregistered_profile")
        )
    assert surface.run_kind == "unregistered_profile"
    assert surface.tool_ids == ("builtin.reminder.create",)
    assert "surface_unknown_run_kind" in caplog.text
    assert ToolSurfacePolicy().policy_for("unregistered_profile").reason


# --- E13 缺 tags / E14 未知语气 -------------------------------------------


def test_e13_tool_without_tags_is_not_cut_by_tag_rules():
    registry = registry_with(tool_definition("builtin.reminder.create", tags=(), priority=10))
    surface = resolve(
        registry, surface_context(scene={"tone_bias": "focused"}, relationship={"stage": "stranger"})
    )
    assert surface.tool_ids == ("builtin.reminder.create",)
    assert surface.excluded == ()


def test_e14_unknown_tone_bias_does_not_cut_and_warns(caplog):
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.ambient.note", tags=("ambient",), priority=20),
    )
    with caplog.at_level(logging.WARNING, logger=SURFACE_LOGGER):
        surface = resolve(registry, surface_context(scene={"tone_bias": "mysterious"}))
    assert "builtin.ambient.note" in surface.tool_ids
    assert "surface_unknown_tone_bias" in caplog.text


def test_unknown_relationship_stage_is_conservative(caplog):
    registry = registry_with(
        tool_definition("builtin.reminder.create", priority=10),
        tool_definition("builtin.intimate.share", tags=("intimate",), priority=20),
    )
    with caplog.at_level(logging.WARNING, logger=SURFACE_LOGGER):
        surface = resolve(registry, surface_context(relationship={"stage": "soulmate"}))
    assert "builtin.intimate.share" in surface.tool_ids
    assert "surface_unknown_relationship_stage" in caplog.text


def test_unknown_scene_tone_missing_is_conservative(caplog):
    registry = registry_with(tool_definition("builtin.ambient.note", tags=("ambient",)))
    with caplog.at_level(logging.INFO, logger=SURFACE_LOGGER):
        surface = resolve(registry, surface_context(scene={}))
    assert "builtin.ambient.note" in surface.tool_ids
    assert "surface_scene_degraded" in caplog.text


# --- 零 IO / 零 LLM --------------------------------------------------------


def test_projection_performs_zero_io_and_zero_llm(monkeypatch):
    probe = install_io_probe(monkeypatch)
    registry = builtin_registry()
    for run_kind in (
        RUN_KIND_FOREGROUND_CHAT,
        RUN_KIND_AUTONOMOUS_TICK,
        RUN_KIND_EVENT_DRIVEN,
    ):
        resolve(
            registry,
            surface_context(
                run_kind=run_kind,
                world={"part_of_day": "late_night", "locations": ["home"]},
                scene={"tone_bias": "focused"},
                relationship={"stage": "stranger"},
                inventory=["苹果"],
                authorized_recipients=["u-9"],
            ),
        )
    assert probe.counts == {"db": 0, "net": 0, "llm": 0}


def test_surface_module_has_no_io_imports():
    source = (BACKEND_ROOT / "app/services/tool/surface.py").read_text(encoding="utf-8")
    for forbidden in (
        "app.repositories",
        "sqlalchemy",
        "httpx",
        "requests",
        "SessionLocal",
        "llm_gateway",
        "app.chains",
        "world_engine",
    ):
        assert forbidden not in source


# --- 资产一致性 -------------------------------------------------------------


def test_action_tool_map_covers_every_action_type_and_binds_registered_tools():
    registry = builtin_registry()
    assert set(ACTION_TOOL_MAP) == set(ACTION_CAPABILITY_MAP)
    for action_type, tool_ids in ACTION_TOOL_MAP.items():
        assert tool_ids
        for tool_id in tool_ids:
            definition = registry.get(tool_id)
            assert definition is not None, f"{action_type} → {tool_id} 未注册"
            if definition.namespace == "channel":
                # TOOL-010：通道工具绑定独立的 `channel_feishu` 能力（外发与"行动 note"
                # 必须可分流），共用 legacy 能力名的只有内置工具。
                continue
            assert (
                definition.capability,
                definition.action,
            ) == ACTION_CAPABILITY_MAP[action_type]


def test_toolcontext_field_set_is_frozen_to_documented_shape():
    from dataclasses import fields

    from app.services.tool.context import ToolContext

    # TOOL-010 追加 `dedupe_key`（外发类能力的幂等键下传面，§7.6），其余字段为 TOOL-004 形态。
    assert {field.name for field in fields(ToolContext)} == {
        "user_id",
        "character_id",
        "record_id",
        "now",
        "settings",
        "run_kind",
        "run_id",
        "source",
        "dedupe_key",
        "world",
        "inventory",
        "situations",
        "scene",
        "relationship",
        "authorized_recipients",
    }


def test_surface_limit_defaults_to_ctx_settings():
    registry = builtin_registry()
    ctx = surface_context(settings=tool_settings(v24_tool_surface_max_tools=1))
    resolver = ToolSurfaceResolver(registry)
    surface = resolver.resolve(ctx.run_kind, ctx)
    assert len(surface.tool_ids) == 1
    # TOOL-010：`builtin.search.query` 被可用性降级维度先裁掉，不计入上限截断。
    assert [item["reason"] for item in surface.excluded].count(SURFACE_LIMIT_REASON) == 7


@pytest.mark.parametrize("run_kind", list(SURFACE_RULES))
def test_every_declared_rule_projects_without_error(run_kind):
    surface = resolve(builtin_registry(), surface_context(run_kind=run_kind))
    assert isinstance(surface, ToolSurface)
    assert surface.surface_hash


def test_golden_now_is_not_part_of_hash_input():
    early = resolve(builtin_registry(), surface_context(now=NOW))
    late = resolve(builtin_registry(), surface_context(now=NOW.replace(hour=23)))
    assert early.surface_hash == late.surface_hash


def test_registry_fixture_tools_are_enabled_except_channel():
    registry = ToolRegistry()
    register_builtin_tools(registry)
    statuses = {item.id: registry.effective_status(item.id) for item in registry.list()}
    assert set(statuses) == set(BUILTIN_TOOL_IDS)
    assert statuses["channel.feishu.send"] == "disabled"
    assert all(
        status == "enabled" for tool_id, status in statuses.items() if tool_id != "channel.feishu.send"
    )
