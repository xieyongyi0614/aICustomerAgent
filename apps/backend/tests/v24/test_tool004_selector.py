"""TOOL-004 §6.1/§6.3：工具选择的确定性、一词多工具与旧映射兜底（E2、E7、E8）。

P0-2：追加"收件人感知"选择（`channel.*` 在外部投递意图下整体前置）的确定性与纯函数断言。
"""

import pytest

from app.character.asuna.action import ACTION_TOOL_MAP
from app.models.action import ActionIntent
from app.models.tool import ToolSurface
from app.services.tool.surface import (
    RECIPIENT_PARAM_KEYS,
    SELECTION_REASON_CHANNEL_RECIPIENT,
    SELECTION_REASON_NO_CANDIDATE,
    SELECTION_REASON_PRIORITY_ORDER,
    ToolSelector,
    ToolSurfaceResolver,
    delivery_recipient,
)
from tests.v24.tool004_support import (
    RUN_KIND_AUTONOMOUS_TICK,
    builtin_registry,
    registry_with,
    surface_context,
    tool_definition,
)
from tests.v24.tool010_support import (
    CHANNEL_ENVS,
    CHANNEL_TOOL_ID,
    NOTIFICATION_TOOL_ID,
    builtin_registry as channel_bound_registry,
    enable,
    reset_runtime_state,
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
    """TOOL-010｜`query_search` 走路线 B：`builtin.search.query` 默认被工具面裁剪，
    故与 `send_notification` 一样不参与"映射可解析"的断言（E1）。"""
    registry = builtin_registry()
    surface = surface_of(registry)
    selector = ToolSelector(registry)
    for action_type, tool_ids in ACTION_TOOL_MAP.items():
        if action_type in ("send_notification", "query_search"):
            continue
        binding = selector.select(intent(action_type), surface)
        assert binding is not None, action_type
        assert binding.tool_id in tool_ids


def test_select_one_to_many_picks_lowest_priority():
    """无收件人键的 `send_notification`：维持 priority + 字典序（P0-2 非触发路径）。"""
    registry = builtin_registry()
    surface = surface_of(registry)
    selection = ToolSelector(registry).select_with_reason(intent("send_notification"), surface)
    assert selection.binding is not None
    assert selection.binding.tool_id == "builtin.notification.send"
    assert selection.reason == SELECTION_REASON_PRIORITY_ORDER
    assert selection.recipient == ""


# --- P0-2 收件人感知（外部投递优先通道工具） ---------------------------------


def _delivery_surface(monkeypatch) -> tuple:
    """通道可用态的内置注册表与工具面：`channel.feishu.send` 与本地通知候选同时在面内。"""
    enable(monkeypatch, **CHANNEL_ENVS)
    reset_runtime_state()
    registry = channel_bound_registry()
    return registry, surface_of(registry)


def test_recipient_intent_prefers_channel_namespace(monkeypatch):
    registry, surface = _delivery_surface(monkeypatch)
    assert CHANNEL_TOOL_ID in surface.tool_ids
    assert NOTIFICATION_TOOL_ID in surface.tool_ids
    assert surface.tool_ids.index(CHANNEL_TOOL_ID) > surface.tool_ids.index(
        NOTIFICATION_TOOL_ID
    )

    selection = ToolSelector(registry).select_with_reason(
        intent("send_notification", recipient="ou_asuna"), surface
    )

    assert selection.binding is not None
    assert selection.binding.tool_id == CHANNEL_TOOL_ID
    assert selection.reason == SELECTION_REASON_CHANNEL_RECIPIENT
    assert selection.recipient == "ou_asuna"
    assert selection.candidates[0] == CHANNEL_TOOL_ID
    assert sorted(selection.candidates) == [NOTIFICATION_TOOL_ID, CHANNEL_TOOL_ID]


def test_select_without_recipient_keeps_local_tool_under_channel_binding(monkeypatch):
    """同一注册表与工具面：去掉收件人键即回到本地工具（规则只看意图参数）。"""
    registry, surface = _delivery_surface(monkeypatch)
    selection = ToolSelector(registry).select_with_reason(
        intent("send_notification", content="在吗"), surface
    )
    assert selection.binding.tool_id == NOTIFICATION_TOOL_ID
    assert selection.reason == SELECTION_REASON_PRIORITY_ORDER


@pytest.mark.parametrize("key", RECIPIENT_PARAM_KEYS)
def test_every_recipient_param_key_triggers_channel_preference(monkeypatch, key):
    registry, surface = _delivery_surface(monkeypatch)
    selection = ToolSelector(registry).select_with_reason(
        intent("send_notification", content="在吗", **{key: "ou_asuna"}), surface
    )
    assert selection.binding.tool_id == CHANNEL_TOOL_ID
    assert selection.reason == SELECTION_REASON_CHANNEL_RECIPIENT


@pytest.mark.parametrize(
    "value", ["", "   ", None, 42, ["ou_asuna"], {"external_id": "ou"}]
)
def test_blank_or_non_text_recipient_keeps_priority_order(monkeypatch, value):
    registry, surface = _delivery_surface(monkeypatch)
    selection = ToolSelector(registry).select_with_reason(
        intent("send_notification", content="在吗", recipient=value), surface
    )
    assert selection.binding.tool_id == NOTIFICATION_TOOL_ID
    assert selection.reason == SELECTION_REASON_PRIORITY_ORDER


def test_recipient_rule_needs_both_channel_and_other_candidates(monkeypatch):
    """候选集只有通道声明（本地声明被工具面裁掉）时不触发优先规则。"""
    registry, surface = _delivery_surface(monkeypatch)
    channel_only = ToolSurface(
        run_kind=surface.run_kind, tool_ids=(CHANNEL_TOOL_ID,), surface_hash="channel-only"
    )
    selection = ToolSelector(registry).select_with_reason(
        intent("send_notification", recipient="ou_asuna"), channel_only
    )
    assert selection.binding.tool_id == CHANNEL_TOOL_ID
    assert selection.reason == SELECTION_REASON_PRIORITY_ORDER


def test_selection_is_deterministic_across_runs(monkeypatch):
    registry, surface = _delivery_surface(monkeypatch)
    selector = ToolSelector(registry)
    picks = {
        (
            selection.binding.tool_id if selection.binding else None,
            selection.reason,
            selection.candidates,
        )
        for selection in (
            selector.select_with_reason(
                intent("send_notification", recipient="ou_asuna"), surface
            )
            for _ in range(5)
        )
    }
    assert len(picks) == 1
    assert next(iter(picks))[0] == CHANNEL_TOOL_ID


def test_delivery_recipient_is_a_pure_accessor():
    assert delivery_recipient(intent("send_notification", recipient=" ou_a ")) == "ou_a"
    assert delivery_recipient(intent("send_notification", recipient_id="ou_b")) == "ou_b"
    assert delivery_recipient(intent("send_notification", to="ou_c")) == "ou_c"
    assert delivery_recipient(intent("send_notification", external_id="ou_d")) == "ou_d"
    assert delivery_recipient(intent("send_notification", recipient="")) == ""
    assert delivery_recipient(intent("send_notification")) == ""
    assert delivery_recipient(None) == ""


def test_no_candidate_reports_reason():
    selection = ToolSelector(builtin_registry()).select_with_reason(intent(), EMPTY_SURFACE)
    assert selection.binding is None
    assert selection.reason == SELECTION_REASON_NO_CANDIDATE


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
    if action_type == "query_search":
        # TOOL-010｜路线 B：检索工具默认裁剪出工具面，故选择器返回 None（E1）。
        assert binding is None
        return
    assert binding is not None
    assert binding.tool_id == tool_id
