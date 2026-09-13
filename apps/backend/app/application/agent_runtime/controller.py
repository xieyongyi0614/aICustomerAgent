"""Run Controller / Run Recorder（AGENT-001 §5.1/§5.5/§7）。

Run 生命周期唯一管理者：open（loop_runs 建行，run_kind/profile）→
按 Profile 顺序执行阶段（步骤本体复用 life_loop 既有函数）→ close
（终态 + 成本汇总）。只调度不持有业务语义；唯一写面 = loop_runs。
"""

import asyncio
import logging
import time
from datetime import datetime

from app.application.agent_runtime import profiles, trigger_router
from app.application import agent_state_assembler
from app.application.agent_state_assembler import run_state_snapshot_stage
from app.services import goal_stack
from app.application.agent_runtime.llm_gateway import acquire
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
    TERMINAL_ABORTED,
    TERMINAL_DONE,
    RunContext,
)
from app.application.life_loop_context import memory_digest_var
from app.core.settings import get_settings
from app.repositories import llm_call_repository, loop_run_repository, outbox_repository
from app.services import life_loop_budget

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return get_settings().v21_agent_runtime_enabled


def unified_run_enabled() -> bool:
    settings = get_settings()
    return settings.v21_unified_run_enabled and settings.v21_agent_runtime_enabled


def open_run(
    user_id: str | None,
    run_kind: str,
    trigger_type: str,
    reason: str,
    now: datetime | None = None,
) -> RunContext:
    """Run Open：台账建行 + Profile 快照落库；kind 沿既有枚举（前台=chat）。"""
    now = now or datetime.now()
    kind = "chat" if run_kind == RUN_KIND_FOREGROUND_CHAT else "autonomy"
    row = loop_run_repository.create_run(
        user_id=user_id,
        kind=kind,
        reason=reason,
        trigger_type=trigger_type,
        run_kind=run_kind,
        profile=profiles.snapshot_profile(run_kind),
        now=now,
    )
    agent_state_assembler.ensure_personality_baseline(user_id)
    return RunContext(
        run_id=row.id,
        user_id=user_id,
        run_kind=run_kind,
        trigger_type=trigger_type,
        reason=reason,
        started_at=now,
    )


def open_foreground_run(user_id: str, now: datetime | None = None) -> RunContext | None:
    """前台收编入口：unified 关闭时返回 None（调用方走 v2.0.0 原路径）。"""
    if not unified_run_enabled():
        return None
    run_kind, trigger_type = trigger_router.classify_channel_message()
    return open_run(user_id, run_kind, trigger_type, "user_message", now)


def run_stage(run: RunContext, steps: list, name: str, func, *args) -> dict:
    """同步阶段执行原语（语义对齐 life_loop._record_step）。"""
    started = time.perf_counter()
    entry: dict = {"step": name}
    try:
        detail = func(*args) or {}
        entry.update(detail)
        entry.setdefault("status", "ok")
    except Exception as exc:
        logger.exception("agent run 步骤失败：%s", name)
        entry.update({"status": "error", "error": exc.__class__.__name__})
    entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    steps.append(entry)
    loop_run_repository.mark_step(run.run_id, entry)
    return entry


async def run_stage_async(
    run: RunContext, steps: list, name: str, coro_factory, critical: bool = False
) -> dict:
    """异步阶段执行原语（语义对齐 life_loop._record_step_async）。"""
    started = time.perf_counter()
    entry: dict = {"step": name}
    try:
        detail = await coro_factory()
        entry.update(detail or {})
        entry.setdefault("status", "ok")
    except Exception as exc:
        logger.exception("agent run 步骤失败：%s", name)
        entry.update({"status": "error", "error": exc.__class__.__name__})
        entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        steps.append(entry)
        loop_run_repository.mark_step(run.run_id, entry)
        if critical:
            raise
    entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    steps.append(entry)
    loop_run_repository.mark_step(run.run_id, entry)
    return entry


def append_step(run: RunContext, steps: list, entry: dict) -> None:
    entry.setdefault("duration_ms", 0.0)
    steps.append(entry)
    loop_run_repository.mark_step(run.run_id, entry)


def close_run(
    run: RunContext,
    status: str,
    steps: list | None = None,
    budget_state: dict | None = None,
    now: datetime | None = None,
) -> None:
    """Run Close：终态 + 成本汇总（窗口计数口径与 life_loop 一致）。

    steps=None（前台整链包裹，无逐阶段记账）时保留台账既有 steps。
    """
    finished = now or datetime.now()
    if budget_state is None:
        budget_state = life_loop_budget.check_daily_budget(now=finished).as_dict()
    try:
        llm_count = (
            llm_call_repository.count_calls_between(run.started_at, finished)
            if finished >= run.started_at
            else 0
        )
    except Exception:
        logger.exception("run 窗口 LLM 计数失败，按 0 记账")
        llm_count = 0
    loop_run_repository.finish_run(
        run.run_id,
        status=status,
        steps=steps,
        llm_call_count=llm_count,
        budget_state=budget_state,
        now=finished,
    )


def _autonomous_stage_runner(name: str, user_id: str, run: RunContext, now: datetime):
    """阶段名 → 既有步骤本体（Profile Registry 是唯一阶段序列来源）。

    未注册阶段名 fail-closed 抛错：注册表与实现不一致必须暴露，不得静默跳过。
    """
    from app.application import life_loop as life_loop_mod

    runners = {
        "perception": lambda: life_loop_mod._step_perception(user_id, now),
        "state_update": lambda: life_loop_mod._step_state_update(user_id, now),
        "state_snapshot": lambda: asyncio.to_thread(run_state_snapshot_stage, user_id, run),
        "goal_check": lambda: life_loop_mod._step_goal_check(user_id, now),
        "goal_stack": lambda: goal_stack.run_goal_stack_stage(user_id, run, now),
        "goal_supply": lambda: life_loop_mod._step_goal_supply(user_id, now),
        "goal_advance": lambda: life_loop_mod._step_goal_advance(user_id, now),
        "memory_retrieval": lambda: life_loop_mod._step_memory_retrieval(
            user_id, now, run.data
        ),
        "reflection_check": lambda: life_loop_mod._step_reflection_check(user_id, now),
        "world_experience": lambda: life_loop_mod._step_world_experience(user_id, now),
    }
    try:
        return runners[name]
    except KeyError as exc:
        raise ValueError(f"Profile 声明了未实现的阶段：{name}") from exc


_ASYNC_STAGES = frozenset({"goal_advance", "state_snapshot"})


async def run_autonomous_cycle(
    user_id: str,
    llm=None,
    now: datetime | None = None,
    trigger_type: str | None = None,
    reason: str | None = None,
) -> str:
    """autonomous_tick Profile：按 Profile Registry 声明的阶段序列执行。

    与 v2.0.0 _run_user_cycle 的差异仅三处：台账经 open_run 落
    run_kind/profile、decision 增加第三道 Gateway 闸、支持事件升级触发源。
    """
    from app.application.post_process import get_user_write_lock

    now = now or datetime.now()
    settings = get_settings()
    if trigger_type is None or reason is None:
        trigger_type, reason = trigger_router.classify_background_trigger(user_id, now)
    run = open_run(user_id, RUN_KIND_AUTONOMOUS_TICK, trigger_type, reason, now)
    steps: list = []
    budget = life_loop_budget.check_daily_budget(now=now)
    status = TERMINAL_DONE
    spec = profiles.get_profile(RUN_KIND_AUTONOMOUS_TICK)
    try:
        async with get_user_write_lock(user_id):
            for name in spec.stages:
                if name == "decision":
                    await _run_decision_stage(run, steps, user_id, llm, now, budget, settings)
                    continue
                runner = _autonomous_stage_runner(name, user_id, run, now)
                if name in _ASYNC_STAGES:
                    await run_stage_async(
                        run, steps, name, runner, critical=name in spec.critical
                    )
                else:
                    run_stage(run, steps, name, runner)
    except Exception as exc:
        logger.exception("agent run 用户周期中止：%s", user_id)
        status = TERMINAL_ABORTED
        steps.append(
            {"step": "abort", "status": "error", "error": exc.__class__.__name__}
        )
    finally:
        digest_token = run.data.get("digest_token")
        if digest_token is not None:
            memory_digest_var.reset(digest_token)
        agent_state_assembler.reset_run_state(run)
    close_run(run, status, steps, budget_state=budget.as_dict(), now=datetime.now())
    return status


async def _run_decision_stage(run, steps, user_id, llm, now, budget, settings) -> None:
    """decision 阶段：两道既有预算闸 → Gateway 第三道闸 → critical 执行。"""
    from app.application import life_loop as life_loop_mod

    if budget.status == life_loop_budget._STATUS_DEGRADED:
        append_step(
            run, steps,
            {"step": "decision", "status": "skipped", "skip_reason": "quota_circuit_open"},
        )
    elif life_loop_mod._cycle_llm_budget_exhausted(steps, settings):
        append_step(
            run, steps,
            {"step": "decision", "status": "skipped", "skip_reason": "step_budget"},
        )
    elif not acquire(user_id, "proactive", run, now=now).granted:
        append_step(
            run, steps,
            {"step": "decision", "status": "skipped", "skip_reason": "gateway_denied"},
        )
    else:
        await run_stage_async(
            run, steps, "decision",
            lambda: life_loop_mod._step_decision(user_id, llm, now),
            critical=True,
        )


async def run_event_pregate(llm=None, now: datetime | None = None) -> int:
    """event_driven Profile（Flow C）：白名单事件升级为完整 Run，其余 0 消耗。"""
    settings = get_settings()
    if not settings.v21_event_escalation_types:
        return 0
    now = now or datetime.now()
    escalated = 0
    for row in outbox_repository.list_pending(now=now, limit=20):
        if not trigger_router.evaluate_event_escalation(row.event_type):
            continue
        user_id = (row.payload or {}).get("user_id")
        if not user_id:
            continue
        run = open_run(
            user_id, RUN_KIND_EVENT_DRIVEN, "world_event", f"event:{row.event_type}", now
        )
        steps: list = []
        try:
            await run_autonomous_cycle(
                user_id, llm=llm, now=now,
                trigger_type="world_event", reason=f"event:{row.event_type}",
            )
            append_step(run, steps, {"step": "event_pregate", "status": "ok", "escalated": True})
            close_run(run, TERMINAL_DONE, steps, now=datetime.now())
            escalated += 1
        except Exception:
            logger.exception("事件升级 Run 失败：%s", row.idempotency_key)
            append_step(
                run, steps,
                {"step": "event_pregate", "status": "error", "escalated": True},
            )
            close_run(run, TERMINAL_ABORTED, steps, now=datetime.now())
    return escalated
