"""TOOL-001：工具域值对象与纯函数（architecture.md §5 / TOOL-001 §6）。"""

import ast
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings._shared import SettingsError
from app.models.action import GATE_REASONS, ActionIntent
from app.models import tool as tool_model
from app.models.tool import (
    PERMISSION_LEVELS,
    TOOL_EFFECT_KINDS,
    TOOL_EXECUTION_STATUSES,
    TOOL_FAILURE_KINDS,
    TOOL_LIFECYCLES,
    TOOL_LIFECYCLE_VALUES,
    TOOL_NAMESPACES,
    PermissionProfile,
    ToolBinding,
    ToolDefinition,
    ToolEffect,
    ToolExecution,
    ToolHealth,
    ToolInvocation,
    ToolObservation,
    ToolParameter,
    ToolResult,
    ToolSchema,
    ToolSurface,
    namespace_permission_floor,
    permission_level_rank,
    resolve_permission_level,
    transition_tool_lifecycle,
)

LIFECYCLE_EVENTS = ("enable", "disable", "deprecate", "retire")

LEGAL_TRANSITIONS = {
    ("enabled", "disable"): "disabled",
    ("enabled", "deprecate"): "deprecated",
    ("disabled", "enable"): "enabled",
    ("disabled", "deprecate"): "deprecated",
    ("deprecated", "retire"): "removed",
}

FORBIDDEN_MODEL_IMPORTS = ("app.repositories", "app.services", "app.application")


def _definition(**overrides):
    payload = {
        "id": "builtin.reminder.create",
        "name": "创建提醒",
        "description": "为用户创建一条提醒",
        "namespace": "builtin",
        "capability": "reminder",
        "action": "create",
        "input_schema": ToolSchema(),
        "permission": PermissionProfile(level="normal"),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


ROUND_TRIP_SAMPLES = (
    ToolParameter(
        name="content",
        type="string",
        required=True,
        description="提醒内容",
        min_length=1,
        max_length=140,
        source_hint="user_message",
    ),
    ToolSchema(
        parameters=[ToolParameter(name="content", type="string", required=True)],
        strict=True,
        semantic_validators=("future_datetime",),
    ),
    PermissionProfile(
        level="sensitive",
        scope=("channel:feishu",),
        confirm="first_time",
        rate_limit={"per_window": 5, "window_seconds": 60},
        requires_online=True,
        audit=True,
        scope_grant_ref="grant-1",
    ),
    _definition(),
    ToolBinding(
        tool_id="builtin.reminder.create",
        capability="reminder",
        action="create",
        definition=_definition(),
    ),
    ToolInvocation(
        tool_id="builtin.reminder.create",
        params={"content": "开会"},
        rationale="用户要求提醒",
        source="conversation",
        intent=ActionIntent(action_type="create_reminder", confidence="confident"),
        goal_id="goal-1",
        dedupe_key="dedupe-1",
        run_id="run-1",
        surface_hash="surface-1",
    ),
    ToolExecution(
        index=0,
        tool_id="builtin.reminder.create",
        capability="reminder",
        action="create",
        status="succeeded",
        params={"content": "开会"},
        permission={"level": "normal", "decision": "allow"},
        validation=None,
        result={"status": "succeeded"},
        started_at=datetime(2026, 9, 14, 8, 0, 0),
        duration_ms=12,
    ),
    ToolResult(
        status="succeeded",
        effects=[
            ToolEffect(
                kind="world",
                ref="we_1",
                detail="创建提醒世界事件",
                reversible=True,
            )
        ],
        observations={"world.event_id": "we_1"},
        failure_kind=None,
        error=None,
        usage={"duration_ms": 12, "external_calls": 0},
        redacted=["due_at"],
        raw_error=None,
    ),
    ToolEffect(kind="memory", ref="mem_1", detail="记住用户事项", reversible=False),
    ToolObservation(
        untrusted=True,
        source_tool="ext.api.weather.current",
        facts={"temperature": 20},
    ),
    ToolSurface(
        run_kind="foreground_chat",
        tool_ids=("builtin.reminder.create", "world.env.query"),
        excluded=({"tool_id": "channel.feishu.send", "reason": "requires_online"},),
        surface_hash="surface-1",
    ),
    ToolHealth(
        consecutive_failures=2,
        last_failure_at=datetime(2026, 9, 14, 9, 0, 0),
        last_success_at=datetime(2026, 9, 14, 8, 0, 0),
        failure_rate_window=0.5,
        tripped=False,
    ),
)


@pytest.mark.parametrize("sample", ROUND_TRIP_SAMPLES, ids=lambda item: type(item).__name__)
def test_value_object_serialization_round_trip(sample):
    dumped = sample.model_dump(mode="json")
    assert type(sample).model_validate(dumped) == sample


def test_round_trip_covers_twelve_value_objects():
    assert len({type(sample).__name__ for sample in ROUND_TRIP_SAMPLES}) == 12


def test_lifecycle_transition_full_matrix():
    for status in TOOL_LIFECYCLES:
        for event in LIFECYCLE_EVENTS:
            expected = LEGAL_TRANSITIONS.get((status, event))
            assert transition_tool_lifecycle(status, event) == expected, (status, event)


def test_removed_is_terminal():
    for event in LIFECYCLE_EVENTS:
        assert transition_tool_lifecycle("removed", event) is None


def test_illegal_lifecycle_transitions_return_none():
    assert transition_tool_lifecycle("enabled", "enable") is None
    assert transition_tool_lifecycle("enabled", "retire") is None
    assert transition_tool_lifecycle("disabled", "disable") is None
    assert transition_tool_lifecycle("deprecated", "enable") is None
    assert transition_tool_lifecycle("deprecated", "disable") is None
    assert transition_tool_lifecycle("deprecated", "deprecate") is None
    assert transition_tool_lifecycle("enabled", "unknown_event") is None
    assert transition_tool_lifecycle("unknown_status", "enable") is None


def test_permission_level_rank_is_strictly_ordered():
    assert [permission_level_rank(level) for level in PERMISSION_LEVELS] == [0, 1, 2, 3]


def test_namespace_permission_floors():
    assert namespace_permission_floor("builtin") == "normal"
    assert namespace_permission_floor("world") == "normal"
    assert namespace_permission_floor("channel") == "sensitive"
    assert namespace_permission_floor("ext.api") == "sensitive"
    assert namespace_permission_floor("user") == "dangerous"
    for namespace in TOOL_NAMESPACES:
        assert namespace_permission_floor(namespace) in PERMISSION_LEVELS


def test_namespace_permission_floor_rejects_unknown_namespace():
    with pytest.raises(SettingsError) as excinfo:
        namespace_permission_floor("thirdparty")
    assert "thirdparty" in str(excinfo.value)


def test_resolve_permission_level_passes_when_at_or_above_floor():
    assert resolve_permission_level("normal", "builtin", None) == "normal"
    assert resolve_permission_level("dangerous", "builtin", None) == "dangerous"
    assert resolve_permission_level("sensitive", "channel", None) == "sensitive"
    assert resolve_permission_level("dangerous", "user", None) == "dangerous"


def test_resolve_permission_level_allows_override_with_reason():
    assert resolve_permission_level("normal", "channel", "评审单 X-1") == "normal"
    assert resolve_permission_level("normal", "user", "评审单 X-2") == "normal"


def test_resolve_permission_level_rejects_silent_downgrade():
    with pytest.raises(SettingsError):
        resolve_permission_level("normal", "channel", None)
    with pytest.raises(SettingsError) as excinfo:
        resolve_permission_level("safe", "user", "")
    assert "override_reason" in str(excinfo.value)


def test_e1_user_namespace_below_floor_rejected():
    with pytest.raises(SettingsError) as excinfo:
        _definition(
            id="user.note.append",
            namespace="user",
            permission=PermissionProfile(level="normal"),
        )
    assert "user" in str(excinfo.value)


def test_e2_user_namespace_below_floor_with_override_reason_allowed():
    definition = _definition(
        id="user.note.append",
        namespace="user",
        permission=PermissionProfile(level="normal", override_reason="评审单 X-1"),
    )
    assert definition.permission.level == "normal"
    assert definition.permission.override_reason == "评审单 X-1"


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("name", "提" * 21),
        ("description", "提" * 121),
        ("when_to_use", "提" * 81),
        ("when_not_to_use", "提" * 81),
    ],
)
def test_definition_length_budget_rejected(field_name, value):
    with pytest.raises(ValidationError):
        _definition(**{field_name: value})


def test_definition_length_budget_boundary_accepted():
    definition = _definition(
        name="提" * 20,
        description="提" * 120,
        when_to_use="提" * 80,
        when_not_to_use="提" * 80,
    )
    assert len(definition.name) == 20
    assert len(definition.description) == 120


def test_parameter_description_length_budget_rejected():
    with pytest.raises(ValidationError):
        ToolParameter(name="content", type="string", description="提" * 61)


def test_parameter_description_boundary_accepted():
    parameter = ToolParameter(name="content", type="string", description="提" * 60)
    assert len(parameter.description) == 60


@pytest.mark.parametrize(
    "bad_id",
    [
        "builtin",
        "Builtin.reminder",
        "builtin.Reminder.create",
        "builtin.reminder-create",
        "builtin.reminder create",
        "1builtin.reminder.create",
        "builtin..create",
        ".builtin.create",
        "builtin.create.",
        "builtin.a.b.c.d.e",
    ],
)
def test_e3_invalid_tool_id_rejected(bad_id):
    with pytest.raises(ValidationError):
        _definition(id=bad_id)


@pytest.mark.parametrize(
    "good_id,namespace,level",
    [
        ("builtin.reminder.create", "builtin", "normal"),
        ("world.obj.move", "world", "normal"),
        ("ext.api.weather.current", "ext.api", "sensitive"),
        ("user.note.append", "user", "dangerous"),
    ],
)
def test_legal_tool_id_accepted(good_id, namespace, level):
    definition = _definition(
        id=good_id,
        namespace=namespace,
        permission=PermissionProfile(level=level),
    )
    assert definition.id == good_id


def test_e4_irreversible_forces_audit():
    definition = _definition(
        side_effects=("write_world", "irreversible"),
        permission=PermissionProfile(level="normal", audit=False),
    )
    assert definition.is_irreversible() is True
    assert definition.permission.audit is True


def test_dangerous_level_forces_audit():
    definition = _definition(permission=PermissionProfile(level="dangerous", audit=False))
    assert definition.permission.audit is True


def test_e5_error_map_unknown_failure_kind_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _definition(error_map={"ValueError": "broken"})
    message = str(excinfo.value)
    assert "broken" in message
    assert "transient" in message


def test_e5_error_map_known_failure_kinds_accepted():
    definition = _definition(
        error_map={"TimeoutError": "timeout", "ValueError": "invalid"}
    )
    assert definition.error_map == {"TimeoutError": "timeout", "ValueError": "invalid"}
    for failure_kind in definition.error_map.values():
        assert failure_kind in TOOL_FAILURE_KINDS


def test_e9_output_schema_default_is_legal():
    definition = _definition()
    assert definition.output_schema is None
    result = ToolResult(status="succeeded", observations={})
    assert result.status == "succeeded"
    assert result.failure_kind is None


def test_derived_read_only_and_effective_timeout():
    assert _definition(side_effects=("read",)).is_read_only() is True
    assert _definition(side_effects=("read", "write_world")).is_read_only() is False
    assert _definition().is_read_only() is False
    assert _definition(side_effects=("read",)).effective_timeout(9.5) == 9.5
    assert _definition(timeout_seconds=3.0).effective_timeout(9.5) == 3.0


def test_json_shape_is_stable_and_carries_type_and_required():
    schema = ToolSchema(
        parameters=[
            ToolParameter(name="content", type="string", required=True),
            ToolParameter(name="due_at", type="datetime"),
        ],
        semantic_validators=("future_datetime",),
    )
    shape = schema.json_shape()
    assert shape == {
        "strict": True,
        "semantic_validators": ["future_datetime"],
        "parameters": [
            {"name": "content", "type": "string", "required": True},
            {"name": "due_at", "type": "datetime", "required": False},
        ],
    }
    assert schema.json_shape() == shape


def test_enum_value_domains():
    assert TOOL_LIFECYCLES == ("enabled", "disabled", "deprecated", "removed")
    assert TOOL_LIFECYCLE_VALUES == frozenset(TOOL_LIFECYCLES)
    assert TOOL_EXECUTION_STATUSES == (
        "succeeded",
        "failed",
        "timeout",
        "unavailable",
        "denied",
        "invalid",
        "pending_confirmation",
    )
    assert TOOL_FAILURE_KINDS == (
        "transient",
        "permanent",
        "timeout",
        "unavailable",
        "denied",
        "invalid",
    )
    assert TOOL_EFFECT_KINDS == (
        "world",
        "memory",
        "relationship",
        "note",
        "external",
    )
    assert PERMISSION_LEVELS == ("safe", "normal", "sensitive", "dangerous")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_model_layer_has_no_forbidden_layer_dependencies():
    modules = _imported_modules(Path(tool_model.__file__))
    offenders = sorted(
        module
        for module in modules
        for forbidden in FORBIDDEN_MODEL_IMPORTS
        if module == forbidden or module.startswith(forbidden + ".")
    )
    assert offenders == []


def test_gate_reasons_extended_without_removing_existing_values():
    existing = {
        "disabled",
        "ambiguous_params",
        "capability_unavailable",
        "duplicate",
        "quota_exceeded",
        "effect_already_satisfied",
        "target_not_found",
    }
    added = {"permission_denied", "invalid_params", "pending_confirmation"}
    assert added <= set(GATE_REASONS)
    assert existing <= set(GATE_REASONS)
    assert len(GATE_REASONS) == 10
    assert len(set(GATE_REASONS)) == 10
