"""TOOL-002：内置声明与模块级单例（TOOL-002 §2.4、§4.2，E11）。"""

import ast
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.models.tool import TOOL_DESCRIPTION_MAX_LENGTH, TOOL_NAME_MAX_LENGTH, TOOL_WHEN_MAX_LENGTH
from app.services.action.registry import get_capability_registry
from app.services.tool import registry as tool_registry
from app.services.tool.registry import (
    ToolRegistry,
    get_tool_registry,
    register_builtin_tools,
)
from tests.v24.tool002_support import (
    BUILTIN_ENABLED_IDS,
    BUILTIN_TOOL_IDS,
    MAPPING_TABLE,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

FROZEN_SOURCE_HASHES: dict[str, dict[str, str]] = {
    "app/services/action/registry.py": {
        "Capability": "0d4bbd17c64cea99f38c44b89d5202dbac71ef2ee7cb75ae0c7f2d7bfa9a435a",
        "CapabilityRegistry": "b255acb1f49b1bcb2e58f0636ceb763833a31c4e5368ce2dc8e8feb2603b606e",
    },
    "app/models/action.py": {
        "ActionSchema": "48881bbf60c6811b58fc59644b0bd86a6ceb1c47bd5b7e85f18f970189ad5adc",
    },
}


def _builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def _class_source_hash(relative_path: str, class_name: str) -> str:
    source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            return hashlib.sha256(segment.encode("utf-8")).hexdigest()
    raise AssertionError(f"未找到类定义: {relative_path}::{class_name}")


def test_builtin_declarations_cover_mapping_table():
    registry = _builtin_registry()
    declared = sorted(item.id for item in registry.list())
    assert declared == list(BUILTIN_TOOL_IDS)
    assert len(BUILTIN_ENABLED_IDS) >= 9
    assert sorted(
        item.id for item in registry.list(status="enabled")
    ) == list(BUILTIN_ENABLED_IDS)


@pytest.mark.parametrize("row", MAPPING_TABLE, ids=lambda row: row["tool_id"])
def test_builtin_definition_matches_mapping_table(row):
    definition = _builtin_registry().get(row["tool_id"])
    assert definition is not None
    assert definition.capability == row["capability"]
    assert definition.action == row["action"]
    assert definition.namespace == row["namespace"]
    assert definition.permission.level == row["level"]
    assert definition.side_effects == row["side_effects"]
    assert definition.idempotency == row["idempotency"]
    assert definition.priority == row["priority"]


@pytest.mark.parametrize("row", MAPPING_TABLE, ids=lambda row: row["tool_id"])
def test_builtin_binding_resolves_to_real_capability(row):
    """TOOL-010｜`channel.feishu.send` 绑定 `channel_feishu`：该能力仅在通道可用时
    进入全局 CapabilityRegistry（默认 6 个能力不变），声明期由通道能力单例充当依据。"""
    registry = _builtin_registry()
    binding = registry.resolve(row["tool_id"])
    assert binding is not None
    assert binding.tool_id == row["tool_id"]
    capability_registry = get_capability_registry()
    if not capability_registry.has(binding.capability, binding.action):
        from app.services.tool.channel_tools import get_channel_capability

        channel = get_channel_capability()
        assert binding.capability == channel.name
        assert binding.action in channel.actions
        assert registry.effective_status(binding.tool_id) == "disabled"
        return
    action_schema = capability_registry.get(binding.capability).actions[binding.action]
    declared_required = {
        parameter.name
        for parameter in binding.definition.input_schema.parameters
        if parameter.required
    }
    assert set(action_schema.required) <= declared_required


def test_builtin_field_budgets_are_respected():
    for definition in _builtin_registry().list():
        assert len(definition.name) <= TOOL_NAME_MAX_LENGTH, definition.id
        assert len(definition.description) <= TOOL_DESCRIPTION_MAX_LENGTH, definition.id
        assert len(definition.when_to_use) <= TOOL_WHEN_MAX_LENGTH, definition.id


def test_builtin_declarations_do_not_touch_capability_implementations():
    registry = get_capability_registry()
    assert {
        entry["name"]: {
            action: schema["required"] for action, schema in entry["actions"].items()
        }
        for entry in registry.describe()
    } == {
        "reminder": {"create": ["content", "due_at"], "cancel": ["target"]},
        "memory": {"save": ["fact"]},
        "world_action": {
            "create": ["object"],
            "move": ["object", "location"],
            "use": ["object"],
        },
        "environment_query": {"query": []},
        "search": {"query": ["query"]},
        "notification": {"send": ["content"]},
    }


def test_channel_placeholder_is_disabled_and_hidden_from_describe():
    registry = _builtin_registry()
    definition = registry.get("channel.feishu.send")
    assert definition.status == "disabled"
    assert registry.effective_status("channel.feishu.send") == "disabled"
    assert registry.has("channel.feishu.send") is False
    assert "channel.feishu.send" not in [item.tool_id for item in registry.describe()]
    assert registry.namespaces()["channel"].enabled_count == 0


def test_read_only_tools_carry_override_reason_for_namespace_floor():
    registry = _builtin_registry()
    for tool_id in ("world.env.query", "builtin.search.query"):
        definition = registry.get(tool_id)
        assert definition.permission.level == "safe"
        assert definition.permission.override_reason
        assert definition.is_read_only()


def test_describe_snapshot_is_stable_across_builds():
    payloads = [
        json.dumps(
            [asdict(descriptor) for descriptor in _builtin_registry().describe()],
            ensure_ascii=False,
        )
        for _ in range(3)
    ]
    assert len(set(payloads)) == 1


def test_get_tool_registry_returns_none_when_master_flag_off(v24_tool_env, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        tool_registry, "register_builtin_tools", lambda registry: calls.append("built")
    )
    v24_tool_env(v24_tool_system_enabled=False)
    assert get_settings().v24_tool_system_enabled is False
    assert get_tool_registry() is None
    assert calls == []


def test_get_tool_registry_ignores_existing_instance_when_flag_off(
    v24_tool_env, monkeypatch
):
    monkeypatch.setattr(tool_registry, "_registry", ToolRegistry())
    v24_tool_env(v24_tool_system_enabled=False)
    assert get_tool_registry() is None


def test_get_tool_registry_builds_once_when_master_flag_on(v24_tool_env, monkeypatch):
    calls: list[ToolRegistry] = []
    original = tool_registry.register_builtin_tools

    def _spy(registry: ToolRegistry) -> None:
        calls.append(registry)
        original(registry)

    monkeypatch.setattr(tool_registry, "register_builtin_tools", _spy)
    v24_tool_env(v24_tool_system_enabled=True)
    first = get_tool_registry()
    second = get_tool_registry()
    assert first is not None
    assert first is second
    assert calls == [first]
    assert len(first.list()) == len(BUILTIN_TOOL_IDS)


def test_get_tool_registry_singleton_is_memoized_across_calls(v24_tool_env):
    v24_tool_env(v24_tool_system_enabled=True)
    assert get_tool_registry() is get_tool_registry()


def test_action_registry_and_action_schema_are_frozen_for_this_task():
    for relative_path, classes in FROZEN_SOURCE_HASHES.items():
        for class_name, expected in classes.items():
            assert _class_source_hash(relative_path, class_name) == expected, (
                f"{relative_path}::{class_name} 在 TOOL-002 中被改动；"
                "本任务不得修改 CapabilityRegistry / Capability / ActionSchema"
            )
