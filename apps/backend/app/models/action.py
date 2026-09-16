"""V9 Action 域模型（action-model.md）。

纯数据定义与纯函数：ActionIntent / ActionPlan / ActionStep / ActionResult /
ActionEffect / Action / ActionRecord / CapabilityResult + 六态状态机 transition_action。
V2.6.0：Action 统一抽象 / ExecutionKind 映射 / ActionSource 扩展。
不绑定数据库、HTTP 与 LLM；非法状态迁移返回 None（V8 物品状态机同款纪律）。
"""

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ActionType = Literal[
    "create_reminder",
    "cancel_reminder",
    "remember_fact",
    "create_object",
    "move_object",
    "use_object",
    "query_environment",
    "query_search",
    "send_notification",
]

ACTION_TYPES: tuple[str, ...] = (
    "create_reminder",
    "cancel_reminder",
    "remember_fact",
    "create_object",
    "move_object",
    "use_object",
    "query_environment",
    "query_search",
    "send_notification",
)

ActionSource = Literal["conversation", "autonomy", "cancel", "plan", "event_driven"]

ACTION_SOURCES: tuple[str, ...] = (
    "conversation",
    "autonomy",
    "cancel",
    "plan",
    "event_driven",
)

ExecutionKind = Literal["internal", "tool", "external"]

ACTION_EXECUTION_MAP: dict[str, ExecutionKind] = {
    "create_reminder": "internal",
    "cancel_reminder": "internal",
    "remember_fact": "internal",
    "create_object": "internal",
    "move_object": "internal",
    "use_object": "internal",
    "query_environment": "tool",
    "query_search": "tool",
    "send_notification": "external",
}

ACTION_STATUS_SEMANTICS: dict[str, str] = {
    "created": "已创建未调度",
    "planned": "已排期待执行",
    "executing": "执行中",
    "succeeded": "成功终态出度0",
    "failed": "失败终态可由Manager.retry回planned受action_retry_max_attempts约束",
    "cancelled": "取消终态出度0",
}

RETRY_BACK_EDGE: tuple[str, str] = ("failed", "planned")

ActionStatus = Literal[
    "created", "planned", "executing", "succeeded", "failed", "cancelled"
]

ACTION_STATUSES: tuple[str, ...] = (
    "created",
    "planned",
    "executing",
    "succeeded",
    "failed",
    "cancelled",
)

TERMINAL_STATUSES: tuple[str, ...] = ("succeeded", "failed", "cancelled")

GateReason = Literal[
    "disabled",
    "ambiguous_params",
    "capability_unavailable",
    "duplicate",
    "quota_exceeded",
    "effect_already_satisfied",
    "target_not_found",
    "permission_denied",
    "invalid_params",
    "pending_confirmation",
]

GATE_REASONS: tuple[str, ...] = (
    "disabled",
    "ambiguous_params",
    "capability_unavailable",
    "duplicate",
    "quota_exceeded",
    "effect_already_satisfied",
    "target_not_found",
    "permission_denied",
    "invalid_params",
    "pending_confirmation",
)

FailureKind = Literal["transient", "permanent", "timeout", "unavailable"]

FAILURE_KINDS: tuple[str, ...] = ("transient", "permanent", "timeout", "unavailable")

ActionTransitionEvent = Literal[
    "gate_pass",
    "gate_reject",
    "execute_start",
    "step_all_succeeded",
    "step_retryable_failed",
    "step_permanent_failed",
    "expire",
    "cancel_requested",
]

_TRANSITIONS: dict[str, dict[str, str | None]] = {
    "created": {
        "gate_pass": "planned",
        "gate_reject": "cancelled",
        "cancel_requested": "cancelled",
    },
    "planned": {
        "execute_start": "executing",
        "expire": "cancelled",
        "cancel_requested": "cancelled",
    },
    "executing": {
        "step_all_succeeded": "succeeded",
        "step_retryable_failed": "executing",
        "step_permanent_failed": "failed",
    },
    "succeeded": {},
    "failed": {},
    "cancelled": {},
}


def transition_action(
    status: ActionStatus,
    event: ActionTransitionEvent,
    *,
    attempts_exceeded: bool = False,
) -> ActionStatus | None:
    """六态状态机纯函数（action-model.md §3 迁移表）。

    step_retryable_failed 在 attempts_exceeded=True 时迁移到 failed 终态，
    否则留在 executing（attempt+1 由调用方回填）。
    executing 状态不可被 cancel_requested 取消（等待自然结束）。
    """
    if status not in _TRANSITIONS:
        return None
    if event == "step_retryable_failed" and attempts_exceeded:
        return "failed" if status == "executing" else None
    return _TRANSITIONS[status].get(event)


def normalize_core_params(params: dict[str, Any]) -> dict[str, str]:
    """核心参数规范化：去空白、字符串化、按键排序（语序无关、内容敏感）。"""
    normalized: dict[str, str] = {}
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized[key] = " ".join(text.split())
    return normalized


def make_dedupe_key(action_type: ActionType, core_params: dict[str, Any]) -> str:
    """幂等键：sha1(类型 + 规范化核心参数)[:16]（planner.md §1.3）。"""
    normalized = normalize_core_params(core_params)
    material = action_type + "|" + "|".join(
        f"{key}={normalized[key]}" for key in sorted(normalized)
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


class ActionIntent(BaseModel):
    action_type: ActionType
    confidence: Literal["confident", "ambiguous"]
    params: dict[str, Any] = {}
    missing_params: list[str] = []
    evidence: str = ""
    dedupe_key: str = ""
    trigger_source: Literal["lexicon", "llm_assist"] = "lexicon"


class ActionStep(BaseModel):
    index: int
    capability: str
    action: str
    params: dict[str, Any] = {}
    status: Literal["pending", "executing", "succeeded", "failed", "skipped"] = "pending"
    result: dict[str, Any] | None = None


class ActionPlan(BaseModel):
    intent: ActionIntent
    goal_id: str | None = None
    steps: list[ActionStep] = []
    expires_at: datetime | None = None


class ActionEffect(BaseModel):
    kind: Literal["world", "memory", "relationship", "note"]
    ref: str
    detail: str = ""


class ActionResult(BaseModel):
    id: str = ""
    action_id: str = ""
    status: Literal["succeeded", "failed", "partial", "timeout"]
    effects: list[ActionEffect] = []
    error: str | None = None
    failure_kind: FailureKind | None = None
    output: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    observations: dict[str, Any] = {}
    created_at: datetime | None = None

    def has_memory_effect(self) -> bool:
        return any(effect.kind == "memory" for effect in self.effects)

    def has_world_effect(self) -> bool:
        return any(effect.kind == "world" for effect in self.effects)

    def has_relationship_effect(self) -> bool:
        return any(effect.kind == "relationship" for effect in self.effects)

    def dual_write_legacy_keys(self) -> dict[str, Any]:
        """V2.6.0 双写窗口：旧读键与新契约并存，供 V2.4.0 下游读取。"""
        payload = self.model_dump(mode="json")
        if self.output.get("world_event_id") is not None:
            payload["world_event_id"] = self.output["world_event_id"]
        if self.output.get("memory_id") is not None:
            payload["memory_id"] = self.output["memory_id"]
        if self.failure_kind is not None:
            payload["legacy_failure_kind"] = self.failure_kind
        return payload


class Action(BaseModel):
    id: str
    type: ActionType
    target: str | None = None
    parameters: dict[str, Any] = {}
    priority: int = 100
    status: ActionStatus = "created"
    result: ActionResult | None = None
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    executed_at: datetime | None = None
    source: ActionSource = "conversation"
    goal_id: str | None = None
    plan_step: str | None = None
    dedupe_key: str = ""
    run_id: str | None = None

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class CapabilityResult(BaseModel):
    status: Literal["succeeded", "failed", "timeout", "unavailable"]
    payload: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    error: str | None = None


class ActionSchema(BaseModel):
    required: list[str] = []
    optional: dict[str, str] = {}
    validators: dict[str, Any] = Field(default={}, exclude=True)

    def validate(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for name in self.required:
            value = params.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"缺少必需参数: {name}")
        for name, value in params.items():
            if value is None:
                continue
            validator = self.validators.get(name)
            if validator is None:
                continue
            error = validator(name, value)
            if error:
                errors.append(error)
        return errors


class ActionRecord(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    session_id: str | None = None
    source: ActionSource = "conversation"
    action_type: ActionType
    intent: dict[str, Any] = {}
    goal_id: str | None = None
    target_record_id: str | None = None
    dedupe_key: str = ""
    params: dict[str, Any] = {}
    status: ActionStatus = "created"
    gate_reason: str | None = None
    steps: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    attempt: int = 1
    priority: int = 100
    next_retry_at: datetime | None = None
    scheduled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    executed_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


ActionScheduleWhenType = Literal["immediate", "delay", "cron"]

ActionScheduleStatus = Literal["scheduled", "due", "executed", "cancelled"]

ACTION_SCHEDULE_WHEN_TYPES: tuple[str, ...] = ("immediate", "delay", "cron")

ACTION_SCHEDULE_STATUSES: tuple[str, ...] = (
    "scheduled",
    "due",
    "executed",
    "cancelled",
)


class ActionSchedule(BaseModel):
    id: str
    action_id: str
    when_type: ActionScheduleWhenType
    scheduled_at: datetime
    priority: int = 100
    status: ActionScheduleStatus = "scheduled"
    created_at: datetime | None = None
    updated_at: datetime | None = None
