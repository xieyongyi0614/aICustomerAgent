"""TOOL-004 §6.1/§6.3：工具选择的确定性、一词多工具与旧映射兜底（E2、E7、E8）。"""

import pytest

from app.character.asuna.action import ACTION_TOOL_MAP
from app.models.action import ActionIntent
from app.models.tool import ToolSurface
from app.services.tool.surface import ToolSelector, ToolSurfaceResolver
from tests.v24.tool004_support import (
    RUN_KIND_AUTONOMOUS_TICK,
    builtin_registry,
    registry_with,
    surface_context,
    tool_definition,
)


def intent(action_type: str = "create_reminder", **params) -> ActionIntent:
    return ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=params or {"content": "开会", "due_at": "2026-09-15T08:00:00"},
    )


def surface_of(registry, ctx=None) -> ToolSurface:
    ctx = ctx if ctx is not None else surface_context()
    return ToolSurfaceResolver(registry).resolve(ctx.run_kind, ctx)


EMPTY_SURFACE = ToolSurface(run_kind="foreground_chat", tool_ids=(), surface_hash="empty")


# --- E2 空工具面 -------------------------------------------------------------


def test_e2_empty_surface_returns_none():
    assert ToolSelector(builtin_registry()).select(intent(), EMPTY_SURFACE) is None


def test_e2_surface_without_target_tool_returns_none():
    surface = ToolSurface(run_kind="foreground_chat", tool_ids=("world.env.query",))
    assert ToolSelector(builtin_registry()).select(intent(), surface) is None


def test_registry_absent_returns_none():
    assert ToolSelector(None).select(intent(), surface_of(builtin_registry())) is None


# --- 正常选择 -----------------------------------------------------------------


def test_select_resolves_binding_from_surface():
    registry = builtin_registry()
    binding = ToolSelector(registry).select(intent(), surface_of(registry))
    assert binding is not None
    assert binding.tool_id == "builtin.reminder.create"
    assert (binding.capability, binding.action) == ("reminder", "create")


def test_select_is_deterministic_across_runs():
    registry = builtin_registry()
    surface = surface_of(registry)
    picks = {
        ToolSelector(registry).select(intent(), surface).tool_id for _ in range(5)
    }
    assert picks == {"builtin.reminder.create"}


def test_select_follows_action_tool_map_for_every_declared_action_type():
    registry = builtin_registry()
    surface = surface_of(registry)
    selector = ToolSelector(registry)
    for action_type, tool_ids in ACTION_TOOL_MAP.items():
        if action_type == "send_notification":
            continue
        binding = selector.select(intent(action_type), surface)
        assert binding is not None, action_type
        assert binding.tool_id in tool_ids


def test_select_one_to_many_picks_lowest_priority():
    registry = builtin_registry()
    surface = surface_of(registry)
    binding = ToolSelector(registry).select(intent("send_notification"), surface)
    assert binding is not None
    assert binding.tool_id == "builtin.notification.send"


# --- E7 一词多工具 ---------------------------------------------------------


def test_e7_one_to_three_tools_picks_priority_first():
    registry = registry_with(
        tool_definition("builtin.reminder.c", priority=30),
        tool_definition("builtin.reminder.a", priority=10),
        tool_definition("builtin.reminder.b", priority=10),
    )
    surface = surface_of(registry)
    assert set(surface.tool_ids) == {
        "builtin.reminder.c",
        "builtin.reminder.a",
        "builtin.reminder.b",
    }
    selector = ToolSelector(registry, tool_map={"create_reminder": (
        "builtin.reminder.c",
        "builtin.reminder.b",
        "builtin.reminder.a",
    )})
    binding = selector.select(intent(), surface)
    assert binding is not None and binding.tool_id == "builtin.reminder.a"
    assert selector.select(intent(), surface).tool_id == "builtin.reminder.a"


def test_e7_declared_but_cut_tools_are_not_candidates():
    registry = registry_with(
        tool_definition("builtin.reminder.keep", priority=10),
        tool_definition("builtin.reminder.drop", priority=20, tags=("social",)),
    )
    surface = ToolSurfaceResolver(registry).resolve(
        "foreground_chat", surface_context(world={"part_of_day": "late_night"})
    )
    assert surface.tool_ids == ("builtin.reminder.keep",)
    selector = ToolSelector(
        registry,
        tool_map={"create_reminder": ("builtin.reminder.drop", "builtin.reminder.keep")},
    )
    binding = selector.select(intent(), surface)
    assert binding is not None and binding.tool_id == "builtin.reminder.keep"


def test_empty_surface_after_projection_is_not_selectable():
    registry = registry_with(tool_definition("builtin.reminder.late", priority=99))
    surface = ToolSurfaceResolver(registry).resolve(
        RUN_KIND_AUTONOMOUS_TICK, surface_context(run_kind=RUN_KIND_AUTONOMOUS_TICK)
    )
    assert surface.tool_ids == ("builtin.reminder.late",)
    trivial = ToolSurface(run_kind="foreground_chat", tool_ids=())
    assert ToolSelector(registry).select(intent(), trivial) is None


# --- E8 未覆盖 action_type 的旧映射兜底 ------------------------------------


def test_e8_fallback_to_capability_map_when_tool_map_misses():
    registry = builtin_registry()
    surface = surface_of(registry)
    selector = ToolSelector(registry, tool_map={})
    binding = selector.select(intent(), surface)
    assert binding is not None
    assert binding.tool_id == "builtin.reminder.create"


def test_e8_fallback_returns_none_when_nothing_available():
    registry = builtin_registry()
    surface = ToolSurface(run_kind="foreground_chat", tool_ids=("builtin.memory.save",))
    selector = ToolSelector(registry, tool_map={})
    assert selector.select(intent(), surface) is None


def test_e8_returns_none_for_unmapped_action_type():
    registry = builtin_registry()
    selector = ToolSelector(
        registry, tool_map={}, capability_map={"create_reminder": ("reminder", "create")}
    )
    assert selector.select(intent("query_search"), surface_of(registry)) is None


def test_unregistered_mapped_tool_id_returns_none():
    registry = builtin_registry()
    surface = ToolSurface(
        run_kind="foreground_chat", tool_ids=("builtin.reminder.ghost",)
    )
    selector = ToolSelector(
        registry, tool_map={"create_reminder": ("builtin.reminder.ghost",)}
    )
    assert selector.select(intent(), surface) is None


@pytest.mark.parametrize(
    "action_type,tool_id",
    sorted(
        (action_type, tool_ids[0])
        for action_type, tool_ids in ACTION_TOOL_MAP.items()
        if action_type != "send_notification"
    ),
)
def test_declared_mapping_is_resolvable_from_builtin_registry(action_type, tool_id):
    registry = builtin_registry()
    binding = ToolSelector(registry).select(intent(action_type), surface_of(registry))
    assert binding is not None
    assert binding.tool_id == tool_id
