"""TOOL-002：解析面 / 查询面 / 生命周期 / 健康度（TOOL-002 §2.3、§4，E8~E12）。"""

import json
from dataclasses import asdict

import pytest

from app.models.tool import ToolSurface
from app.services.tool.registry import (
    TOOL_HEALTH_WINDOW_SIZE,
    ToolRegistry,
    register_builtin_tools,
)
from tests.v24.tool002_support import definition, reminder_create_schema, schema, parameter


def _registry_with_builtins() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def _describe_payload(registry: ToolRegistry) -> str:
    return json.dumps(
        [asdict(descriptor) for descriptor in registry.describe()],
        ensure_ascii=False,
    )


def test_resolve_get_has_unregistered_returns_defaults():
    registry = ToolRegistry()
    assert registry.resolve("builtin.reminder.create") is None
    assert registry.get("builtin.reminder.create") is None
    assert registry.has("builtin.reminder.create") is False
    assert registry.has("builtin.reminder.create", enabled_only=False) is False
    assert registry.effective_status("builtin.reminder.create") == "removed"


def test_has_enabled_only_semantics():
    registry = ToolRegistry()
    registry.register(definition())
    registry.register(
        definition(
            id="builtin.reminder.cancel",
            action="cancel",
            input_schema=schema(parameter("target", required=True)),
            status="disabled",
        )
    )
    assert registry.has("builtin.reminder.create") is True
    assert registry.has("builtin.reminder.cancel") is False
    assert registry.has("builtin.reminder.cancel", enabled_only=False) is True


def test_list_filters_by_namespace_status_capability_tags():
    registry = _registry_with_builtins()
    assert [item.id for item in registry.list(namespace="world")] == [
        "world.env.query",
        "world.object.create",
        "world.object.move",
        "world.object.use",
    ]
    assert [item.id for item in registry.list(capability="reminder")] == [
        "builtin.reminder.cancel",
        "builtin.reminder.create",
    ]
    assert [item.id for item in registry.list(status="disabled")] == [
        "channel.feishu.send"
    ]
    assert [item.id for item in registry.list(tags=("world", "read"))] == [
        "world.env.query"
    ]
    assert registry.list(namespace="user") == []
    assert [
        item.id
        for item in registry.list(namespace="world", capability="world_action", tags=("object",))
    ] == ["world.object.create", "world.object.move", "world.object.use"]


def test_list_is_always_sorted_by_tool_id():
    registry = ToolRegistry()
    registry.register(definition(id="builtin.reminder.cancel", action="cancel", input_schema=schema(parameter("target", required=True))))
    registry.register(definition())
    assert [item.id for item in registry.list()] == [
        "builtin.reminder.cancel",
        "builtin.reminder.create",
    ]


def test_namespaces_returns_five_indexes_sorted():
    registry = _registry_with_builtins()
    indexes = registry.namespaces()
    assert list(indexes) == ["builtin", "channel", "world", "ext.api", "user"]
    assert indexes["builtin"].tool_ids == sorted(indexes["builtin"].tool_ids)
    assert indexes["builtin"].enabled_count == 5
    assert indexes["world"].tool_ids == [
        "world.env.query",
        "world.object.create",
        "world.object.move",
        "world.object.use",
    ]
    assert indexes["world"].enabled_count == 4
    assert indexes["channel"].tool_ids == ["channel.feishu.send"]
    assert indexes["channel"].enabled_count == 0
    assert indexes["ext.api"].tool_ids == []
    assert indexes["ext.api"].enabled_count == 0
    assert indexes["user"].tool_ids == []
    assert indexes["user"].enabled_count == 0


def test_namespaces_index_is_not_mutable_from_outside():
    registry = _registry_with_builtins()
    indexes = registry.namespaces()
    indexes["world"].tool_ids.append("bogus")
    assert "bogus" not in registry.namespaces()["world"].tool_ids


def test_describe_projects_declaration_fields():
    registry = _registry_with_builtins()
    descriptors = {descriptor.tool_id: descriptor for descriptor in registry.describe()}
    reminder = descriptors["builtin.reminder.create"]
    assert reminder.name == "创建提醒"
    assert reminder.namespace == "builtin"
    assert reminder.status == "enabled"
    assert reminder.side_effects == ("write_world",)
    assert reminder.when_to_use
    assert reminder.params == {
        "content": {"type": "string", "required": True},
        "due_at": {"type": "datetime", "required": True},
        "importance": {
            "type": "enum",
            "required": False,
            "enum": ["low", "normal", "high"],
        },
    }
    environment = descriptors["world.env.query"]
    assert environment.params["dimension"]["enum"] == [
        "weather",
        "temperature",
        "time",
        "lighting",
    ]


def test_describe_output_is_byte_reproducible():
    first = _describe_payload(_registry_with_builtins())
    second = _describe_payload(_registry_with_builtins())
    registry = _registry_with_builtins()
    assert first == second == _describe_payload(registry) == _describe_payload(registry)


def test_describe_excludes_disabled_placeholder():
    registry = _registry_with_builtins()
    assert "channel.feishu.send" not in [item.tool_id for item in registry.describe()]


def test_describe_enabled_only_false_includes_disabled_and_tripped(v24_tool_env):
    """P2-5：`enabled_only=False` 显式关闭过滤，disabled / 熔断条目带真实状态回归投影。"""
    v24_tool_env(v24_tool_system_enabled=True, v24_tool_disabled_ids="world.object.move")
    registry = _registry_with_builtins()
    registry.mark_tripped("world.object.use")

    default_ids = [item.tool_id for item in registry.describe()]
    assert "channel.feishu.send" not in default_ids
    assert "world.object.move" not in default_ids
    assert "world.object.use" not in default_ids

    all_descriptors = {
        item.tool_id: item for item in registry.describe(enabled_only=False)
    }
    assert set(all_descriptors) >= {
        "channel.feishu.send",
        "world.object.move",
        "world.object.use",
    }
    assert all_descriptors["channel.feishu.send"].status == "disabled"
    assert all_descriptors["world.object.move"].status == "disabled"
    assert all_descriptors["world.object.use"].status == "disabled"
    assert all_descriptors["builtin.reminder.create"].status == "enabled"


def test_describe_enabled_only_false_respects_surface_order(v24_tool_env):
    """`enabled_only=False` 与 `surface` 组合：保 surface 序、去重、忽略未注册 id。"""
    v24_tool_env(v24_tool_system_enabled=True)
    registry = _registry_with_builtins()
    surface = ToolSurface(
        run_kind="conversation",
        tool_ids=("channel.feishu.send", "missing.tool.id", "builtin.reminder.create"),
    )
    assert [
        item.tool_id for item in registry.describe(surface=surface, enabled_only=False)
    ] == ["channel.feishu.send", "builtin.reminder.create"]


def test_describe_with_surface_keeps_surface_order_and_ignores_unknown(v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True)
    registry = _registry_with_builtins()
    surface = ToolSurface(
        run_kind="conversation",
        tool_ids=(
            "world.object.move",
            "builtin.reminder.create",
            "missing.tool.id",
            "world.object.move",
        ),
    )
    assert [item.tool_id for item in registry.describe(surface=surface)] == [
        "world.object.move",
        "builtin.reminder.create",
    ]


def test_describe_empty_surface_returns_empty(v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True)
    registry = _registry_with_builtins()
    assert registry.describe(surface=ToolSurface(run_kind="conversation")) == []


def test_describe_surface_skips_disabled_tool(v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True, v24_tool_disabled_ids="world.object.move")
    registry = _registry_with_builtins()
    surface = ToolSurface(
        run_kind="conversation",
        tool_ids=("world.object.move", "builtin.reminder.create"),
    )
    assert [item.tool_id for item in registry.describe(surface=surface)] == [
        "builtin.reminder.create"
    ]


def test_effective_status_layers(v24_tool_env):
    registry = _registry_with_builtins()
    assert registry.effective_status("builtin.reminder.create") == "enabled"
    assert registry.effective_status("channel.feishu.send") == "disabled"

    v24_tool_env(v24_tool_disabled_ids="builtin.reminder.create")
    assert registry.effective_status("builtin.reminder.create") == "disabled"

    registry._health["world.object.create"].tripped = True
    assert registry.effective_status("world.object.create") == "disabled"


def test_effective_status_terminal_code_state_wins_over_overrides(v24_tool_env):
    v24_tool_env(v24_tool_disabled_ids="builtin.reminder.create,builtin.reminder.cancel")
    registry = ToolRegistry()
    registry.register(definition(status="deprecated"))
    registry.register(
        definition(
            id="builtin.reminder.cancel",
            action="cancel",
            input_schema=schema(parameter("target", required=True)),
            status="removed",
        )
    )
    registry._health["builtin.reminder.create"].tripped = True
    registry._health["builtin.reminder.cancel"].tripped = True
    assert registry.effective_status("builtin.reminder.create") == "deprecated"
    assert registry.effective_status("builtin.reminder.cancel") == "removed"


def test_deprecated_tool_skips_describe_but_stays_resolvable():
    registry = ToolRegistry()
    registry.register(definition(status="deprecated"))
    assert registry.describe() == []
    assert registry.resolve("builtin.reminder.create") is not None
    assert registry.has("builtin.reminder.create") is False
    assert registry.has("builtin.reminder.create", enabled_only=False) is True
    assert [item.id for item in registry.list(status="deprecated")] == [
        "builtin.reminder.create"
    ]


def test_disabled_id_absent_from_describe_and_list(v24_tool_env):
    v24_tool_env(v24_tool_disabled_ids="builtin.reminder.create")
    registry = _registry_with_builtins()
    assert registry.effective_status("builtin.reminder.create") == "disabled"
    assert "builtin.reminder.create" not in [
        item.tool_id for item in registry.describe()
    ]
    assert registry.has("builtin.reminder.create") is False
    assert registry.has("builtin.reminder.create", enabled_only=False) is True
    assert registry.namespaces()["builtin"].enabled_count == 4


def test_disabled_overlay_does_not_write_back_to_definition(v24_tool_env):
    v24_tool_env(v24_tool_disabled_ids="builtin.reminder.create")
    registry = _registry_with_builtins()
    assert registry.get("builtin.reminder.create").status == "enabled"
    assert registry.effective_status("builtin.reminder.create") == "disabled"


def test_health_is_read_only_copy():
    registry = ToolRegistry()
    registry.register(definition())
    registry.record_outcome("builtin.reminder.create", ok=False, failure_kind="transient")
    snapshot = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    snapshot.consecutive_failures = 99
    snapshot.tripped = True
    assert registry.health("builtin.reminder.create")["builtin.reminder.create"].consecutive_failures == 1
    assert registry.effective_status("builtin.reminder.create") == "enabled"


def test_health_unknown_tool_id_returns_empty_dict():
    registry = ToolRegistry()
    registry.register(definition())
    assert registry.health("builtin.reminder.cancel") == {}
    assert list(registry.health()) == ["builtin.reminder.create"]


def test_record_outcome_counts_and_timestamps():
    registry = ToolRegistry()
    registry.register(definition())
    registry.record_outcome("builtin.reminder.create", ok=False, failure_kind="timeout")
    registry.record_outcome("builtin.reminder.create", ok=False, failure_kind="timeout")
    health = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.consecutive_failures == 2
    assert health.last_failure_at is not None
    assert health.last_success_at is None
    assert health.failure_rate_window == 1.0
    assert health.tripped is False

    registry.record_outcome("builtin.reminder.create", ok=True)
    health = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.consecutive_failures == 0
    assert health.last_success_at is not None
    assert health.failure_rate_window == pytest.approx(2 / 3)


def test_record_outcome_window_is_bounded():
    registry = ToolRegistry()
    registry.register(definition())
    for _ in range(3):
        registry.record_outcome("builtin.reminder.create", ok=False, failure_kind="transient")
    for _ in range(7):
        registry.record_outcome("builtin.reminder.create", ok=True)
    health = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.failure_rate_window == pytest.approx(3 / TOOL_HEALTH_WINDOW_SIZE)

    registry.record_outcome("builtin.reminder.create", ok=True)
    health = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.failure_rate_window == pytest.approx(2 / TOOL_HEALTH_WINDOW_SIZE)

    for _ in range(10):
        registry.record_outcome("builtin.reminder.create", ok=True)
    health = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.failure_rate_window == 0.0


def test_record_outcome_ignores_unregistered_tool_silently():
    registry = ToolRegistry()
    registry.register(definition())
    registry.record_outcome("builtin.reminder.cancel", ok=False, failure_kind="timeout")
    registry.record_outcome("builtin.reminder.cancel", ok=True)
    assert registry.health("builtin.reminder.cancel") == {}
    assert list(registry.health()) == ["builtin.reminder.create"]
    registered = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert registered.consecutive_failures == 0
    assert registered.last_failure_at is None
    assert registered.last_success_at is None
    assert registered.failure_rate_window == 0.0


def test_record_outcome_rejects_unknown_failure_kind():
    registry = ToolRegistry()
    registry.register(definition())
    with pytest.raises(ValueError) as excinfo:
        registry.record_outcome("builtin.reminder.create", ok=False, failure_kind="boom")
    assert "未知失败类型" in str(excinfo.value)
    with pytest.raises(ValueError):
        registry.record_outcome("builtin.reminder.create", ok=True, failure_kind="boom")
    assert registry.health("builtin.reminder.create")["builtin.reminder.create"].consecutive_failures == 0


def test_health_is_process_memory_and_resets_on_restart():
    first = _registry_with_builtins()
    first.record_outcome("builtin.reminder.create", ok=False, failure_kind="transient")
    assert first.health("builtin.reminder.create")["builtin.reminder.create"].consecutive_failures == 1
    restarted = _registry_with_builtins()
    health = restarted.health("builtin.reminder.create")["builtin.reminder.create"]
    assert health.consecutive_failures == 0
    assert health.failure_rate_window == 0.0
    assert health.last_failure_at is None


def test_binding_keeps_declared_schema():
    registry = ToolRegistry()
    registry.register(definition(input_schema=reminder_create_schema()))
    binding = registry.resolve("builtin.reminder.create")
    assert binding.definition.input_schema.parameters[0].name == "content"
