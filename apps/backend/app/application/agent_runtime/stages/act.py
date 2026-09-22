"""Action Coordination（RT-010）：Act 段的行动编排。

把 Action Execution（V2.6）接入循环第四段：`Intention` / `PlanValue` → 行动 → 执行
→ `ActOutcome`（含 `ActionResult`）回流，形成 Run 内**可观测的行动闭环**。

边界（RT-010 §3.2 / §4.3）：

- **唯一编排器**（D1）：行动创建 + 执行只经 `action_engine.run_action_planning`
  （内部五段：`new_record` → 六闸门 → `assemble_plan` → `execute_plan` → `integrate_result`）；
  本段零直写 `action_records` 状态列。
- **结果必产**（D2）：进入执行后，成功 / 闸门拦截 / 未绑定工具 / 超时 / 异常一律归一为
  `ActionResult`（闸门拦截与异常由本段合成，其余由记录反序列化）。
- **零重试 / 零调度**（D3）：不写 `next_retry_at` / `scheduled_at`，不调 `ActionManager.retry`；
  重试与排期归既有 `action_retry` / `action_schedules` 维护步。
- **不决策**（D6）：`intent_to_action_intent` 只做**映射**（候选 → 动作类型 + 参数），
  不做「做不做 / 做哪个」判断——那已由 Reason 段裁决。
- **不阻塞**（D5）：行动失败 / 超时 → Run `degraded`，循环继续（行动失败 ≠ Run 失败）。
- **工具治理不绕过**（D4）：工具类动作经引擎内部 `execute_plan` → `ToolExecutor` 五段短路，
  本段零直调 `Capability.execute`。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime.contracts import (
    EVENT_ACTION_COMPLETED,
    EVENT_ACTION_EXECUTED,
    RuntimeEvent,
)
from app.application.agent_runtime.models import RUN_KIND_FOREGROUND_CHAT
from app.models.action import ActionResult, ActionIntent
from app.services import character_assets
from app.services.action import result as action_result

logger = logging.getLogger(__name__)

TRACE_STAGE = "runtime_act"

REASON_NO_ACTION = "no_action_intention"
REASON_NO_IDENTITY = "no_identity"
REASON_NO_MAPPING = "no_action_mapping"
REASON_ENGINE_FAILED = "engine_failed"
REASON_PLAN_STEP = "plan_step"

SOURCE_CONVERSATION = "conversation"
SOURCE_AUTONOMY = "autonomy"
SOURCE_PLAN = "plan"

ACT_SOURCE_MAP: Mapping[str, str] = {
    "chat_response": SOURCE_CONVERSATION,
    "turn_intention": SOURCE_CONVERSATION,
    "autonomy_trigger": SOURCE_AUTONOMY,
    "goal_compile": SOURCE_AUTONOMY,
    "world_affordance": SOURCE_AUTONOMY,
    "capability": SOURCE_PLAN,
}

@dataclass(frozen=True, slots=True)
class ActOutcome:
    """Act 段产物（architecture §2.1 Act）。

    `result` 仅在**进入执行**时非空（§4.1）；被映射否决 / no-op 时 `executed=False`
    且 `result=None`（无执行即无结果，D2 的「每次执行必产」不被削弱）。
    """

    action_id: str | None
    action_type: str | None
    result: ActionResult | None
    gates: Mapping[str, Any]
    source: str
    executed: bool
    decided_at: datetime

    def failed(self) -> bool:
        return self.result is not None and self.result.status != "succeeded"


def action_source_for(intention: Any, run: Any = None) -> str:
    """意图来源 → `ActionSource`（`conversation` / `autonomy` / `plan`）。"""
    mapped = ACT_SOURCE_MAP.get(getattr(intention, "source", "") or "")
    if mapped:
        return mapped
    if getattr(run, "run_kind", None) == RUN_KIND_FOREGROUND_CHAT:
        return SOURCE_CONVERSATION
    return SOURCE_AUTONOMY


def _winning_candidate(intention: Any) -> Mapping[str, Any] | None:
    audit = getattr(intention, "audit", None) or {}
    for candidate in audit.get("candidates") or []:
        if candidate.get("won"):
            return candidate
    return None


def _action_type_for_tool(
    tool_id: str | None, *, character_id: str = character_assets.DEFAULT_CHARACTER_ID
) -> str | None:
    """tool_id → `ActionType`（反查人设 `ACTION_TOOL_MAP`，唯一映射来源）。"""
    if not tool_id:
        return None
    for action_type, tool_ids in character_assets.action_tool_map(character_id).items():
        if tool_id in tool_ids:
            return action_type
    return None


def _missing_params(
    action_type: str,
    params: Mapping[str, Any],
    *,
    character_id: str = character_assets.DEFAULT_CHARACTER_ID,
) -> list[str]:
    required = character_assets.required_params(character_id).get(action_type, ())
    return [name for name in required if not params.get(name)]


def _dedupe_key(
    goal_id: str | None,
    intention_text: str | None,
    action_type: str,
    session_id: str | None,
) -> str:
    basis = goal_id or intention_text or session_id or ""
    return f"act:{action_type}:{basis}"


def intent_to_action_intent(
    intention: Any,
    *,
    session_id: str | None,
    goal_id: str | None,
    character_id: str = character_assets.DEFAULT_CHARACTER_ID,
) -> ActionIntent | None:
    """`Intention` → `ActionIntent`（**只映射**，D6）。

    映射依据：决策管线胜出候选的 `tool_id`（反查人设 `ACTION_TOOL_MAP`）。候选未携带
    工具身份 → 返回 `None`（无行动可映射，不是失败）。参数取自候选 `params`；
    必填参数缺失时 `confidence="ambiguous"`，由引擎的既有闸门裁决（本段不替它判断）。
    """
    candidate = _winning_candidate(intention)
    if candidate is None:
        return None
    action_type = _action_type_for_tool(
        candidate.get("tool_id"), character_id=character_id
    )
    if action_type is None:
        return None
    params = dict(candidate.get("params") or {})
    missing = _missing_params(action_type, params, character_id=character_id)
    return ActionIntent(
        action_type=action_type,  # type: ignore[arg-type]
        confidence="ambiguous" if missing else "confident",
        params=params,
        missing_params=missing,
        evidence=str(getattr(intention, "intention", None) or ""),
        dedupe_key=_dedupe_key(
            goal_id or getattr(intention, "goal_id", None),
            getattr(intention, "intention", None),
            action_type,
            session_id,
        ),
        trigger_source="lexicon",
    )


def _result_from_record(record: Any, *, now: datetime) -> ActionResult:
    """记录 → `ActionResult`；未进入执行（闸门拦截 / 计划装配失败）时按 D2 合成。"""
    payload = getattr(record, "result", None)
    if isinstance(payload, dict) and payload:
        try:
            return ActionResult.model_validate(payload)
        except Exception:  # noqa: BLE001 — 反序列化失败退化为合成结果，不抛错
            logger.exception("行动结果反序列化失败，按闸门结果合成：%s", record.id)
    gate_reason = getattr(record, "gate_reason", None)
    return ActionResult(
        id=action_result.make_result_id(),
        action_id=record.id,
        status="failed",
        failure_kind=(
            "unavailable" if gate_reason == "capability_unavailable" else "permanent"
        ),
        error=str(gate_reason or getattr(record, "status", "failed"))[:120],
        metadata={
            "gate_reason": gate_reason,
            "record_status": getattr(record, "status", None),
            "source": "act_stage",
        },
        created_at=now,
    )


def _failure_result(*, action_id: str, error: str, now: datetime) -> ActionResult:
    return ActionResult(
        id=action_result.make_result_id(),
        action_id=action_id,
        status="failed",
        failure_kind="transient",
        error=error[:120],
        metadata={"source": "act_stage", "stage_error": error},
        created_at=now,
    )


def _gates_summary(record: Any) -> dict[str, Any]:
    """六闸门裁决的**只读投影**（引擎内已裁决，本段不重跑闸门）。"""
    gate_reason = getattr(record, "gate_reason", None)
    return {
        "allowed": gate_reason is None,
        "gate_reason": gate_reason,
        "status": getattr(record, "status", None),
        "attempt": getattr(record, "attempt", None),
        "steps": len(getattr(record, "steps", None) or []),
    }


def _record_trace(
    trace: Any, *, status: str, reason: str, detail: Mapping[str, Any] | None = None
) -> None:
    if trace is None:
        return
    trace.record(TRACE_STAGE, 0.0, status=status, reason=reason, **(dict(detail or {})))


def _mark_degraded(run: Any) -> None:
    if run is not None:
        run.degraded = True


def _emit(
    event_type: str,
    *,
    run: Any,
    session_id: str | None,
    occurred_at: datetime,
    payload: Mapping[str, Any],
    trace: Any,
) -> None:
    event_bus.emit(
        RuntimeEvent(
            event_type=event_type,
            run_id=str(getattr(run, "run_id", "") or ""),
            session_id=session_id,
            occurred_at=occurred_at,
            payload=dict(payload),
            correlation_id=getattr(run, "run_id", None),
        ),
        trace,
    )


def _empty_outcome(
    *, source: str, action_type: str | None, now: datetime
) -> ActOutcome:
    return ActOutcome(
        action_id=None,
        action_type=action_type,
        result=None,
        gates={},
        source=source,
        executed=False,
        decided_at=now,
    )


def _plan_step_status(payload: Mapping[str, Any]) -> str:
    """`_execute_plan_step` 返回投影 → `ActionResult.status` 值域。"""
    outcome = payload.get("outcome")
    if outcome in ("succeeded", "partial", "timeout"):
        return str(outcome)
    if payload.get("step_status") == "done":
        return "succeeded"
    return "failed"


async def _run_plan_step(
    plan_value: Any, *, run: Any, now: datetime, trace: Any
) -> tuple[ActionResult | None, str | None]:
    """计划步骤执行（既有 `life_loop._execute_plan_step` 本体，非重写）。

    同步阻塞的仓储读取（目标 / 计划记录）下放 `asyncio.to_thread`；`_execute_plan_step`
    本身是 `async def`（内部 `await bridge.execute_step`），只能 `await`。
    """
    from app.application import life_loop
    from app.core.settings import get_settings
    from app.services import goal_service

    def _load() -> tuple[Any, Any]:
        return (
            goal_service.get_goal(plan_value.goal_id),
            goal_service.get_plan(plan_value.plan_id),
        )

    goal, plan_record = await asyncio.to_thread(_load)
    if goal is None or plan_record is None:
        return None, None
    payload = await life_loop.execute_plan_step(
        goal, plan_record, now, {}, get_settings()
    )
    status = _plan_step_status(payload)
    result = action_result.from_plan_step_outcome(
        {
            "status": status,
            "error": payload.get("failure_kind") or payload.get("skip_reason"),
            "output": {"step_index": payload.get("step_index")},
        },
        action_id=str(payload.get("action_id") or ""),
    )
    return result, str(payload.get("skip_reason") or payload.get("step_status") or status)


async def act(
    intention: Any,
    *,
    plan: Any = None,
    session_context: Any = None,
    run: Any = None,
    llm: Any = None,
    now: datetime | None = None,
    trace: Any = None,
) -> ActOutcome:
    """`Intention` / `PlanValue` → `ActOutcome`（唯一编排入口）。

    分支优先级：`plan.current_step` 存在（计划驱动）→ 既有计划步骤执行路径；
    否则按 `Intention` 映射创建并执行行动。`llm` 仅为签名对齐保留——本段零 LLM 调用。
    """
    acted_at = (
        now
        or getattr(run, "started_at", None)
        or getattr(session_context, "started_at", None)
        or datetime.now()
    )
    session_id = getattr(session_context, "session_id", None)
    user_id = getattr(run, "user_id", None) or session_id
    source = action_source_for(intention, run)

    current_step = getattr(plan, "current_step", None)
    if plan is not None and current_step is not None:
        result, detail = await _run_plan_step(
            plan, run=run, now=acted_at, trace=trace
        )
        if result is not None:
            if result.status != "succeeded":
                _mark_degraded(run)
            _record_trace(
                trace,
                status="ok" if result.status == "succeeded" else "degraded",
                reason=REASON_PLAN_STEP,
                detail={"status": result.status, "detail": detail},
            )
            _emit(
                EVENT_ACTION_COMPLETED,
                run=run,
                session_id=session_id,
                occurred_at=acted_at,
                payload={
                    "action_id": result.action_id,
                    "status": result.status,
                    "source": SOURCE_PLAN,
                },
                trace=trace,
            )
            return ActOutcome(
                action_id=result.action_id or None,
                action_type=getattr(current_step, "tool_id", None),
                result=result,
                gates={"step_index": getattr(current_step, "index", None)},
                source=SOURCE_PLAN,
                executed=True,
                decided_at=acted_at,
            )

    if not user_id:
        _record_trace(trace, status="skipped", reason=REASON_NO_IDENTITY)
        return _empty_outcome(source=source, action_type=None, now=acted_at)

    if getattr(intention, "intention", None) is None and getattr(
        intention, "source", None
    ) != "chat_response":
        _record_trace(trace, status="skipped", reason=REASON_NO_ACTION)
        return _empty_outcome(source=source, action_type=None, now=acted_at)

    action_intent = intent_to_action_intent(
        intention,
        session_id=session_id,
        goal_id=getattr(intention, "goal_id", None),
        character_id=getattr(session_context, "character_id", None)
        or character_assets.DEFAULT_CHARACTER_ID,
    )
    if action_intent is None:
        _record_trace(trace, status="skipped", reason=REASON_NO_MAPPING)
        return _empty_outcome(source=source, action_type=None, now=acted_at)

    from app.application import action_engine

    _emit(
        EVENT_ACTION_EXECUTED,
        run=run,
        session_id=session_id,
        occurred_at=acted_at,
        payload={"action_type": action_intent.action_type, "source": source},
        trace=trace,
    )
    try:
        record = await action_engine.run_action_planning(
            user_id,
            action_intent,
            session_id=session_id,
            goal_id=getattr(intention, "goal_id", None),
            source=source,
        )
    except Exception as exc:  # noqa: BLE001 — 行动失败只降级，不中断循环（D5）
        logger.exception("行动编排失败：%s", action_intent.action_type)
        _mark_degraded(run)
        result = _failure_result(
            action_id="", error=exc.__class__.__name__, now=acted_at
        )
        _record_trace(
            trace,
            status="degraded",
            reason=REASON_ENGINE_FAILED,
            detail={"error": exc.__class__.__name__},
        )
        _emit(
            EVENT_ACTION_COMPLETED,
            run=run,
            session_id=session_id,
            occurred_at=acted_at,
            payload={
                "action_id": None,
                "status": result.status,
                "source": source,
            },
            trace=trace,
        )
        return ActOutcome(
            action_id=None,
            action_type=action_intent.action_type,
            result=result,
            gates={},
            source=source,
            executed=False,
            decided_at=acted_at,
        )

    result = _result_from_record(record, now=acted_at)
    executed = bool(record is not None and record.result)
    if result.status != "succeeded":
        _mark_degraded(run)
    _record_trace(
        trace,
        status="ok" if result.status == "succeeded" else "degraded",
        reason=str(getattr(record, "gate_reason", None) or result.status),
        detail={
            "action_id": getattr(record, "id", None),
            "status": result.status,
            "executed": executed,
        },
    )
    _emit(
        EVENT_ACTION_COMPLETED,
        run=run,
        session_id=session_id,
        occurred_at=acted_at,
        payload={
            "action_id": getattr(record, "id", None),
            "status": result.status,
            "source": source,
        },
        trace=trace,
    )
    return ActOutcome(
        action_id=getattr(record, "id", None),
        action_type=action_intent.action_type,
        result=result,
        gates=_gates_summary(record),
        source=source,
        executed=executed,
        decided_at=acted_at,
    )
