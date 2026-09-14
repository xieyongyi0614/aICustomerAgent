"""TOOL-003 §6.1 / §6.2：`CapabilityResult` → `ToolResult` 归一映射表逐行（E7、E10、E12）。"""

import json

from app.models.action import CapabilityResult
from app.services.tool.normalizer import (
    GENERIC_OBSERVATION_MAP,
    NORMALIZE_FAILED,
    REDACTED_VALUE,
    TOOL_OBSERVATION_MAP,
    ExecutionMeta,
    ObservationNormalizer,
    derive_failure_kind,
    persisted_result,
    redact_params,
    redacted_param_names,
)
from tests.v24.tool002_support import definition
from tests.v24.tool003_support import notification_definition, sensitive_definition

NORMALIZER = ObservationNormalizer()


def _defn(tool_id: str):
    capability, action = {
        "builtin.reminder.create": ("reminder", "create"),
        "builtin.reminder.cancel": ("reminder", "cancel"),
        "builtin.memory.save": ("memory", "save"),
        "world.object.create": ("world_action", "create"),
        "world.object.move": ("world_action", "move"),
        "world.object.use": ("world_action", "use"),
        "world.env.query": ("environment_query", "query"),
        "builtin.search.query": ("search", "query"),
        "builtin.notification.send": ("notification", "send"),
    }[tool_id]
    return definition(id=tool_id, capability=capability, action=action)


def _meta(tool_id: str, *, duration_ms: float = 12.5, sensitive: tuple[str, ...] = ()) -> ExecutionMeta:
    return ExecutionMeta(tool_id=tool_id, duration_ms=duration_ms, sensitive_param_names=sensitive)


def test_mapping_table_covers_documented_tools():
    """TOOL-010｜映射表以 §2.2 表为准：新增 `builtin.memory.save`（memory.id 双写）、
    `builtin.notification.send`（note.created）与 `channel.feishu.send`（external.message_id）。"""
    assert set(TOOL_OBSERVATION_MAP) == {
        "builtin.reminder.create",
        "builtin.reminder.cancel",
        "builtin.memory.save",
        "world.object.create",
        "world.object.move",
        "world.object.use",
        "world.env.query",
        "builtin.search.query",
        "builtin.notification.send",
        "channel.feishu.send",
    }
    assert GENERIC_OBSERVATION_MAP == {"world_event_id": "world.event_id", "memory_id": "memory.id"}


def test_reminder_create_maps_world_event_and_due_at():
    raw = CapabilityResult(
        status="succeeded",
        payload={"world_event_id": "evt-1", "due_at": "2026-06-02T08:00:00+00:00", "failure_kind": None},
        usage={"duration_ms": 3.5},
    )
    result = NORMALIZER.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    assert result.status == "succeeded"
    assert [(effect.kind, effect.ref) for effect in result.effects] == [("world", "evt-1")]
    assert result.observations == {
        "world.event_id": "evt-1",
        "time.due_at": "2026-06-02T08:00:00+00:00",
    }
    assert result.failure_kind is None
    assert result.usage == {"duration_ms": 3.5, "tool_id": "builtin.reminder.create", "external_calls": 0}


def test_reminder_cancel_maps_cancelled_count_without_effects():
    raw = CapabilityResult(status="succeeded", payload={"cancelled": 2, "failure_kind": None})
    result = NORMALIZER.normalize(_defn("builtin.reminder.cancel"), raw, _meta("builtin.reminder.cancel"))
    assert result.effects == []
    assert result.observations == {"world.cancelled_count": 2}


def test_memory_save_maps_memory_id_double_write():
    raw = CapabilityResult(status="succeeded", payload={"memory_id": "mem-9", "failure_kind": None})
    result = NORMALIZER.normalize(_defn("builtin.memory.save"), raw, _meta("builtin.memory.save"))
    assert [(effect.kind, effect.ref) for effect in result.effects] == [("memory", "mem-9")]
    assert result.effects[0].detail == "已记住"
    assert result.observations == {"memory.id": "mem-9"}


def test_world_object_maps_object_and_location_id():
    raw = CapabilityResult(
        status="succeeded", payload={"object_id": "obj-1", "location_id": "loc-2", "failure_kind": None}
    )
    for tool_id in ("world.object.create", "world.object.move", "world.object.use"):
        result = NORMALIZER.normalize(_defn(tool_id), raw, _meta(tool_id))
        assert result.observations == {"world.object_id": "obj-1", "world.location_id": "loc-2"}


def test_env_query_maps_env_observations():
    raw = CapabilityResult(
        status="succeeded",
        payload={"weather": "clear", "part_of_day": "afternoon", "temperature_c": 24, "failure_kind": None},
    )
    result = NORMALIZER.normalize(_defn("world.env.query"), raw, _meta("world.env.query"))
    assert result.observations == {"env.weather": "clear", "env.part_of_day": "afternoon"}


def test_search_query_maps_untrusted_marker():
    raw = CapabilityResult(
        status="succeeded",
        payload={"result_count": 3, "results": ["a", "b", "c"], "untrusted": True, "failure_kind": None},
    )
    result = NORMALIZER.normalize(_defn("builtin.search.query"), raw, _meta("builtin.search.query"))
    assert result.observations == {
        "search.result_count": 3,
        "search.results": ["a", "b", "c"],
        "search.untrusted": True,
    }


def test_world_event_and_deferred_op_are_split_e7():
    raw = CapabilityResult(
        status="succeeded",
        payload={
            "world_event_id": "evt-7",
            "deferred_world_op": {"op": "create_event", "args": ["u1"]},
            "failure_kind": None,
        },
    )
    result = NORMALIZER.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    assert [(effect.kind, effect.ref) for effect in result.effects] == [("world", "evt-7")]
    assert result.observations == {"world.event_id": "evt-7"}
    stored = persisted_result(result, raw)
    assert stored["payload"]["deferred_world_op"] == {"op": "create_event", "args": ["u1"]}
    assert "deferred_world_op" not in json.dumps(stored["observations"])


def test_deferred_op_only_payload_keeps_outbox_dependency():
    raw = CapabilityResult(
        status="succeeded",
        payload={"deferred_world_op": {"op": "cancel_events_by_type"}, "failure_kind": None},
    )
    result = NORMALIZER.normalize(_defn("builtin.reminder.cancel"), raw, _meta("builtin.reminder.cancel"))
    assert result.effects == []
    assert result.observations == {}
    assert persisted_result(result, raw)["payload"]["deferred_world_op"] == {
        "op": "cancel_events_by_type"
    }


def test_unknown_payload_keys_are_ignored_e10():
    raw = CapabilityResult(
        status="succeeded",
        payload={"world_event_id": "evt-1", "hallucinated": {"a": 1}, "secret": "x", "failure_kind": None},
    )
    result = NORMALIZER.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    assert result.observations == {"world.event_id": "evt-1"}


def test_failure_kind_is_promoted_and_kept_in_old_location():
    raw = CapabilityResult(
        status="failed", payload={"failure_kind": "permanent"}, error="世界事件创建失败"
    )
    result = NORMALIZER.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    assert result.failure_kind == "permanent"
    assert persisted_result(result, raw)["payload"]["failure_kind"] == "permanent"
    assert result.error == "世界事件创建失败"


def test_failure_kind_falls_back_to_status():
    assert derive_failure_kind(CapabilityResult(status="timeout")) == "timeout"
    assert derive_failure_kind(CapabilityResult(status="unavailable")) == "unavailable"
    assert derive_failure_kind(CapabilityResult(status="failed")) == "transient"
    assert derive_failure_kind(CapabilityResult(status="succeeded")) is None
    assert (
        derive_failure_kind(CapabilityResult(status="failed", payload={"failure_kind": "bogus"}))
        == "transient"
    )


def test_error_is_truncated_to_contract_limit():
    raw = CapabilityResult(status="failed", payload={"failure_kind": "transient"}, error="x" * 500)
    result = NORMALIZER.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    assert len(result.error) == 80


def test_external_calls_reflects_send_external_side_effect():
    raw = CapabilityResult(status="succeeded", payload={"message_id": "m-1", "failure_kind": None})
    result = NORMALIZER.normalize(
        notification_definition(), raw, _meta("builtin.notification.send")
    )
    assert result.usage["external_calls"] == 1


def test_effect_is_not_reversible_for_irreversible_tool():
    defn = definition(
        id="world.object.use",
        capability="world_action",
        action="use",
        side_effects=("write_world", "irreversible"),
        namespace="world",
    )
    raw = CapabilityResult(status="succeeded", payload={"world_event_id": "evt-2", "failure_kind": None})
    result = NORMALIZER.normalize(defn, raw, _meta("world.object.use"))
    assert result.effects[0].reversible is False


def test_sensitive_names_are_recorded_and_values_redacted():
    defn = sensitive_definition()
    params = {"content": "你好", "recipient": "u-9"}
    names = redacted_param_names(defn, params)
    assert names == ("recipient",)
    result = NORMALIZER.normalize(
        defn,
        CapabilityResult(status="succeeded", payload={"message_id": "m-1", "failure_kind": None}),
        _meta("builtin.notification.send", sensitive=names),
    )
    assert result.redacted == ["recipient"]
    redacted = redact_params(params, names)
    assert redacted == {"content": "你好", "recipient": REDACTED_VALUE}
    assert params == {"content": "你好", "recipient": "u-9"}


def test_empty_sensitive_value_is_not_redacted_e12():
    defn = sensitive_definition()
    for empty in ("", "   ", None):
        params = {"content": "你好", "recipient": empty}
        assert redacted_param_names(defn, params) == ()
    params = {"content": "你好", "recipient": ""}
    result = NORMALIZER.normalize(
        defn,
        CapabilityResult(status="succeeded", payload={}, ),
        _meta("builtin.notification.send", sensitive=redacted_param_names(defn, params)),
    )
    assert result.redacted == []


def test_normalize_failure_degrades_without_raising(monkeypatch):
    normalizer = ObservationNormalizer()
    monkeypatch.setattr(
        normalizer, "_observations", lambda defn, payload: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    raw = CapabilityResult(
        status="timeout", payload={"failure_kind": "timeout"}, usage={"duration_ms": 1.0}
    )
    result = normalizer.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    assert result.raw_error == NORMALIZE_FAILED
    assert result.status == "timeout"
    assert result.observations == {}
    assert result.effects == []
    assert result.redacted == []
    assert result.usage["tool_id"] == "builtin.reminder.create"


def test_persisted_result_carries_new_keys_and_old_payload():
    raw = CapabilityResult(
        status="succeeded",
        payload={"world_event_id": "evt-1", "due_at": "2026-06-02T08:00:00", "failure_kind": None},
        usage={"duration_ms": 3.5},
    )
    result = NORMALIZER.normalize(_defn("builtin.reminder.create"), raw, _meta("builtin.reminder.create"))
    stored = persisted_result(result, raw)
    assert set(stored) == {
        "status",
        "effects",
        "observations",
        "failure_kind",
        "error",
        "usage",
        "redacted",
        "raw_error",
        "payload",
    }
    assert stored["payload"]["world_event_id"] == "evt-1"
    assert stored["observations"]["world.event_id"] == "evt-1"
    assert stored["usage"]["tool_id"] == "builtin.reminder.create"


def test_normalizer_does_not_mutate_raw_result():
    raw = CapabilityResult(status="succeeded", payload={"cancelled": 1, "failure_kind": None}, usage={})
    NORMALIZER.normalize(_defn("builtin.reminder.cancel"), raw, _meta("builtin.reminder.cancel"))
    assert raw.usage == {}
    assert raw.payload == {"cancelled": 1, "failure_kind": None}


KNOWN_CAPABILITY_PAYLOAD_KEYS = frozenset(
    {
        "world_event_id",
        "memory_id",
        "deferred_world_op",
        "failure_kind",
        "due_at",
        "cancelled",
        "object_id",
        "name",
        "location_id",
        "state",
        "quantity",
        "time",
        "weekday",
        "part_of_day",
        "weather",
        "temperature_c",
        "lighting",
        "simulated",
        "location",
        "result_count",
        "results",
        "untrusted",
        "message_id",
        "note_id",
        "note_created",
        "content",
        "external_sent",
        "external_message_id",
    }
)


def test_observation_map_rows_reference_registered_tools_and_known_payload_keys():
    from app.services.tool.registry import ToolRegistry, register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)
    for tool_id, mapping in TOOL_OBSERVATION_MAP.items():
        assert registry.get(tool_id) is not None, tool_id
        assert set(mapping) <= KNOWN_CAPABILITY_PAYLOAD_KEYS, tool_id
        assert len(set(mapping.values())) == len(mapping), tool_id


def test_redacted_param_names_ignores_non_sensitive_params():
    assert redacted_param_names(definition(), {"content": "x"}) == ()
    assert redacted_param_names(definition(), {}) == ()
    assert redacted_param_names(notification_definition(), {"content": "x", "recipient": "u-9"}) == ()
