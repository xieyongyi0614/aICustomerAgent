"""V3.0 Agent Runtime 接口契约冻结（RT-001）。

Runtime Core 对外唯一契约面：`AgentRuntime.run` + Input / Output / Event / Error
四类契约，外加事件常量与字段冻结常量。值对象全部 `frozen` 不可变、零 IO、零 LLM、
零持久化依赖；本模块只依赖标准库、通道契约（`app.channels.base`）与 Run 触发源
枚举（`models.TRIGGER_*`）。字段冻结由 `tests/v30/test_runtime_contracts.py` 强制。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from app.application.agent_runtime.models import (
    TRIGGER_CHANNEL_MESSAGE,
    TRIGGER_TYPES,
)
from app.channels.base import ChannelIdentity

RunStatus = Literal["done", "aborted", "degraded"]
ErrorKind = Literal[
    "perception",
    "decision",
    "planning",
    "execution",
    "feedback",
    "state",
    "session",
]
LoopStage = Literal["observe", "reason", "plan", "act", "reflect", "update"]

DEFAULT_CHARACTER_ID = "asuna"

EVENT_RUN_OPENED = "RunOpened"
EVENT_STAGE_COMPLETED = "StageCompleted"
EVENT_RUN_CLOSED = "RunClosed"
EVENT_STATE_VERSION_BUMPED = "StateVersionBumped"
EVENT_OBSERVATION_RECORDED = "ObservationRecorded"
EVENT_USER_MESSAGE_RECEIVED = "UserMessageReceived"
EVENT_ACTION_EXECUTED = "ActionExecuted"
EVENT_ACTION_COMPLETED = "ActionCompleted"
EVENT_MEMORY_UPDATED = "MemoryUpdated"
EVENT_RELATIONSHIP_UPDATED = "RelationshipUpdated"
EVENT_DECISION_MADE = "DecisionMade"
"""Reason 段产出 `Intention` 的通知锚点（RT-008）。

RT-001 冻结的初始事件集不含本项；RT-008 §5.3 要求 Reason 段发出该事件，而
`RuntimeEvent.__post_init__` 对未知 `event_type` fail-closed，故同批登记（登记于
`tests/v30/test_runtime_contracts.py::EXPECTED_EVENT_TYPES`，属**契约追加**而非私改）。
"""

EVENT_TYPES: tuple[str, ...] = (
    EVENT_USER_MESSAGE_RECEIVED,
    EVENT_OBSERVATION_RECORDED,
    EVENT_RUN_OPENED,
    EVENT_STAGE_COMPLETED,
    EVENT_DECISION_MADE,
    EVENT_ACTION_EXECUTED,
    EVENT_ACTION_COMPLETED,
    EVENT_MEMORY_UPDATED,
    EVENT_RELATIONSHIP_UPDATED,
    EVENT_STATE_VERSION_BUMPED,
    EVENT_RUN_CLOSED,
)

RUNTIME_INPUT_FIELDS: tuple[str, ...] = (
    "kind",
    "source",
    "payload",
    "received_at",
    "channel_identity",
    "thread_id",
)
SESSION_CONTEXT_FIELDS: tuple[str, ...] = (
    "session_id",
    "character_id",
    "channel",
    "external_user_id",
    "thread_id",
    "trigger_type",
    "run_id",
    "started_at",
)
RUN_RESULT_FIELDS: tuple[str, ...] = (
    "run_id",
    "status",
    "intention",
    "action_result",
    "feedback",
    "trace_ref",
    "budget_account",
)
RUNTIME_EVENT_FIELDS: tuple[str, ...] = (
    "event_type",
    "run_id",
    "session_id",
    "occurred_at",
    "payload",
    "correlation_id",
)
RUNTIME_FAILURE_FIELDS: tuple[str, ...] = (
    "kind",
    "stage",
    "run_id",
    "recoverable",
    "detail",
)


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class RuntimeInput:
    """归一化触发输入（architecture §5.2）；kind 复用四类触发源。"""

    kind: str
    source: str
    payload: Mapping[str, Any]
    received_at: datetime
    channel_identity: ChannelIdentity | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in TRIGGER_TYPES:
            raise ValueError(f"未知的触发类型：{self.kind!r}")
        if not self.source or not self.source.strip():
            raise ValueError("source 不能为空")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at 必须为时区感知时间")
        if not _jsonable(self.payload):
            raise ValueError("payload 必须为 JSON 可序列化的映射")


@dataclass(frozen=True, slots=True)
class SessionContext:
    """会话载体；Run 的宿主（挂接位由 RT-002 填）。"""

    session_id: str
    character_id: str = DEFAULT_CHARACTER_ID
    channel: str | None = None
    external_user_id: str | None = None
    thread_id: str | None = None
    trigger_type: str = TRIGGER_CHANNEL_MESSAGE
    run_id: str | None = None
    started_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.session_id or not self.session_id.strip():
            raise ValueError("session_id 不能为空")


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次认知循环的终态（architecture §5.3）。

    intention / action_result / feedback 为开放槽，由 RT-008 / RT-010 / RT-012
    在同一模块内以 TypeAlias 收窄，不得改名或增删。
    """

    run_id: str
    status: RunStatus
    intention: object | None = None
    action_result: object | None = None
    feedback: object | None = None
    trace_ref: str | None = None
    budget_account: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """进程内事件（architecture §5.4）；只落 Trace，不落业务表。"""

    event_type: str
    run_id: str
    session_id: str | None
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"未知的事件类型：{self.event_type!r}")
        if not _jsonable(self.payload):
            raise ValueError("payload 必须为 JSON 可序列化的映射")


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    """错误契约（architecture §5.5）；recoverable 是唯一降级裁决位。"""

    kind: ErrorKind
    stage: str
    run_id: str
    recoverable: bool
    detail: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentRuntime(Protocol):
    """Runtime Core 对外唯一接口（architecture §5.1）。"""

    async def run(  # pylint: disable=redefined-builtin
        self, input: RuntimeInput, context: SessionContext
    ) -> RunResult:
        """驱动一次认知循环，返回该 Run 的终态。"""


def terminal_status_for(failure: RuntimeFailure) -> RunStatus:
    """唯一降级裁决：可恢复 → degraded；不可恢复 → aborted。"""
    return "degraded" if failure.recoverable else "aborted"


def contract_fields() -> dict[str, tuple[str, ...]]:
    """字段冻结表的运行时视图（供测试与评审核对）。"""
    return {
        "RuntimeInput": tuple(f.name for f in fields(RuntimeInput)),
        "SessionContext": tuple(f.name for f in fields(SessionContext)),
        "RunResult": tuple(f.name for f in fields(RunResult)),
        "RuntimeEvent": tuple(f.name for f in fields(RuntimeEvent)),
        "RuntimeFailure": tuple(f.name for f in fields(RuntimeFailure)),
    }
