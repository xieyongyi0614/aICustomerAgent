"""V2.4.0 结果归一（architecture.md §5.5 / TOOL-003 §2.2、§4.4）。

把 V9 自由 payload 的 `CapabilityResult` 归一为结构化 `ToolResult`：

- `world_event_id` / `memory_id` → `effects`（world / memory）+ `observations`（`world.event_id` /
  `memory.id`）**双写**；旧键原样保留在持久化 payload 内（兼容窗口 ≥ 1 个版本）。
- `deferred_world_op` **不进 observations**（执行细节，outbox 依赖），留在 payload。
- `failure_kind` 提升为顶层，旧位置（payload 内）保留。
- 逐工具键映射见 `TOOL_OBSERVATION_MAP`（TOOL-010：单一来源为角色资产
  `app/character/asuna/tool.py::TOOL_OBSERVATION_KEYS`）；未知 payload 键忽略（E10）。
- 敏感字段脱敏由 `ToolParameter.sensitive` 驱动，字段名记入 `redacted`（空值不脱敏，E12）。
- 归一自身异常**不抛错**：降级为 `raw_error="normalize_failed"` 并记日志。
- TOOL-010 新增两类效果：`note_id` → `ToolEffect.kind="note"`（行动 note，通知能力），
  `external_sent` → `ToolEffect.kind="external"`（外部外发，**reversible 恒为 False**，§2.3 / §9.5-6）；
  外发成功但响应缺 `external_message_id` 时 `ref` 为空字符串且**不视为失败**（E7）。
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.character.asuna.tool import TOOL_OBSERVATION_KEYS
from app.models.action import CapabilityResult
from app.models.tool import (
    TOOL_FAILURE_KIND_VALUES,
    ToolDefinition,
    ToolEffect,
    ToolResult,
)

logger = logging.getLogger(__name__)

NORMALIZE_FAILED = "normalize_failed"

REDACTED_VALUE = "***"

GENERIC_OBSERVATION_MAP: dict[str, str] = {
    "world_event_id": "world.event_id",
    "memory_id": "memory.id",
}

TOOL_OBSERVATION_MAP: dict[str, dict[str, str]] = {
    tool_id: dict(keys) for tool_id, keys in TOOL_OBSERVATION_KEYS.items()
}

NOTE_EFFECT_PAYLOAD_KEY = "note_id"

EXTERNAL_EFFECT_PAYLOAD_KEY = "external_sent"

EXTERNAL_MESSAGE_ID_PAYLOAD_KEY = "external_message_id"

EXT_API_NAMESPACE = "ext.api"

OBSERVATIONS_PAYLOAD_KEY = "observations"

UNTRUSTED_PAYLOAD_KEY = "untrusted"

UNTRUSTED_OBSERVATION_KEY = "ext.untrusted"


_STATUS_FAILURE_KINDS: dict[str, str] = {
    "timeout": "timeout",
    "unavailable": "unavailable",
    "failed": "transient",
}


@dataclass(frozen=True)
class ExecutionMeta:
    """执行元数据（architecture.md §4.4）：工具身份 + 耗时 + 已生效的敏感字段名。"""

    tool_id: str
    duration_ms: float = 0.0
    sensitive_param_names: tuple[str, ...] = ()


def redacted_param_names(defn: ToolDefinition, params: dict[str, Any]) -> tuple[str, ...]:
    """由 `ToolParameter.sensitive` 驱动的生效脱敏字段名：无内容的敏感字段不计入（E12）。"""
    names: list[str] = []
    for parameter in defn.input_schema.parameters:
        if not parameter.sensitive:
            continue
        value = params.get(parameter.name)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        names.append(parameter.name)
    return tuple(names)


def redact_params(params: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """脱敏副本：命中字段名替换为 `REDACTED_VALUE`，调用方入参不被改写。"""
    if not names:
        return dict(params)
    redacted = set(names)
    return {
        key: (REDACTED_VALUE if key in redacted else value)
        for key, value in params.items()
    }


def derive_failure_kind(raw: CapabilityResult) -> str | None:
    """失败类型：工具声明位置优先（payload.failure_kind），否则由 status 推导。"""
    payload = raw.payload if isinstance(raw.payload, dict) else {}
    declared = payload.get("failure_kind")
    if isinstance(declared, str) and declared in TOOL_FAILURE_KIND_VALUES:
        return declared
    return _STATUS_FAILURE_KINDS.get(raw.status)


def external_call_count(defn: ToolDefinition) -> int:
    return 1 if "send_external" in defn.side_effects else 0


def persisted_result(tool_result: ToolResult, raw: CapabilityResult) -> dict[str, Any]:
    """落 `steps[].result` 的形态：ToolResult 新键 + V9 `payload` 旧读键（outbox 依赖）。"""
    stored = tool_result.model_dump(mode="json")
    stored["payload"] = dict(raw.payload) if isinstance(raw.payload, dict) else {}
    return stored


def _truncate(text: Any, limit: int) -> str | None:
    if text is None:
        return None
    return str(text)[:limit]


class ObservationNormalizer:
    """`CapabilityResult` → `ToolResult`；归一异常降级不抛错。"""

    def normalize(
        self, defn: ToolDefinition, raw: CapabilityResult, meta: ExecutionMeta
    ) -> ToolResult:
        try:
            return self._normalize(defn, raw, meta)
        except Exception:
            logger.exception(
                "工具结果归一失败，降级为 %s：tool_id=%s", NORMALIZE_FAILED, meta.tool_id
            )
            return self._degraded(defn, raw, meta)

    def _normalize(
        self, defn: ToolDefinition, raw: CapabilityResult, meta: ExecutionMeta
    ) -> ToolResult:
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        usage = dict(raw.usage)
        usage["tool_id"] = meta.tool_id
        usage["external_calls"] = external_call_count(defn)
        return ToolResult(
            status=raw.status,
            effects=self._effects(defn, payload),
            observations=self._observations(defn, payload),
            failure_kind=derive_failure_kind(raw),
            error=_truncate(raw.error, 80),
            usage=usage,
            redacted=list(meta.sensitive_param_names),
            raw_error=None,
        )

    def _degraded(
        self, defn: ToolDefinition, raw: CapabilityResult, meta: ExecutionMeta
    ) -> ToolResult:
        usage = dict(raw.usage) if isinstance(raw.usage, dict) else {}
        usage["tool_id"] = meta.tool_id
        usage["external_calls"] = 0
        return ToolResult(
            status=raw.status,
            effects=[],
            observations={},
            failure_kind=None,
            error=_truncate(raw.error, 80),
            usage=usage,
            redacted=[],
            raw_error=NORMALIZE_FAILED,
        )

    def _effects(self, defn: ToolDefinition, payload: dict[str, Any]) -> list[ToolEffect]:
        reversible = not defn.is_irreversible()
        effects: list[ToolEffect] = []
        event_id = payload.get("world_event_id")
        if event_id:
            effects.append(
                ToolEffect(
                    kind="world",
                    ref=str(event_id),
                    detail=str(defn.name)[:200],
                    reversible=reversible,
                )
            )
        memory_id = payload.get("memory_id")
        if memory_id:
            effects.append(
                ToolEffect(kind="memory", ref=str(memory_id), detail="已记住", reversible=reversible)
            )
        note_id = payload.get(NOTE_EFFECT_PAYLOAD_KEY)
        if note_id:
            effects.append(
                ToolEffect(
                    kind="note",
                    ref=str(note_id),
                    detail=_truncate(payload.get("content"), 200) or str(defn.name)[:200],
                    reversible=True,
                )
            )
        if payload.get(EXTERNAL_EFFECT_PAYLOAD_KEY):
            effects.append(
                ToolEffect(
                    kind="external",
                    ref=str(payload.get(EXTERNAL_MESSAGE_ID_PAYLOAD_KEY) or ""),
                    detail=str(defn.name)[:200],
                    reversible=False,
                )
            )
        return effects

    def _observations(self, defn: ToolDefinition, payload: dict[str, Any]) -> dict[str, Any]:
        observations: dict[str, Any] = {}
        for payload_key, observation_key in GENERIC_OBSERVATION_MAP.items():
            value = payload.get(payload_key)
            if value is not None:
                observations[observation_key] = value
        for payload_key, observation_key in TOOL_OBSERVATION_MAP.get(defn.id, {}).items():
            value = payload.get(payload_key)
            if value is not None:
                observations[observation_key] = value
        if defn.namespace == EXT_API_NAMESPACE:
            observations.update(self._external_observations(payload))
        return observations

    @staticmethod
    def _external_observations(payload: dict[str, Any]) -> dict[str, Any]:
        """`ext.api.*` 的 observations 由清单 `response_map` 动态声明（tool_id 无法静态建表），
        故按约定键取用；外部内容恒打 `untrusted=True`（§9.5-10 提示注入防线）。"""
        declared = payload.get(OBSERVATIONS_PAYLOAD_KEY)
        observations = (
            {str(key): value for key, value in declared.items()}
            if isinstance(declared, dict)
            else {}
        )
        if payload.get(UNTRUSTED_PAYLOAD_KEY):
            observations[UNTRUSTED_OBSERVATION_KEY] = True
        return observations
