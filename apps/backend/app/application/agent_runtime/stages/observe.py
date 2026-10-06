"""Perception Layer（RT-007）：Observe 段的感知归一。

把四类触发增量（用户消息 / 世界事件 / 状态阈值 / 调度）归一为**唯一输入面**
`Observation`：四类事实集 + 降级记录 + 去重键 + 对齐 `run.started_at` 的时点。

边界（architecture §4 边界裁决表）：

- **只读投影**：不写 `memories` / `world_*` / `relationship_*` / `character_state` /
  `scene_state`；零新增表列。
- **零 LLM**：不触碰 `llm_gateway` / `chains` / `prompts`。
- **零二次检索**（D2）：记忆信号复用 RT-004 的召回结果，**禁止**调 `memory.retriever`。
- **失败不中断**（D5）：任一事实集读取失败 → 该集 `None` + `ObservationDegradation`，
  绝不外抛（感知失败不应中断 Run，旁路纪律）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core import timeutil
from app.application import world_engine
from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.contracts import (
    DEFAULT_CHARACTER_ID,
    EVENT_OBSERVATION_RECORDED,
    RuntimeEvent,
    RuntimeInput,
    SessionContext,
)
from app.application.agent_runtime.models import TRIGGER_CHANNEL_MESSAGE

FACT_SET_USER_INPUT = "user_input"
FACT_SET_WORLD = "world"
FACT_SET_MEMORY = "memory"
FACT_SET_CHARACTER = "character"

FACT_SETS: tuple[str, ...] = (
    FACT_SET_USER_INPUT,
    FACT_SET_WORLD,
    FACT_SET_MEMORY,
    FACT_SET_CHARACTER,
)

FACT_ATTRS: Mapping[str, str] = {
    FACT_SET_USER_INPUT: "user_input",
    FACT_SET_WORLD: "world",
    FACT_SET_MEMORY: "memory",
    FACT_SET_CHARACTER: "character",
}

TRACE_STAGE = "runtime_observe"

MEMORY_TOPIC_LIMIT = 5
MEMORY_TOPIC_MAX_CHARS = 40

_DEDUPE_BASIS_KEYS: tuple[str, ...] = ("dedupe_key", "event_id", "text")


@dataclass(frozen=True, slots=True)
class UserInputFact:
    text: str
    channel: str | None
    external_user_id: str | None
    thread_id: str | None


@dataclass(frozen=True, slots=True)
class WorldFact:
    payload: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class MemorySignalFact:
    count: int
    topics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CharacterStateFact:
    mood: str | None
    energy: float | None
    relationship: Mapping[str, Any]
    snapshot_version: int


@dataclass(frozen=True, slots=True)
class ObservationDegradation:
    fact_set: str
    error: str


@dataclass(frozen=True, slots=True)
class Observation:
    kind: str
    source: str
    dedupe_key: str
    observed_at: datetime
    user_input: UserInputFact | None
    world: WorldFact | None
    memory: MemorySignalFact | None
    character: CharacterStateFact | None
    degradations: tuple[ObservationDegradation, ...] = ()

    def degraded_fact_sets(self) -> tuple[str, ...]:
        return tuple(item.fact_set for item in self.degradations)

    def present_fact_sets(self) -> tuple[str, ...]:
        return tuple(
            name for name in FACT_SETS if getattr(self, FACT_ATTRS[name]) is not None
        )


def observation_dedupe_key(
    kind: str, source: str, runtime_input: RuntimeInput | None
) -> str:
    """去重键 `kind:source:基准`；同输入恒等（基准不含挂钟时间）。

    基准优先取 payload 的显式去重键（`dedupe_key` / `event_id`），其次消息文本，
    最后回落 `received_at`（它属于 `RuntimeInput` 本身，故仍与输入一一对应）。
    """
    if runtime_input is None:
        basis = ""
    else:
        payload = runtime_input.payload or {}
        basis = ""
        for key in _DEDUPE_BASIS_KEYS:
            value = payload.get(key)
            if value:
                basis = str(value)
                break
        if not basis:
            basis = runtime_input.received_at.isoformat()
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{source}:{digest}"


def _kind_of(
    runtime_input: RuntimeInput | None, session_context: SessionContext | None
) -> str:
    if runtime_input is not None:
        return runtime_input.kind
    if session_context is not None:
        return session_context.trigger_type
    return TRIGGER_CHANNEL_MESSAGE


def _source_of(
    runtime_input: RuntimeInput | None, session_context: SessionContext | None
) -> str:
    if runtime_input is not None and runtime_input.source.strip():
        return runtime_input.source
    if session_context is not None and session_context.channel:
        return session_context.channel
    return "runtime"


def _build_user_input_fact(
    runtime_input: RuntimeInput | None, session_context: SessionContext | None
) -> UserInputFact | None:
    """用户输入感知；无文本（后台触发）→ `None`，**不是降级**（D5）。"""
    payload = runtime_input.payload if runtime_input is not None else None
    text = str((payload or {}).get("text") or "")
    if not text.strip():
        return None
    identity = runtime_input.channel_identity if runtime_input is not None else None
    channel = (identity.channel if identity is not None else None) or (
        session_context.channel if session_context is not None else None
    )
    external_user_id = (
        identity.external_user_id if identity is not None else None
    ) or (session_context.external_user_id if session_context is not None else None)
    thread_id = (
        runtime_input.thread_id if runtime_input is not None else None
    ) or (session_context.thread_id if session_context is not None else None)
    return UserInputFact(
        text=text,
        channel=channel,
        external_user_id=external_user_id,
        thread_id=thread_id,
    )


def _build_world_fact(
    runtime_context: Any,
    session_context: SessionContext | None,
    degradations: list[ObservationDegradation],
) -> WorldFact | None:
    """世界状态感知：`runtime_context.world` 优先，缺上下文时才调只读事实包。"""
    try:
        if runtime_context is not None:
            payload = runtime_context.world.payload if runtime_context.world else None
        else:
            user_id = (
                session_context.effective_user_id()
                if session_context is not None
                else None
            )
            payload = world_engine.collect_facts(user_id) if user_id else None
    except Exception as exc:  # noqa: BLE001 — 感知失败只降级，不中断 Run（D5）
        degradations.append(
            ObservationDegradation(FACT_SET_WORLD, exc.__class__.__name__)
        )
        return None
    return WorldFact(payload=dict(payload) if payload else None)


def _build_memory_fact(
    runtime_context: Any, degradations: list[ObservationDegradation]
) -> MemorySignalFact | None:
    """记忆信号感知：只投影 RT-004 召回结果（不重排、不打分、不二次检索，D2）。"""
    if runtime_context is None or runtime_context.memory is None:
        return None
    try:
        memories = tuple(runtime_context.memory.memories)
        topics = tuple(
            str(getattr(memory, "content", "") or "")[:MEMORY_TOPIC_MAX_CHARS]
            for memory in memories[:MEMORY_TOPIC_LIMIT]
        )
    except Exception as exc:  # noqa: BLE001
        degradations.append(
            ObservationDegradation(FACT_SET_MEMORY, exc.__class__.__name__)
        )
        return None
    return MemorySignalFact(count=len(memories), topics=topics)


def _build_character_fact(
    runtime_state: Any,
    session_context: SessionContext | None,
    observed_at: datetime,
    degradations: list[ObservationDegradation],
) -> CharacterStateFact | None:
    """关系与状态感知：冻结态优先（RT-003），否则按 Run 时点取只读快照。"""
    if runtime_state is not None:
        agent_state = runtime_state.snapshot
    else:
        user_id = (
            session_context.effective_user_id() if session_context is not None else None
        )
        if not user_id:
            return None
        character_id = (
            session_context.character_id
            if session_context is not None
            else DEFAULT_CHARACTER_ID
        )
        try:
            agent_state = state_manager.snapshot(user_id, character_id, now=observed_at)
        except Exception as exc:  # noqa: BLE001
            degradations.append(
                ObservationDegradation(FACT_SET_CHARACTER, exc.__class__.__name__)
            )
            return None
    return CharacterStateFact(
        mood=agent_state.mood,
        energy=agent_state.energy,
        relationship=dict(agent_state.relationship or {}),
        snapshot_version=agent_state.snapshot_version,
    )


def _record_trace(trace: Any, observation: Observation) -> None:
    if trace is None:
        return
    trace.record(
        TRACE_STAGE,
        0.0,
        status="degraded" if observation.degradations else "ok",
        kind=observation.kind,
        source=observation.source,
        dedupe_key=observation.dedupe_key,
        degraded_fact_sets=list(observation.degraded_fact_sets()),
    )


def _emit_observation(
    observation: Observation,
    *,
    run_id: str | None,
    session_id: str | None,
    trace: Any,
) -> None:
    event_bus.emit(
        RuntimeEvent(
            event_type=EVENT_OBSERVATION_RECORDED,
            run_id=run_id or "",
            session_id=session_id,
            occurred_at=observation.observed_at,
            payload={
                "kind": observation.kind,
                "source": observation.source,
                "dedupe_key": observation.dedupe_key,
                "fact_sets": list(observation.present_fact_sets()),
                "degraded_fact_sets": list(observation.degraded_fact_sets()),
            },
            correlation_id=run_id,
        ),
        trace,
    )


def observe(
    runtime_input: RuntimeInput | None,
    session_context: SessionContext | None = None,
    *,
    runtime_context: Any = None,
    runtime_state: Any = None,
    now: datetime | None = None,
    run_id: str | None = None,
    trace: Any = None,
) -> Observation:
    """四类触发增量 → `Observation`（唯一输入面）；任一事实集失败只降级不抛错。

    `run_id` 用于 `ObservationRecorded` 的 Run 归属（默认回落 `session_context.run_id`）；
    `now` 由调用方对齐 `run.started_at`（裁决 D3）。
    """
    observed_at = now or getattr(session_context, "started_at", None) or timeutil.now()
    kind = _kind_of(runtime_input, session_context)
    source = _source_of(runtime_input, session_context)
    degradations: list[ObservationDegradation] = []

    observation = Observation(
        kind=kind,
        source=source,
        dedupe_key=observation_dedupe_key(kind, source, runtime_input),
        observed_at=observed_at,
        user_input=_build_user_input_fact(runtime_input, session_context),
        world=_build_world_fact(runtime_context, session_context, degradations),
        memory=_build_memory_fact(runtime_context, degradations),
        character=_build_character_fact(
            runtime_state, session_context, observed_at, degradations
        ),
        degradations=tuple(degradations),
    )
    _record_trace(trace, observation)
    _emit_observation(
        observation,
        run_id=run_id or getattr(session_context, "run_id", None),
        session_id=session_context.session_id if session_context is not None else None,
        trace=trace,
    )
    return observation
