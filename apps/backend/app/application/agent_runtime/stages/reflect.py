"""Reflection Stage（RT-011）：Reflect 段（慢时钟）。

在循环内显式化 Reflect 慢时钟段：证据窗 → 触发 Reflection → 归集 `Insight`，
并与既有周期反思**幂等共存**（Q4）。

边界（RT-011 §3.2 / §4.3）：

- **Preserve**（D3）：`services/reflection/**` 全不动——三闸（confidence 校准 / 复检）、
  `Insight` 生命周期、证据窗聚合数学零差异；本段只调既有触发与执行入口。
- **幂等共存**（D2）：与周期路径共用 `triggers` 的日桶 / 额度去重键；同窗命中即跳过，
  不重复产 Insight。
- **零直写**：不写 `insights` / `reflection_runs` / `evidence_links`（落库仍经
  `reflector._persist` 单事务）。
- **慢时钟不拖垮快时钟**（D4）：后台档预算不足 → 段跳过 + `degraded`，不抛错。
- **默认关闭**（D5）：`runtime_reflect_in_loop_enabled=False`，关闭即回 V2.6.1。
- **不新增调度**（D6）：不新增 job worker / 常驻循环；反思执行仍由既有 worker 消费。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

TRACE_STAGE = "runtime_reflect"

REASON_DISABLED = "disabled"
REASON_OPTIONAL_DISABLED = "optional_stage_disabled"
REASON_NO_IDENTITY = "no_identity"
REASON_BUDGET = "budget"
REASON_DUPLICATE = "duplicate_window"
REASON_NO_EVIDENCE = "no_evidence"

DEFAULT_CHARACTER_ID = "asuna"
REFLECT_INSIGHT_SCAN_LIMIT = 50


@dataclass(frozen=True, slots=True)
class InsightRef:
    """`Insight` 的只读投影（类型不新增，§3.2）。"""

    insight_id: str
    insight_type: str
    confidence: float
    summary: str


@dataclass(frozen=True, slots=True)
class ReflectDegradation:
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReflectOutcome:
    """Reflect 段产物。

    `llm_used` 语义 = 本段是否**进入反思执行路径**（执行内的 LLM 参与由 `reflector`
    自行记账到 run 行，段内不绕过服务层直查表）。预算闸拦截时恒为 `False`。
    """

    triggered: bool
    skipped_reason: str | None
    insights: tuple[InsightRef, ...]
    llm_used: bool
    degradations: tuple[ReflectDegradation, ...] = ()

    def degraded(self) -> bool:
        return bool(self.degradations)


def reflect_enabled() -> bool:
    """总闸：`runtime_reflect_in_loop_enabled`（默认 `False`，D5）。"""
    return bool(get_settings().runtime_reflect_in_loop_enabled)


def optional_phase_enabled() -> bool:
    """可选段：`runtime_loop_optional_stages` 是否含 `reflect`（D1，复用 RT-006 解析）。"""
    from app.application.agent_runtime import loop as loop_module

    return loop_module.PHASE_REFLECT in loop_module.enabled_optional_phases()


def evidence_window_key(user_id: str, now: datetime) -> str:
    """证据窗去重键：复用 `triggers` 的日桶构造（不新造算法，§5.1）。"""
    from app.services.reflection import triggers

    return triggers.day_bucket_key(user_id, now)


def _skipped(reason: str, *, degraded: bool = False) -> ReflectOutcome:
    return ReflectOutcome(
        triggered=False,
        skipped_reason=reason,
        insights=(),
        llm_used=False,
        degradations=(ReflectDegradation(reason),) if degraded else (),
    )


def _mark_degraded(run: Any) -> None:
    if run is not None:
        run.degraded = True


def _record_trace(
    trace: Any, *, status: str, reason: str, detail: Mapping[str, Any] | None = None
) -> None:
    if trace is None:
        return
    trace.record(TRACE_STAGE, 0.0, status=status, reason=reason, **dict(detail or {}))


def _project_insights(
    user_id: str, character_id: str, since: datetime
) -> tuple[InsightRef, ...]:
    """归集本轮之后产生的 active Insight（只读面；零直查表）。

    归集口径 = `created_at >= 段起始时刻`。**不订阅** `register_insight_created_listener`：
    该 API 无单点注销，`reset_insight_created_listeners()` 会连带清掉 DEV-002 的编译触发
    订阅（全局副作用）。
    """
    from app.services.reflection import lifecycle

    try:
        insights = lifecycle.list_active_insights(
            user_id, character_id, limit=REFLECT_INSIGHT_SCAN_LIMIT
        )
    except Exception:  # noqa: BLE001 — 归集失败不影响已完成的反思
        logger.exception("Insight 归集失败，返回空投影")
        return ()
    return tuple(
        InsightRef(
            insight_id=insight.id,
            insight_type=insight.type,
            confidence=insight.confidence,
            summary=insight.statement,
        )
        for insight in insights
        if insight.created_at is not None and insight.created_at >= since
    )


async def reflect(
    *,
    action_outcome: Any = None,
    session_context: Any = None,
    run: Any = None,
    llm: Any = None,
    now: datetime | None = None,
    trace: Any = None,
) -> ReflectOutcome:
    """慢时钟 Reflect 段：门控 → 预算 → 触发 → 执行 → 归集。

    `action_outcome`（RT-010 产物）用于 Trace 关联（`action_id` / `result.status`）；
    证据窗的**选取与聚合仍完全由既有 `triggers` / `evidence` 负责**（§3.2 禁止改证据
    数学），本段不复制证据装配。`llm` 仅为签名对齐保留。
    """
    reflected_at = (
        now
        or getattr(run, "started_at", None)
        or getattr(session_context, "started_at", None)
        or datetime.now()
    )
    if not reflect_enabled():
        _record_trace(trace, status="skipped", reason=REASON_DISABLED)
        return _skipped(REASON_DISABLED)
    if not optional_phase_enabled():
        _record_trace(trace, status="skipped", reason=REASON_OPTIONAL_DISABLED)
        return _skipped(REASON_OPTIONAL_DISABLED)

    user_id = getattr(run, "user_id", None) or getattr(
        session_context, "session_id", None
    )
    if not user_id:
        _record_trace(trace, status="skipped", reason=REASON_NO_IDENTITY)
        return _skipped(REASON_NO_IDENTITY)

    character_id = getattr(session_context, "character_id", None) or DEFAULT_CHARACTER_ID
    action_id = getattr(action_outcome, "action_id", None)
    action_status = getattr(getattr(action_outcome, "result", None), "status", None)

    from app.application.agent_runtime import llm_gateway
    from app.services import life_loop_budget
    from app.services.reflection import reflector, triggers

    if life_loop_budget.is_degraded(now=reflected_at) or not llm_gateway.acquire(
        user_id, "reflection", run, now=reflected_at, account=False
    ).granted:
        _mark_degraded(run)
        _record_trace(
            trace,
            status="degraded",
            reason=REASON_BUDGET,
            detail={"action_id": action_id, "action_status": action_status},
        )
        return _skipped(REASON_BUDGET, degraded=True)

    trigger_outcome = triggers.trigger_for_user(
        user_id,
        character_id,
        triggers.TRIGGER_EVENT,
        reflected_at,
        trace,
    )
    if trigger_outcome == triggers.OUTCOME_OFF:
        _record_trace(trace, status="skipped", reason=REASON_DISABLED)
        return _skipped(REASON_DISABLED)
    if trigger_outcome != triggers.OUTCOME_QUEUED:
        reason = (
            REASON_DUPLICATE
            if trigger_outcome == triggers.OUTCOME_QUOTA
            else REASON_NO_EVIDENCE
        )
        _record_trace(
            trace,
            status="skipped",
            reason=reason,
            detail={"trigger_outcome": trigger_outcome, "action_id": action_id},
        )
        return _skipped(reason)

    try:
        processed = reflector.run_queued_reflections(reflected_at, trace)
    except Exception as exc:  # noqa: BLE001 — 慢时钟失败只降级，不中断循环
        logger.exception("反思执行异常：%s", user_id)
        _mark_degraded(run)
        _record_trace(
            trace,
            status="degraded",
            reason="executor_error",
            detail={"error": exc.__class__.__name__},
        )
        return ReflectOutcome(
            triggered=True,
            skipped_reason=None,
            insights=(),
            llm_used=False,
            degradations=(ReflectDegradation("executor_error", exc.__class__.__name__),),
        )

    insights = _project_insights(user_id, character_id, reflected_at)
    _record_trace(
        trace,
        status="ok",
        reason="reflected",
        detail={
            "processed": processed,
            "insights": len(insights),
            "action_id": action_id,
            "window_key": evidence_window_key(user_id, reflected_at),
        },
    )
    return ReflectOutcome(
        triggered=True,
        skipped_reason=None,
        insights=insights,
        llm_used=processed > 0,
    )
