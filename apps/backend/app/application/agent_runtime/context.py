"""Runtime Context Manager（RT-004）：一次认知循环的不可变运行时上下文。

四段（用户 / 世界 / 角色 / 记忆）**只读投影、每 Run 重建、Run 内可冻结、超预算裁剪**；
Context 不落表、不写回（architecture §3.1）。记忆段是 `context_builder` 产物的投影，
**禁止二次检索**（D2）；任一段失败只降级为空段，不阻断装配（D3）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core import timeutil
from app.application import world_engine
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.contracts import RuntimeInput, SessionContext
from app.core.settings import get_settings
from app.models.agent_state import AgentStateSnapshot
from app.services.conversation import context as context_builder

SEGMENT_PRIORITY: tuple[str, ...] = ("character", "user", "world", "memory")
PROTECTED_SEGMENTS: frozenset[str] = frozenset({"character", "user"})
TRIMMABLE_SEGMENTS: tuple[str, ...] = ("world", "memory")


@dataclass(frozen=True, slots=True)
class UserContext:
    conversation: Any
    channel: str | None
    external_user_id: str | None
    thread_id: str | None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    memories: tuple[Any, ...]
    insights: tuple[Any, ...]
    shared_experiences: tuple[Any, ...]
    relationship_patterns: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class CharacterContext:
    snapshot: AgentStateSnapshot
    snapshot_version: int
    versions: Mapping[str, state_manager.StateVersion]


@dataclass(frozen=True, slots=True)
class WorldContext:
    payload: Any | None


@dataclass(frozen=True, slots=True)
class ContextDegradation:
    segment: str
    error: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    total_chars: int
    used_chars: int
    truncated: bool
    dropped_segments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    session_id: str
    character_id: str
    user: UserContext | None
    memory: MemoryContext | None
    character: CharacterContext | None
    world: WorldContext | None
    budget: ContextBudget
    degradations: tuple[ContextDegradation, ...]
    time_point: datetime
    frozen: bool


def _current_input(runtime_input: RuntimeInput | None) -> str:
    if runtime_input is None:
        return ""
    return str((runtime_input.payload or {}).get("text", ""))


def _segment_chars(segment: Any) -> int:
    if segment is None:
        return 0
    try:
        return len(json.dumps(segment, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(repr(segment))


def _resolve_user_id(session_context: SessionContext, run) -> str | None:
    """解析本次装配的 `user_id`：Run 显式身份优先，其次会话载体声明。

    **绝不**用 `session_id` 兜底（RT-ALL-code-review H-4）：`session_id` 与 `user_id`
    在生产可分离，混用会读到错误主体的记忆 / 世界 / 角色状态。二者皆缺时返回 None，
    由 `assemble` 降级为空段。
    """
    return session_context.effective_user_id(getattr(run, "user_id", None))


async def _build_user_segment(
    user_id: str,
    session_context: SessionContext,
    runtime_input: RuntimeInput | None,
    trace,
    degradations: list[ContextDegradation],
) -> UserContext | None:
    try:
        conversation = await context_builder.build(
            session_context.session_id,
            user_id,
            _current_input(runtime_input),
            trace=trace,
        )
    except Exception as exc:
        degradations.append(ContextDegradation("user", exc.__class__.__name__))
        return None
    return UserContext(
        conversation=conversation,
        channel=session_context.channel,
        external_user_id=session_context.external_user_id,
        thread_id=session_context.thread_id,
    )


def _build_memory_segment(
    user: UserContext | None, degradations: list[ContextDegradation]
) -> MemoryContext | None:
    if user is None:
        return None
    conversation = user.conversation
    try:
        return MemoryContext(
            memories=tuple(conversation.memories),
            insights=tuple(conversation.insights),
            shared_experiences=tuple(conversation.shared_experiences),
            relationship_patterns=tuple(conversation.relationship_patterns),
        )
    except Exception as exc:
        degradations.append(ContextDegradation("memory", exc.__class__.__name__))
        return None


async def _build_character_segment(
    user_id: str,
    session_context: SessionContext,
    time_point: datetime,
    degradations: list[ContextDegradation],
) -> CharacterContext | None:
    try:
        agent_state = await asyncio.to_thread(
            state_manager.snapshot,
            user_id,
            session_context.character_id,
            time_point,
        )
        versions = {}
        for domain in state_manager.DOMAIN_SOURCES:
            versions[domain] = await asyncio.to_thread(
                state_manager.version,
                domain,
                user_id,
                session_context.character_id,
                time_point,
            )
    except Exception as exc:
        degradations.append(ContextDegradation("character", exc.__class__.__name__))
        return None
    return CharacterContext(
        snapshot=agent_state,
        snapshot_version=agent_state.snapshot_version,
        versions=versions,
    )


async def _build_world_segment(
    user_id: str,
    session_context: SessionContext,
    trace,
    degradations: list[ContextDegradation],
) -> WorldContext | None:
    try:
        payload = await asyncio.to_thread(
            world_engine.build_context,
            user_id,
            session_context.session_id,
            trace,
        )
    except Exception as exc:
        degradations.append(ContextDegradation("world", exc.__class__.__name__))
        return None
    return WorldContext(payload=payload)


def _apply_budget(
    segments: dict[str, Any], total: int
) -> tuple[dict[str, Any], ContextBudget]:
    chars = {name: _segment_chars(segment) for name, segment in segments.items()}
    used = sum(chars.values())
    dropped: list[str] = []
    for name in TRIMMABLE_SEGMENTS:
        if used <= total:
            break
        if name in PROTECTED_SEGMENTS or segments[name] is None:
            continue
        used -= chars[name]
        segments[name] = None
        dropped.append(name)
    budget = ContextBudget(
        total_chars=total,
        used_chars=used,
        truncated=bool(dropped),
        dropped_segments=tuple(dropped),
    )
    return segments, budget


async def assemble(
    session_context: SessionContext,
    runtime_input: RuntimeInput | None = None,
    *,
    run=None,
    now: datetime | None = None,
    trace=None,
) -> RuntimeContext:
    frozen = get_settings().runtime_context_freeze_enabled
    if frozen and run is not None:
        cached = run.data.get("runtime_context")
        if cached is not None:
            return cached

    time_point = now or getattr(run, "started_at", None) or timeutil.now()
    degradations: list[ContextDegradation] = []

    user_id = _resolve_user_id(session_context, run)
    if user_id is None:
        degradations.append(ContextDegradation("user", "unknown_user"))
        user_segment = None
        character_segment = None
        world_segment = None
    else:
        user_segment = await _build_user_segment(
            user_id, session_context, runtime_input, trace, degradations
        )
        character_segment = await _build_character_segment(
            user_id, session_context, time_point, degradations
        )
        world_segment = await _build_world_segment(
            user_id, session_context, trace, degradations
        )
    memory_segment = _build_memory_segment(user_segment, degradations)

    segments: dict[str, Any] = {
        "user": user_segment,
        "memory": memory_segment,
        "character": character_segment,
        "world": world_segment,
    }
    segments, budget = _apply_budget(
        segments, get_settings().context_total_char_budget
    )

    context = RuntimeContext(
        session_id=session_context.session_id,
        character_id=session_context.character_id,
        user=segments["user"],
        memory=segments["memory"],
        character=segments["character"],
        world=segments["world"],
        budget=budget,
        degradations=tuple(degradations),
        time_point=time_point,
        frozen=frozen,
    )
    if frozen and run is not None:
        run.data["runtime_context"] = context
    return context


def context_digest(context: RuntimeContext) -> str:
    payload = json.dumps(context, default=str, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def current(run) -> RuntimeContext | None:
    if run is None:
        return None
    return run.data.get("runtime_context")


def reset(run) -> None:
    if run is not None:
        run.data.pop("runtime_context", None)
