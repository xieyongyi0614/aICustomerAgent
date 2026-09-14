"""TOOL-002：注册期七项校验（TOOL-002 §2.3 / §6，E1~E7）。"""

import pytest
from pydantic import ValidationError

from app.models import tool as tool_model
from app.models.tool import PermissionProfile, namespace_permission_floor
from app.core.settings._shared import SettingsError
from app.services.action.registry import get_capability_registry
from app.services.tool import registry as tool_registry
from app.services.tool.registry import (
    TOOL_ID_PATTERN,
    ToolRegistry,
    _validate_capability_resolvable,
    _validate_field_budget,
    _validate_id_format,
    _validate_id_unique,
    _validate_namespace,
    _validate_permission_level,
    _validate_schema_alignment,
)
from tests.v24.tool002_support import definition, parameter, raw_definition, schema

INVALID_TOOL_IDS = (
    "reminder",
    "builtin",
    "Builtin.Reminder",
    "builtin.reminder-create",
    "builtin.Reminder.create",
    "1builtin.reminder",
    "builtin..create",
    "builtin.reminder.create.extra.more",
)


class _OtherCapability:
    name = "memory"


def test_check1_id_pattern_matches_tool001_construction_pattern():
    assert TOOL_ID_PATTERN.pattern == tool_model._TOOL_ID_PATTERN.pattern
    assert TOOL_ID_PATTERN.fullmatch("builtin.reminder.create")
    assert TOOL_ID_PATTERN.fullmatch("ext.api.weather.current")


def test_check1_id_format_positive_and_negative():
    _validate_id_format(definition())
    for tool_id in INVALID_TOOL_IDS:
        with pytest.raises(ValueError) as excinfo:
            _validate_id_format(raw_definition(id=tool_id))
        assert "校验 1" in str(excinfo.value), tool_id


def test_check1_construction_layer_rejects_invalid_id():
    with pytest.raises(ValidationError):
        definition(id="reminder")


def test_check2_duplicate_id_rejected():
    registry = ToolRegistry()
    registry.register(definition())
    with pytest.raises(ValueError) as excinfo:
        registry.register(definition())
    assert "校验 2" in str(excinfo.value)
    assert "builtin.reminder.create" in str(excinfo.value)


def test_check2_id_unique_positive_and_negative():
    registered = {definition().id: definition()}
    _validate_id_unique(definition(id="builtin.reminder.cancel", action="cancel"), registered)
    with pytest.raises(ValueError) as excinfo:
        _validate_id_unique(definition(), registered)
    assert "校验 2" in str(excinfo.value)


def test_check3_namespace_whitelist_positive_and_negative():
    for namespace in tool_model.TOOL_NAMESPACES:
        _validate_namespace(raw_definition(namespace=namespace))
    with pytest.raises(ValueError) as excinfo:
        _validate_namespace(raw_definition(namespace="plugin"))
    assert "校验 3" in str(excinfo.value)
    assert "plugin" in str(excinfo.value)


def test_check3_registration_rejects_unknown_namespace():
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(raw_definition(namespace="plugin"))
    assert "校验 3" in str(excinfo.value)


def test_check4_capability_resolvable_positive_and_negative():
    _validate_capability_resolvable(definition())
    with pytest.raises(ValueError) as excinfo:
        _validate_capability_resolvable(definition(capability="ghost"))
    assert "校验 4" in str(excinfo.value)


def test_check4_rejects_action_missing_in_capability():
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(definition(action="explode"))
    assert "校验 4" in str(excinfo.value)
    assert "explode" in str(excinfo.value)


def test_check4_rejects_mismatched_capability_implementation():
    with pytest.raises(ValueError) as excinfo:
        _validate_capability_resolvable(definition(), _OtherCapability())
    assert "校验 4" in str(excinfo.value)


def test_check4_routes_through_real_capability_registry(monkeypatch):
    real_registry = get_capability_registry()
    calls: list[str] = []

    def _spy():
        calls.append("called")
        return real_registry

    monkeypatch.setattr(tool_registry, "get_capability_registry", _spy)
    assert real_registry.has("reminder", "create")
    _validate_capability_resolvable(definition())
    assert calls == ["called"]


def test_check5_schema_alignment_positive_and_negative():
    _validate_schema_alignment(definition())
    contradiction = definition(
        input_schema=schema(parameter("content", required=True))
    )
    with pytest.raises(ValueError) as excinfo:
        _validate_schema_alignment(contradiction)
    assert "校验 5" in str(excinfo.value)
    assert "due_at" in str(excinfo.value)


def test_check5_registration_rejects_missing_required_param():
    contradiction = definition(input_schema=schema(parameter("content", required=True)))
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(contradiction)
    assert "校验 5" in str(excinfo.value)


def test_check5_reports_unresolvable_binding_as_schema_failure():
    with pytest.raises(ValueError) as excinfo:
        _validate_schema_alignment(definition(capability="ghost"))
    assert "校验 5" in str(excinfo.value)


def test_check5_only_constrains_action_schema_required_subset():
    stricter = definition(
        input_schema=schema(
            parameter("content", required=True),
            parameter("due_at", "datetime", required=True),
            parameter("note", required=True, description="工具级额外必填"),
        )
    )
    _validate_schema_alignment(stricter)


def test_check6_permission_positive_and_negative():
    _validate_permission_level(definition())
    assert namespace_permission_floor("user") == "dangerous"
    user_normal = raw_definition(
        id="user.note.append",
        namespace="user",
        capability="memory",
        action="save",
        permission=PermissionProfile(level="normal"),
    )
    with pytest.raises(ValueError) as excinfo:
        _validate_permission_level(user_normal)
    assert "校验 6" in str(excinfo.value)
    assert "override_reason" in str(excinfo.value)


def test_check6_registration_rejects_user_namespace_below_floor():
    user_normal = raw_definition(
        id="user.note.append",
        namespace="user",
        capability="memory",
        action="save",
        input_schema=schema(parameter("fact", required=True)),
        permission=PermissionProfile(level="normal"),
    )
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(user_normal)
    assert "校验 6" in str(excinfo.value)


def test_check6_allows_override_reason_below_floor():
    user_with_reason = raw_definition(
        id="user.note.append",
        namespace="user",
        permission=PermissionProfile(level="normal", override_reason="用户显式授权"),
    )
    _validate_permission_level(user_with_reason)


def test_check6_construction_layer_enforces_floor():
    with pytest.raises(SettingsError):
        definition(
            id="user.note.append",
            namespace="user",
            permission=PermissionProfile(level="normal"),
        )


@pytest.mark.parametrize(
    "field_name, limit",
    (
        ("name", tool_model.TOOL_NAME_MAX_LENGTH),
        ("description", tool_model.TOOL_DESCRIPTION_MAX_LENGTH),
        ("when_to_use", tool_model.TOOL_WHEN_MAX_LENGTH),
    ),
)
def test_check7_field_budget_positive_and_negative(field_name, limit):
    _validate_field_budget(definition())
    within_budget = raw_definition(**{field_name: "长" * limit})
    _validate_field_budget(within_budget)
    over_budget = raw_definition(**{field_name: "长" * (limit + 1)})
    with pytest.raises(ValueError) as excinfo:
        _validate_field_budget(over_budget)
    assert "校验 7" in str(excinfo.value)
    assert field_name in str(excinfo.value)


def test_check7_registration_rejects_over_budget_description():
    over_budget = raw_definition(description="长" * 121)
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(over_budget)
    assert "校验 7" in str(excinfo.value)


def test_check7_construction_layer_rejects_over_budget_description():
    with pytest.raises(ValidationError):
        definition(description="长" * 121)


@pytest.mark.parametrize(
    "overrides, expected_label",
    (
        ({"id": "reminder"}, "校验 1"),
        ({"namespace": "plugin"}, "校验 3"),
        ({"capability": "ghost"}, "校验 4"),
        ({"input_schema": schema(parameter("content", required=True))}, "校验 5"),
        (
            {
                "namespace": "user",
                "permission": PermissionProfile(level="normal"),
            },
            "校验 6",
        ),
        ({"description": "长" * 121}, "校验 7"),
    ),
)
def test_registration_short_circuits_at_first_failed_check(overrides, expected_label):
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(raw_definition(**overrides))
    assert expected_label in str(excinfo.value)


def test_registration_error_carries_check_label_and_reason():
    with pytest.raises(ValueError) as excinfo:
        ToolRegistry().register(raw_definition(namespace="plugin"))
    message = str(excinfo.value)
    assert message.startswith("工具注册校验失败｜")
    assert "plugin" in message
    assert "builtin, channel, world, ext.api, user" in message


def test_unregister_then_reregister_resets_health():
    registry = ToolRegistry()
    registry.register(definition())
    registry.record_outcome("builtin.reminder.create", ok=False, failure_kind="transient")
    assert registry.health("builtin.reminder.create")["builtin.reminder.create"].consecutive_failures == 1
    registry.unregister("builtin.reminder.create")
    assert registry.get("builtin.reminder.create") is None
    assert registry.resolve("builtin.reminder.create") is None
    assert registry.health() == {}
    registry.register(definition())
    reset = registry.health("builtin.reminder.create")["builtin.reminder.create"]
    assert reset.consecutive_failures == 0
    assert reset.failure_rate_window == 0.0
    assert reset.last_failure_at is None


def test_unregister_unknown_id_is_noop():
    registry = ToolRegistry()
    registry.unregister("builtin.reminder.create")
    assert registry.list() == []


def test_registered_definition_is_preserved_verbatim():
    registry = ToolRegistry()
    declared = definition()
    registry.register(declared)
    stored = registry.get("builtin.reminder.create")
    assert stored is declared
    binding = registry.resolve("builtin.reminder.create")
    assert binding is not None
    assert binding.capability == "reminder"
    assert binding.action == "create"
    assert binding.definition is declared


def test_public_interface_is_frozen_to_documented_surface():
    public = {
        name for name in vars(ToolRegistry) if not name.startswith("_")
    }
    assert public == {
        "register",
        "unregister",
        "resolve",
        "get",
        "has",
        "list",
        "namespaces",
        "describe",
        "effective_status",
        "health",
        "record_outcome",
    }
