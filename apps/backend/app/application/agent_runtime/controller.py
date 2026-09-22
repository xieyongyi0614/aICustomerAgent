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
    TERMINAL_DEGRADED,
    TERMINAL_DONE,
    RunContext,
)
from app.application.life_loop_context import memory_digest_var
from app.core.settings import get_settings
from app.application import logical_clock
from app.repositories import llm_call_repository, loop_run_repository
from app.services import life_loop_budget
from app.services import outbox_service

logger = logging.getLogger(__name__)


def open_run(
    user_id: str | None,
    run_kind: str,
    trigger_type: str,
    reason: str,
    now: datetime | None = None,
    *,
    session_id: str | None = None,
) -> RunContext:
    """Run Open：台账建行 + Profile 快照落库；kind 沿既有枚举（前台=chat）。

    `session_id` 仅在 `runtime_session_tracking_enabled` 开启时写入（裁决 D4）；
    关闭时列恒为 NULL，读路径始终兼容 NULL。
    """
    now = now or datetime.now()
    kind = "chat" if run_kind == RUN_KIND_FOREGROUND_CHAT else "autonomy"
    tracked_session_id = (
        session_id if get_settings().runtime_session_tracking_enabled else None
    )
    row = loop_run_repository.create_run(
        user_id=user_id,
        kind=kind,
        reason=reason,
        trigger_type=trigger_type,
        run_kind=run_kind,
        profile=profiles.snapshot_profile(run_kind),
        now=now,
        session_id=tracked_session_id,
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


def open_foreground_run(
    user_id: str,
    now: datetime | None = None,
    *,
    session_id: str | None = None,
) -> RunContext:
    """前台收编入口：每轮对话都是一次 foreground_chat Run。"""
    run_kind, trigger_type = trigger_router.classify_channel_message()
    return open_run(
        user_id, run_kind, trigger_type, "user_message", now, session_id=session_id
    )


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
        return entry
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


def _reset_run_projections(run: RunContext) -> None:
    """释放 Run 内只读投影缓存（H-5）：State / Context 不把域内容留在 `run.data`。

    惰性导入：`context` 依赖 `world_engine`，模块级导入会把世界装配链拉进 controller。
    """
    from app.application.agent_runtime import context as runtime_context_manager
    from app.application.agent_runtime import state as state_manager

    for reset in (state_manager.reset, runtime_context_manager.reset):
        try:
            reset(run)
        except Exception:  # noqa: BLE001 — 释放失败不得影响关账
            logger.exception("Run 投影释放失败：%s", run.run_id)


def _safe_close_run(
    run: RunContext,
    status: str,
    steps: list | None = None,
    budget_state: dict | None = None,
) -> None:
    """关账兜底：关账自身异常不得掩盖上游异常（取消 / 段失败）。"""
    try:
        close_run(run, status, steps, budget_state=budget_state, now=datetime.now())
    except Exception:  # noqa: BLE001
        logger.exception("agent run 关账失败：%s", run.run_id)


def _autonomous_stage_runner(name: str, user_id: str, run: RunContext, now: datetime):
    """阶段名 → 既有步骤本体（Profile Registry 是唯一阶段序列来源）。

    未注册阶段名 fail-closed 抛错：注册表与实现不一致必须暴露，不得静默跳过。
    同步阶段经 asyncio.to_thread 下放（同步 DB/纯函数离开事件循环）；
    memory_retrieval 在 ContextVar 上置 digest token，必须留在主上下文。
    """
    from app.application import life_loop as life_loop_mod

    runners = {
        "perception": lambda: asyncio.to_thread(
            life_loop_mod._step_perception, user_id, now
        ),
        "state_update": lambda: asyncio.to_thread(
            life_loop_mod._step_state_update, user_id, now
        ),
        "state_snapshot": lambda: asyncio.to_thread(run_state_snapshot_stage, user_id, run),
        "goal_check": lambda: asyncio.to_thread(
            life_loop_mod._step_goal_check, user_id, now
        ),
        "goal_stack": lambda: asyncio.to_thread(
            goal_stack.run_goal_stack_stage, user_id, run, now
        ),
        "goal_supply": lambda: asyncio.to_thread(
            life_loop_mod._step_goal_supply, user_id, now
        ),
        "goal_advance": lambda: life_loop_mod._step_goal_advance(user_id, now),
        "memory_retrieval": lambda: life_loop_mod._step_memory_retrieval(
            user_id, now, run.data
        ),
        "reflection_check": lambda: asyncio.to_thread(
            life_loop_mod._step_reflection_check, user_id, now
        ),
        "world_experience": lambda: asyncio.to_thread(
            life_loop_mod._step_world_experience, user_id, now
        ),
    }
    try:
        return runners[name]
    except KeyError as exc:
        raise ValueError(f"Profile 声明了未实现的阶段：{name}") from exc


def legacy_cycle_runnable():
    """开关关闭时的既有自治周期执行体（保留，供灰度对照与回退）。"""
    return _legacy_run_autonomous_cycle


async def _legacy_run_autonomous_cycle(
    user_id: str,
    llm=None,
    now: datetime | None = None,
    trigger_type: str | None = None,
    reason: str | None = None,
) -> str:
    """autonomous_tick Profile：按 Profile Registry 声明的阶段序列执行。

    唯一的自治周期入口（v2.0.0 的 `life_loop._run_user_cycle` 已随开关体系删除下线）：
    台账落 run_kind/profile，decision 前置三道闸，触发源支持事件升级。
    """
    from app.application.post_process import get_user_write_lock

    now = now or datetime.now()
    clock_token = logical_clock.bind(now)
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
                await run_stage_async(
                    run, steps, name, runner, critical=name in spec.critical
                )
    except asyncio.CancelledError:
        logger.warning("agent run 用户周期被取消，按 aborted 关账：%s", user_id)
        status = TERMINAL_ABORTED
        steps.append({"step": "cancel", "status": "error", "error": "CancelledError"})
        raise
    except Exception as exc:
        logger.exception("agent run 用户周期中止：%s", user_id)
        status = TERMINAL_ABORTED
        steps.append(
            {"step": "abort", "status": "error", "error": exc.__class__.__name__}
        )
    except BaseException as exc:  # noqa: BLE001 — KeyboardInterrupt / SystemExit 等
        logger.exception("agent run 用户周期被中断：%s", user_id)
        status = TERMINAL_ABORTED
        steps.append(
            {"step": "abort", "status": "error", "error": exc.__class__.__name__}
        )
        raise
    finally:
        logical_clock.unbind(clock_token)
        digest_token = run.data.get("digest_token")
        if digest_token is not None:
            memory_digest_var.reset(digest_token)
        agent_state_assembler.reset_run_state(run)
        _reset_run_projections(run)
        _safe_close_run(run, status, steps, budget_state=budget.as_dict())
    return status


async def run_autonomous_cycle(
    user_id: str,
    llm=None,
    now: datetime | None = None,
    trigger_type: str | None = None,
    reason: str | None = None,
) -> str:
    """autonomous_tick 唯一入口：开关关走既有执行体，开关开走 AgentLoop。

    两条路径共享 decision 三道闸语义与 11 段阶段本体（RT-016 D1/D2/D3）。
    """
    if get_settings().runtime_autonomous_cycle_enabled:
        return await _run_autonomous_cycle_via_loop(
            user_id, llm=llm, now=now, trigger_type=trigger_type, reason=reason
        )
    return await legacy_cycle_runnable()(
        user_id, llm=llm, now=now, trigger_type=trigger_type, reason=reason
    )


async def _run_autonomous_cycle_via_loop(
    user_id: str,
    llm=None,
    now: datetime | None = None,
    trigger_type: str | None = None,
    reason: str | None = None,
) -> str:
    """AgentLoop 驱动的自治周期：阶段本体仍经既有 runners，只换执行形状。"""
    from app.application.agent_runtime.loop import STAGE_RUNNERS, AgentLoop

    now = now or datetime.now()
    settings = get_settings()
    if trigger_type is None or reason is None:
        trigger_type, reason = trigger_router.classify_background_trigger(user_id, now)
    run = open_run(user_id, RUN_KIND_AUTONOMOUS_TICK, trigger_type, reason, now)
    budget = life_loop_budget.check_daily_budget(now=now)
    loop_box: list = []

    async def _decision(_context):
        return await _decision_stage_with_gates(
            run,
            loop_box[0]._steps if loop_box else [],
            user_id,
            llm,
            now,
            budget,
            settings,
        )

    registry = dict(STAGE_RUNNERS)
    registry["decision"] = _decision
    loop = AgentLoop(
        profiles.get_profile(RUN_KIND_AUTONOMOUS_TICK),
        user_id=user_id,
        run=run,
        llm=llm,
        now=now,
        registry=registry,
        promote_degraded=False,
    )
    loop_box.append(loop)
    result = await loop.run()
    return str(result.status)


async def _decision_stage_with_gates(
    run, steps, user_id, llm, now, budget, settings
) -> dict:
    """decision 三道闸（与 legacy `_run_decision_stage` 同序同语义）。"""
    from app.application import life_loop as life_loop_mod

    if budget.status == life_loop_budget._STATUS_DEGRADED:
        return {"status": "skipped", "skip_reason": "quota_circuit_open"}
    if life_loop_mod._cycle_llm_budget_exhausted(steps, settings):
        return {"status": "skipped", "skip_reason": "step_budget"}
    if not acquire(user_id, "proactive", run, now=now).granted:
        return {"status": "skipped", "skip_reason": "gateway_denied"}
    return await life_loop_mod._step_decision(user_id, llm, now)


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
    """event_driven Profile（Flow C）：白名单事件升级为完整 Run，其余 0 消耗。

    两层 Run 的语义：外层记「事件升级」这件事，内层是被升级出来的 tick（见 H-6 裁决）。
    外层**传播内层终态**（不再恒记 `done`）并在 `finally` 关账，取消 / 异常也不留孤儿。
    """
    settings = get_settings()
    if not settings.agent_event_escalation_types:
        return 0
    now = now or datetime.now()
    escalated = 0
    for row in outbox_service.list_pending(now=now, limit=20):
        if not trigger_router.evaluate_event_escalation(row.event_type):
            continue
        user_id = (row.payload or {}).get("user_id")
        if not user_id:
            continue
        run = open_run(
            user_id, RUN_KIND_EVENT_DRIVEN, "world_event", f"event:{row.event_type}", now
        )
        steps: list = []
        status = TERMINAL_ABORTED
        try:
            inner_status = await run_autonomous_cycle(
                user_id, llm=llm, now=now,
                trigger_type="world_event", reason=f"event:{row.event_type}",
            )
            status = _escalation_status(inner_status)
            append_step(
                run, steps,
                {
                    "step": "event_pregate",
                    "status": "ok" if status == TERMINAL_DONE else "error",
                    "escalated": True,
                    "inner_status": inner_status,
                },
            )
            if status != TERMINAL_ABORTED:
                escalated += 1
        except asyncio.CancelledError:
            logger.warning("事件升级被取消：%s", row.idempotency_key)
            status = TERMINAL_ABORTED
            append_step(
                run, steps,
                {"step": "event_pregate", "status": "error", "escalated": True},
            )
            raise
        except Exception:
            logger.exception("事件升级 Run 失败：%s", row.idempotency_key)
            status = TERMINAL_ABORTED
            append_step(
                run, steps,
                {"step": "event_pregate", "status": "error", "escalated": True},
            )
        finally:
            _reset_run_projections(run)
            _safe_close_run(run, status, steps)
    return escalated


def _escalation_status(inner_status: object) -> str:
    """内层 tick 终态 → 外层升级 Run 终态（未知值保守记 aborted）。"""
    value = str(inner_status or "")
    if value in (TERMINAL_DONE, TERMINAL_DEGRADED, TERMINAL_ABORTED):
        return value
    return TERMINAL_ABORTED
