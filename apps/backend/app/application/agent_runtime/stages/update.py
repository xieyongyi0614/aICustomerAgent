"""Update / Feedback Stage（RT-012）：Update 段的回写路由。

把 Act 与 Reflect 产物**路由回各域合法写通道**，并显式化「谁因 `ActionCompleted` 被触发、
写去哪、同步还是后台」（architecture §1.2 M2 / §6.3）。

边界（RT-012 §3.2 / §4.3）：

- **只路由不写**（D1）：一切写经各域**合法通道**（`memory.ingest` /
  `action.relationship_bridge` / `post_process` 步骤 / `deferred_world_op → outbox`）；
  本段零域表直写。
- **前台不阻塞**（D2）：前台 Run 只做 `post_process.schedule_post_process(...)` 交接即返回，
  **不 await** 后台任务完成。
- **一致性模型零改动**（D3）：跨域延迟投递仍走 `outbox_events`，世界写仍走
  `deferred_world_op` 唯一写面；本段不改 `outbox_consumer` / 该路径。
- **事件是只读投影**（D4）：`MemoryUpdated` / `RelationshipUpdated` / `StateVersionBumped`
  经 RT-005 发出，不承载写语义。
- **失败隔离**（D5）：任一通道异常 → 该 `FeedbackItem.applied=False` + Run `degraded`，
  其余通道继续。
- **不做 Development / 人格演化**（D6）：唯 Evolution Engine 编译。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

from app.core import timeutil
from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime.contracts import (
    DEFAULT_CHARACTER_ID,
    EVENT_MEMORY_UPDATED,
    EVENT_RELATIONSHIP_UPDATED,
    EVENT_STATE_VERSION_BUMPED,
    RuntimeEvent,
)
from app.application.agent_runtime.models import RUN_KIND_FOREGROUND_CHAT
from app.application.agent_runtime.profiles import ProfileSpec
from app.services.action import manager as action_manager

logger = logging.getLogger(__name__)

TRACE_STAGE = "runtime_update"

ROUTE_POST_PROCESS = "post_process.schedule"
ROUTE_MEMORY = "memory.ingest_from_action_record"
ROUTE_RELATIONSHIP = "action.relationship_bridge.deliver_action_signal"
ROUTE_OUTBOX = "outbox.deferred_world_op"

TARGET_MEMORY = "memory"
TARGET_RELATIONSHIP = "relationship"
TARGET_STATE = "state"
TARGET_WORLD = "world"

TARGET_FOR_CHANNEL: Mapping[str, str] = {
    ROUTE_POST_PROCESS: TARGET_STATE,
    ROUTE_MEMORY: TARGET_MEMORY,
    ROUTE_RELATIONSHIP: TARGET_RELATIONSHIP,
    ROUTE_OUTBOX: TARGET_WORLD,
}

TARGET_EVENT: Mapping[str, str] = {
    TARGET_MEMORY: EVENT_MEMORY_UPDATED,
    TARGET_RELATIONSHIP: EVENT_RELATIONSHIP_UPDATED,
    TARGET_STATE: EVENT_STATE_VERSION_BUMPED,
}


@dataclass(frozen=True, slots=True)
class PostProcessHandoff:
    """前台后处理的交接载荷（RT-015 收编后由前台链提供）。

    `schedule_post_process` 的实参在既有前台链里逐字固定；本段不重造它们，只做**透传**。
    """

    session_id: str
    user_id: str
    user_input: str
    ai_reply: str
    state: Any
    analysis: Any
    scene_state: Any = None
    scene_intent: Any = None
    current_turn: int = 0
    llm: Any = None
    selected_goal: Any = None
    intention: Any = None
    behavior: Any = None
    action_intent: Any = None

    def as_kwargs(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True, slots=True)
class FeedbackItem:
    target: str
    channel: str
    applied: bool
    background: bool
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Feedback:
    run_id: str
    items: tuple[FeedbackItem, ...]
    handed_off: bool
    emitted_events: tuple[str, ...]
    finished_at: datetime

    def applied_targets(self) -> tuple[str, ...]:
        return tuple(item.target for item in self.items if item.applied)

    def failed_items(self) -> tuple[FeedbackItem, ...]:
        return tuple(item for item in self.items if not item.applied)


def routes_for(spec: ProfileSpec | None, action_outcome: Any = None) -> tuple[str, ...]:
    """回写路由表（**可枚举、确定**）：Profile + 行动结果 → 目标通道清单。

    前台只交接（D2），故恒为 `(post_process.schedule,)`；后台在交接之外按行动结果追加
    记忆 / 关系 / 世界路由。Development 与人格演化**永不在表内**（D6）。
    """
    run_kind = getattr(spec, "run_kind", None)
    if run_kind == RUN_KIND_FOREGROUND_CHAT:
        return (ROUTE_POST_PROCESS,)
    routes: list[str] = [ROUTE_POST_PROCESS]
    if action_outcome is not None and getattr(action_outcome, "action_id", None):
        routes.extend((ROUTE_MEMORY, ROUTE_RELATIONSHIP, ROUTE_OUTBOX))
    return tuple(routes)


def _item(
    channel: str, *, applied: bool, background: bool, **detail: Any
) -> FeedbackItem:
    return FeedbackItem(
        target=TARGET_FOR_CHANNEL[channel],
        channel=channel,
        applied=applied,
        background=background,
        detail=detail,
    )


def _record_trace(
    trace: Any, *, status: str, reason: str, detail: Mapping[str, Any] | None = None
) -> None:
    if trace is None:
        return
    trace.record(TRACE_STAGE, 0.0, status=status, reason=reason, **dict(detail or {}))


def _load_action_record(action_id: str | None) -> Any:
    if not action_id:
        return None
    try:
        return action_manager.get_record(action_id)
    except Exception:  # noqa: BLE001 — 读取失败按记录不可得处理
        logger.exception("行动记录读取失败：%s", action_id)
        return None


def _handoff_post_process(handoff: PostProcessHandoff | None, trace: Any) -> FeedbackItem:
    """前台交接：`schedule_post_process(...)` **只调度不等待**（D2）。"""
    if handoff is None:
        return _item(
            ROUTE_POST_PROCESS,
            applied=False,
            background=True,
            reason="handoff_inputs_absent",
        )
    from app.application import post_process

    try:
        post_process.schedule_post_process(**handoff.as_kwargs(), trace=trace)
    except Exception as exc:  # noqa: BLE001 — 交接失败不阻塞回复（D2/D5）
        logger.exception("后处理交接失败：%s", handoff.session_id)
        return _item(
            ROUTE_POST_PROCESS,
            applied=False,
            background=True,
            error=exc.__class__.__name__,
        )
    return _item(ROUTE_POST_PROCESS, applied=True, background=True)


def _apply_memory(action_outcome: Any, character_id: str, trace: Any) -> FeedbackItem:
    """记忆候选摄取（R1~R8 裁决 + 幂等键 `(source_table, source_id)` 全在既有通道内）。

    §3.1 表里的「+ `action/memory_bridge`」由本通道内部覆盖：`ingest_from_action_record`
    的候选构造即 `memory_bridge.to_memory_candidates`（`ingest.py` 顶部导入），故**不重复**
    再调一次 `memory_bridge.deliver`——那会以另一套去重键产生第二条候选。
    """
    from app.services.memory import ingest

    record = _load_action_record(getattr(action_outcome, "action_id", None))
    if record is None:
        return _item(
            ROUTE_MEMORY, applied=False, background=True, error="record_not_found"
        )
    try:
        row = ingest.ingest_from_action_record(record, character_id, trace)
    except Exception as exc:  # noqa: BLE001
        logger.exception("记忆通道失败：%s", record.id)
        return _item(
            ROUTE_MEMORY, applied=False, background=True, error=exc.__class__.__name__
        )
    return _item(
        ROUTE_MEMORY,
        applied=True,
        background=True,
        action_id=record.id,
        candidate_id=getattr(row, "id", None),
    )


def _acknowledge_relationship_route(action_outcome: Any) -> FeedbackItem:
    """关系信号路由**只登记不重投**：`deliver_action_signal` 已在 Act 的
    `integrate_result` 内调用（`action_engine` 的唯一调用点之一）。

    段内再调会造成关系域**二次写**（`relationship_events` 追加 + `apply_relationship_update`
    的日影响钳制双应用），并打破 V2.5 PLAN-008 的「全仓只有既有两处导入
    `relationship_bridge`」守卫。故此处只登记路由与承接方（D1 只路由不写）。
    """
    return _item(
        ROUTE_RELATIONSHIP,
        applied=False,
        background=True,
        handled_by="act.integrate_result",
        action_id=getattr(action_outcome, "action_id", None),
    )


def _acknowledge_world_route(action_outcome: Any) -> FeedbackItem:
    """世界写路由**只登记不改写**（D3）：跨域投递已由 Act 的 `integrate_result` 经既有
    `deferred_world_op → outbox` 完成；本段不重复投递（重投虽幂等但属多余写）。"""
    return _item(
        ROUTE_OUTBOX,
        applied=False,
        background=True,
        handled_by="act.integrate_result",
        action_id=getattr(action_outcome, "action_id", None),
    )


def _emit_events(
    items: tuple[FeedbackItem, ...],
    *,
    run: Any,
    session_id: str | None,
    occurred_at: datetime,
    trace: Any,
) -> tuple[str, ...]:
    from app.application.agent_runtime import state as state_manager

    emitted: list[str] = []
    for item in items:
        event_type = TARGET_EVENT.get(item.target)
        if event_type is None:
            continue
        event = RuntimeEvent(
            event_type=event_type,
            run_id=str(getattr(run, "run_id", "") or ""),
            session_id=session_id,
            occurred_at=occurred_at,
            payload={
                "target": item.target,
                "channel": item.channel,
                "applied": item.applied,
                "background": item.background,
                "semantics": "routed",
            },
            correlation_id=getattr(run, "run_id", None),
        )
        event_bus.emit(event, trace)
        if item.applied:
            state_manager.observe(item.target, event)
        emitted.append(event_type)
    return tuple(emitted)


async def update(
    *,
    action_outcome: Any = None,
    reflect_outcome: Any = None,
    context: Any = None,
    session_context: Any = None,
    spec: ProfileSpec | None = None,
    handoff: PostProcessHandoff | None = None,
    run: Any = None,
    now: datetime | None = None,
    trace: Any = None,
) -> Feedback:
    """Act / Reflect 产物 → 各域合法写通道（循环收口段）。

    `context`（RT-004）与 `reflect_outcome`（RT-011）当前只作**上下文可用性**登记：
    场景 / 状态 / 目标的实际写入由 `post_process` 步骤在交接后完成，本段不复制其内部实现
    （§6.3 红线）。`handoff` 为 RT-015 收编后由前台链提供的交接载荷。
    """
    finished_at = (
        now
        or getattr(run, "started_at", None)
        or getattr(session_context, "started_at", None)
        or timeutil.now()
    )
    session_id = getattr(session_context, "session_id", None)
    user_id = (
        session_context.effective_user_id(getattr(run, "user_id", None))
        if session_context is not None
        else getattr(run, "user_id", None)
    )
    character_id = (
        getattr(session_context, "character_id", None) or DEFAULT_CHARACTER_ID
    )
    routes = routes_for(spec, action_outcome)
    items: list[FeedbackItem] = []
    handed_off = False
    for route in routes:
        if route == ROUTE_POST_PROCESS:
            item = _handoff_post_process(handoff, trace)
            handed_off = item.applied
        elif route == ROUTE_MEMORY:
            item = _apply_memory(action_outcome, character_id, trace)
        elif route == ROUTE_RELATIONSHIP:
            item = _acknowledge_relationship_route(action_outcome)
        else:
            item = _acknowledge_world_route(action_outcome)
        if (
            not item.applied
            and route != ROUTE_OUTBOX
            and "error" in item.detail
        ) and run is not None:
            run.degraded = True
        items.append(item)

    emitted = _emit_events(
        tuple(items),
        run=run,
        session_id=session_id,
        occurred_at=finished_at,
        trace=trace,
    )
    _record_trace(
        trace,
        status=(
            "degraded"
            if any(not item.applied and "error" in item.detail for item in items)
            else "ok"
        ),
        reason="feedback_routed",
        detail={
            "routes": list(routes),
            "applied": [item.target for item in items if item.applied],
            "handed_off": handed_off,
            "insights": len(getattr(reflect_outcome, "insights", ()) or ()),
            "context_available": context is not None,
        },
    )
    return Feedback(
        run_id=str(getattr(run, "run_id", "") or ""),
        items=tuple(items),
        handed_off=handed_off,
        emitted_events=emitted,
        finished_at=finished_at,
    )
