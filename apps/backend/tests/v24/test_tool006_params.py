"""TOOL-006 §5 Step3 / §6.1 / §6.3：自治产行动参数模板（binding 存在 / 为 None 与 E5）。"""

from datetime import timedelta

import pytest

from app.application import autonomy_engine
from app.character.asuna.action import (
    SOURCE_HINT_DEFAULT,
    build_autonomy_action_params,
    fill_declared_defaults,
)
from app.models.tool import ToolParameter, ToolSchema
from app.services.tool.registry import ToolRegistry
from tests.v24.tool006_support import (
    NOW,
    builtin_registry,
    registry_with,
    tool_definition,
)

V9_TEMPLATE = {"content": "休息一下", "due_at": (NOW + timedelta(minutes=30)).isoformat()}


@pytest.fixture
def registry_on(monkeypatch, v24_tool_env):
    v24_tool_env()
    registry = builtin_registry()
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry)
    return registry


def _schema(*parameters: ToolParameter) -> ToolSchema:
    return ToolSchema(parameters=list(parameters))


# --- §4.4 参数模板：binding 为 None 回退 V9 ------------------------------------


def test_binding_none_falls_back_to_v9_template():
    assert build_autonomy_action_params("create_reminder", NOW, None) == V9_TEMPLATE


def test_engine_params_without_tool_system_match_v9(v24_tool_env, monkeypatch):
    v24_tool_env()
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: None)
    assert autonomy_engine._params_for_autonomy_action("create_reminder", NOW) == V9_TEMPLATE


def test_action_without_template_returns_empty_params():
    assert build_autonomy_action_params("send_notification", NOW, None) == {}


# --- §4.4 参数模板：binding 存在按声明补齐 --------------------------------------


def test_binding_present_fills_declared_defaults(registry_on):
    binding = registry_on.resolve("builtin.reminder.create")
    params = build_autonomy_action_params("create_reminder", NOW, binding)
    assert params == {**V9_TEMPLATE, "importance": "normal"}


def test_engine_params_with_tool_system_fill_importance(registry_on):
    assert autonomy_engine._params_for_autonomy_action("create_reminder", NOW) == {
        **V9_TEMPLATE,
        "importance": "normal",
    }


def test_template_values_are_not_overwritten_by_defaults(monkeypatch, v24_tool_env):
    v24_tool_env()
    registry = registry_with(
        tool_definition(
            "builtin.reminder.create",
            parameters=[
                ToolParameter(
                    name="content", type="string", required=True, default="来自声明的默认值"
                ),
                ToolParameter(
                    name="due_at",
                    type="datetime",
                    required=True,
                    default="2026-01-01T00:00:00",
                ),
                ToolParameter(name="extra", type="string", default="补齐值"),
            ],
        )
    )
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: registry)
    binding = registry.resolve("builtin.reminder.create")
    params = build_autonomy_action_params("create_reminder", NOW, binding)
    assert params["content"] == "休息一下"
    assert params["due_at"] == V9_TEMPLATE["due_at"]
    assert params["extra"] == "补齐值"


def test_source_hint_default_fills_explicit_null_default():
    schema = _schema(
        ToolParameter(name="note", type="string", source_hint=SOURCE_HINT_DEFAULT),
        ToolParameter(name="reference", type="string"),
    )
    filled = fill_declared_defaults({}, schema)
    assert filled == {"note": None}
    assert "reference" not in filled


def test_user_message_source_hint_is_not_filled():
    schema = _schema(
        ToolParameter(name="object", type="string", source_hint="user_message", required=True)
    )
    assert fill_declared_defaults({}, schema) == {}


def test_fill_declared_defaults_keeps_present_keys():
    schema = _schema(ToolParameter(name="note", type="string", default="x"))
    assert fill_declared_defaults({"note": "已有"}, schema) == {"note": "已有"}


# --- E5：映射到不在工具面内的工具 -----------------------------------------------


def test_binding_none_for_tool_excluded_from_surface(monkeypatch, v24_tool_env):
    """E5：工具不在自治工具面内 → select 返回 None → 不抛错，回退 V9 固定模板。"""
    v24_tool_env()
    monkeypatch.setattr(
        autonomy_engine,
        "get_tool_registry",
        lambda: registry_with(tool_definition("channel.feishu.send", namespace="channel")),
    )
    assert autonomy_engine._autonomy_binding("send_notification", NOW) is None
    assert build_autonomy_action_params("send_notification", NOW, None) == {}


def test_binding_none_when_registry_empty(monkeypatch, v24_tool_env):
    v24_tool_env()
    monkeypatch.setattr(autonomy_engine, "get_tool_registry", lambda: ToolRegistry())
    assert autonomy_engine._autonomy_binding("create_reminder", NOW) is None
    assert autonomy_engine._params_for_autonomy_action("create_reminder", NOW) == V9_TEMPLATE


def test_binding_resolution_uses_autonomous_surface(registry_on):
    binding = autonomy_engine._autonomy_binding("query_environment", NOW)
    assert binding is not None and binding.tool_id == "world.env.query"
    assert autonomy_engine._autonomy_binding("send_notification", NOW).tool_id == (
        "builtin.notification.send"
    )


def test_params_for_autonomy_action_signature_unchanged():
    """冻结面：`_params_for_autonomy_action(action_type, now)` 形态不变（调用方不改）。"""
    import inspect

    parameters = list(inspect.signature(autonomy_engine._params_for_autonomy_action).parameters)
    assert parameters == ["action_type", "now"]


def test_binding_resolution_is_user_agnostic_and_deterministic(registry_on):
    """工具面投影不读 user_id（TOOL-004 六维规则与用户无关），故绑定解析可复现。"""
    first = autonomy_engine._autonomy_binding("create_reminder", NOW)
    second = autonomy_engine._autonomy_binding("create_reminder", NOW)
    assert (first.tool_id, first.capability, first.action) == (
        second.tool_id,
        second.capability,
        second.action,
    )
    surface = autonomy_engine.resolve_autonomy_surface("", NOW)
    assert first.tool_id in surface.tool_ids
