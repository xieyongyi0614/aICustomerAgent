"""Reasoning Layer（RT-008）：Reason 段的角色驱动推理。

把「情境 → 决策管线（候选 → 评估 → 风险 → 选择）→ 意图」收口到循环内的**唯一入口**，
产出 `Intention` 值对象交给 Plan（RT-009）/ Act（RT-010）。

边界（RT-008 §3.2 / §4.3）：

- **唯一决策入口**（D1）：本段只调 `decision_pipeline.run_pipeline`，零第二套候选 /
  打分 / 闸门实现——V2.1 红线「前后台同一决策代码路径」。
- **零决策数学改动**（D3）：系数 / 阈值 / tiebreak 全不动；本段只做**输入装配**。
- **段零写入**：不写 `decision_records` / `goals` / `memories`；审计仍经既有
  `observability` 链路落 `decision_records`。故 `build_stack` **只读模式**调用
  （`retire_overdue_enabled=False`，不触 `retire_overdue` 的 goals 写入）。
- **LLM 不经本段 acquire**：`run_risk_gates` 已逐候选做 Gateway 预算硬闸预检
  （`llm_gateway.acquire(..., account=False)`）。段内再 acquire 会二次判定 / 二次消耗
  run 预算 → 属行为变更，禁止。`llm_used` 由该预检结果**只读投影**得出。
- **装配失败降级不中断**：任一读面失败 → 该输入为 `None` + `ReasonDegradation`，不抛。
"""

from __future__ import annotations

import logging
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
    EVENT_DECISION_MADE,
    RuntimeEvent,
    RuntimeInput,
    SessionContext,
)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
)
from app.application.agent_runtime.profiles import ProfileSpec
from app.engines import decision as decision_pipeline
from app.services.goal import stack as goal_stack

logger = logging.getLogger(__name__)

FACT_SET_GOAL_STACK = "goal_stack"
FACT_SET_SNAPSHOT = "state_snapshot"
FACT_SET_WORLD = "world"
FACT_SET_TOOL_INSIGHTS = "tool_insights"

TRACE_STAGE = "runtime_reason"


@dataclass(frozen=True, slots=True)
class ReasonDegradation:
    fact_set: str
    error: str


@dataclass(frozen=True, slots=True)
class Intention:
    """决策管线产出（architecture §5.3 的 Reason 段产物）。

    `audit` 是候选审计只读快照（`DecisionResult.audit`），落 `decision_records` 仍走
    既有 `observability` 链路；本对象**不落表**。
    """

    intention: str | None
    goal_id: str | None
    source: str
    priority: str | None
    confidence: float | None
    llm_used: bool
    degraded: bool
    audit: Mapping[str, Any]
    decided_at: datetime
    degradations: tuple[ReasonDegradation, ...] = ()

    def degraded_fact_sets(self) -> tuple[str, ...]:
        return tuple(item.fact_set for item in self.degradations)


def build_stack(user_id: str, *, now: datetime | None = None, read_only: bool = True) -> Any:
    """目标栈读面（RT-008 §4.2）。

    `read_only=True`（默认）走只读模式：**不调** `retire_overdue`。段内零写入是硬约束，
    逾期目标的退役仍留在既有生命周期路径（RT-016 收编面），不搬进 Reason 段。
    """
    return goal_stack.evaluate_stack(
        user_id, now, retire_overdue_enabled=not read_only
    )


def capabilities_for(
    spec: ProfileSpec, *, user_id: str | None = None, now: datetime | None = None
) -> list[str] | None:
    """Profile → 决策候选能力面；只有自治 Profile 带能力候选（前后台唯一分叉之一）。

    前台候选构成只有「回复用户 + 目标栈 + 静默」，故返回 `None`（与既有
    `chat_pipeline._run_foreground_decision` 逐字一致）；自治 Profile 经
    `autonomy_engine.resolve_autonomy_surface` 解析工具面，解析失败降级为 `None`。
    """
    if spec.run_kind != RUN_KIND_AUTONOMOUS_TICK:
        return None
    from app.application import autonomy_engine

    try:
        surface = autonomy_engine.resolve_autonomy_surface(user_id, now)
    except Exception:  # noqa: BLE001 — 工具面解析失败只降级，不阻断推理
        logger.exception("自治工具面解析失败，capabilities 退化为 None")
        return None
    return None if surface is None else list(surface.tool_ids)


def _user_id(run: Any, session_context: SessionContext | None) -> str | None:
    if run is not None and getattr(run, "user_id", None):
        return run.user_id
    if session_context is not None and session_context.session_id:
        return session_context.session_id
    return None


def _character_id(session_context: SessionContext | None) -> str:
    if session_context is not None and session_context.character_id:
        return session_context.character_id
    return DEFAULT_CHARACTER_ID


def _assemble_stack(
    user_id: str | None, now: datetime, degradations: list[ReasonDegradation]
) -> Any:
    if not user_id:
        return None
    try:
        return build_stack(user_id, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("目标栈装配失败，降级为 None")
        degradations.append(
            ReasonDegradation(FACT_SET_GOAL_STACK, exc.__class__.__name__)
        )
        return None


def _assemble_snapshot(
    runtime_state: Any,
    user_id: str | None,
    character_id: str,
    now: datetime,
    degradations: list[ReasonDegradation],
) -> Any:
    if runtime_state is not None:
        return runtime_state.snapshot
    if not user_id:
        return None
    try:
        return state_manager.snapshot(user_id, character_id, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("状态快照装配失败，降级为 None")
        degradations.append(
            ReasonDegradation(FACT_SET_SNAPSHOT, exc.__class__.__name__)
        )
        return None


def _assemble_world(
    user_id: str | None, degradations: list[ReasonDegradation]
) -> tuple[Any, dict | None]:
    if not user_id:
        return None, None
    try:
        facts = world_engine.collect_facts(user_id) or {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("世界影响装配失败，降级为空")
        degradations.append(ReasonDegradation(FACT_SET_WORLD, exc.__class__.__name__))
        return None, None
    return facts.get("impacts"), {
        "current_block": facts.get("current_block"),
        "part_of_day": facts.get("part_of_day"),
    }


def _assemble_tool_insights(
    user_id: str | None, degradations: list[ReasonDegradation]
) -> list[dict] | None:
    if not user_id:
        return None
    from app.application import autonomy_engine

    try:
        payload = autonomy_engine.collect_tool_insights(user_id) or {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("工具效能信号装配失败，降级为空")
        degradations.append(
            ReasonDegradation(FACT_SET_TOOL_INSIGHTS, exc.__class__.__name__)
        )
        return None
    return payload.get("insights") or None


def _budget_verdicts(audit: Mapping[str, Any]) -> list[tuple[dict, str]]:
    """候选 × 预算硬闸判定（`run_risk_gates` 写入的 Gateway 预检结果，只读投影）。"""
    verdicts: list[tuple[dict, str]] = []
    for candidate in audit.get("candidates") or []:
        for gate in candidate.get("gates") or []:
            if decision_pipeline.GATE_BUDGET in gate:
                verdicts.append((candidate, gate[decision_pipeline.GATE_BUDGET]))
    return verdicts


def _llm_used(audit: Mapping[str, Any]) -> bool:
    """胜出候选是否需要 LLM 且预算闸放行（silence 恒为 False）。"""
    for candidate, verdict in _budget_verdicts(audit):
        if not candidate.get("won"):
            continue
        if candidate.get("source") == "silence":
            return False
        return verdict != "rejected"
    return False


def _budget_denied(audit: Mapping[str, Any]) -> bool:
    return any(verdict == "rejected" for _candidate, verdict in _budget_verdicts(audit))


def _record_trace(trace: Any, intention: Intention, trigger_kind: str | None) -> None:
    if trace is None:
        return
    trace.record(
        TRACE_STAGE,
        0.0,
        status="degraded" if intention.degraded or intention.degradations else "ok",
        trigger_kind=trigger_kind,
        source=intention.source,
        intention=intention.intention,
        priority=intention.priority,
        llm_used=intention.llm_used,
        candidates=len(intention.audit.get("candidates") or []),
        degraded_fact_sets=list(intention.degraded_fact_sets()),
    )


def _emit_decision_made(
    intention: Intention,
    *,
    run_id: str | None,
    session_id: str | None,
    trace: Any,
) -> None:
    event_bus.emit(
        RuntimeEvent(
            event_type=EVENT_DECISION_MADE,
            run_id=run_id or "",
            session_id=session_id,
            occurred_at=intention.decided_at,
            payload={
                "source": intention.source,
                "intention": intention.intention,
                "priority": intention.priority,
                "llm_used": intention.llm_used,
                "degraded": intention.degraded,
                "candidates": len(intention.audit.get("candidates") or []),
            },
            correlation_id=run_id,
        ),
        trace,
    )


async def reason(
    runtime_input: RuntimeInput | None,
    session_context: SessionContext | None,
    observation: Any = None,
    *,
    spec: ProfileSpec,
    runtime_state: Any = None,
    chat_response_intention: str | None = None,
    chat_response_goal_id: str | None = None,
    trigger_intention: str | None = None,
    trigger_goal_id: str | None = None,
    run: Any = None,
    now: datetime | None = None,
    trace: Any = None,
) -> Intention:
    """情境 → 决策管线 → `Intention`（唯一入口，D1）。

    前后台分叉**只在候选构成**（D2）：前台传 `chat_response*` 且 `trigger_*` 置空；
    后台反之并携带自治能力面。`runtime_input` / `observation` 用于 Trace 关联（触发来源
    标记），决策管线的输入面来自状态 / 目标栈 / 世界 / 工具信号（§4.2 表）。
    """
    decided_at = (
        now
        or getattr(run, "started_at", None)
        or getattr(session_context, "started_at", None)
        or timeutil.now()
    )
    trigger_kind = getattr(observation, "kind", None) or (
        runtime_input.kind if runtime_input is not None else None
    )
    user_id = _user_id(run, session_context)
    foreground = spec.run_kind == RUN_KIND_FOREGROUND_CHAT
    degradations: list[ReasonDegradation] = []

    stack = _assemble_stack(user_id, decided_at, degradations)
    snapshot = _assemble_snapshot(
        runtime_state, user_id, _character_id(session_context), decided_at, degradations
    )
    world_impacts, world_schedule = _assemble_world(user_id, degradations)
    tool_insights = _assemble_tool_insights(user_id, degradations)
    capabilities = capabilities_for(spec, user_id=user_id, now=decided_at)

    result = decision_pipeline.run_pipeline(
        stack=stack,
        snapshot=snapshot,
        trigger_intention=None if foreground else trigger_intention,
        trigger_goal_id=None if foreground else trigger_goal_id,
        capabilities=capabilities,
        chat_response=foreground,
        chat_response_intention=chat_response_intention if foreground else None,
        chat_response_goal_id=chat_response_goal_id if foreground else None,
        run=run,
        now=decided_at,
        world_impacts=world_impacts,
        world_schedule=world_schedule,
        tool_insights=tool_insights,
    )

    winner = result.winner
    llm_used = _llm_used(result.audit)
    degraded = _budget_denied(result.audit) and not llm_used
    if degraded and run is not None:
        run.degraded = True
    intention = Intention(
        intention=result.intention,
        goal_id=None if winner is None else winner.goal_id,
        source="none" if winner is None else winner.source,
        priority=(
            None
            if winner is None
            else decision_pipeline.PRIORITY_LABELS.get(winner.priority)
        ),
        confidence=None if winner is None else winner.total,
        llm_used=llm_used,
        degraded=degraded,
        audit=result.audit,
        decided_at=decided_at,
        degradations=tuple(degradations),
    )
    _record_trace(trace, intention, trigger_kind)
    _emit_decision_made(
        intention,
        run_id=getattr(run, "run_id", None)
        or getattr(session_context, "run_id", None),
        session_id=session_context.session_id if session_context is not None else None,
        trace=trace,
    )
    return intention
