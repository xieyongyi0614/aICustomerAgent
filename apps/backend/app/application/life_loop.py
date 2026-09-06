"""V2.0.0 LIFE-002 Life Loop Controller：统一周期编排（生活时刻）。

Perception → State Update → Goal Check → Memory Retrieval / Reflection
Check（LIFE-005 接入）→ Decision → World/Experience 的步骤管线；维护
步骤归并 world maintenance / action retry / trigger reconcile 的调度
入口（引擎函数原样复用，本体零改动）。

只调度不持有业务语义：不写业务域表（唯一写面 = loop_runs +
trigger_registry 状态接口）；Controller 本体 0 LLM（周期内 LLM 仅出现
于 decision 步骤内部的既有 proactive 链，受 LIFE-003 预算约束）。
"""

import asyncio
import logging
import time
from datetime import datetime

from app.core.settings import get_settings
from app.application import autonomy_engine, world_engine
from app.application.post_process import get_user_write_lock
from app.repositories import (
    conversation_repository,
    goal_repository,
    llm_call_repository,
    loop_run_repository,
    proactive_repository,
    trigger_registry_repository,
)
from app.application.life_loop_context import memory_digest_var
from app.services import life_loop_budget, state_service

logger = logging.getLogger(__name__)

_RECONCILE_INTERVAL_SECONDS = 300
_maintenance_last: dict[str, float] = {}
_reflection_check_last: dict[str, datetime] = {}


async def run_life_loop_worker(tick_seconds: int | None = None, llm=None) -> None:
    """常驻循环：先 sleep 后 tick（对齐 v1 循环节奏），异常吞掉下轮继续。"""
    interval = tick_seconds or get_settings().v2_life_loop_tick_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            await run_life_loop_tick(llm=llm)
        except Exception:
            logger.exception("life loop tick 异常，下轮继续")


async def run_life_loop_tick(llm=None, now: datetime | None = None) -> dict:
    """单周期：工作发现（纯 SQL/规则，0 LLM）→ 用户周期 → 维护步骤。"""
    settings = get_settings()
    if not settings.v2_life_loop_enabled:
        return {"user_cycles": 0, "maintenance": 0, "aborted": 0, "idle": True}
    now = now or datetime.now()
    stats: dict = {"user_cycles": 0, "maintenance": 0, "aborted": 0, "idle": False}
    work_users = _collect_work_users(now)
    maintenance_pending = _maintenance_pending(settings)
    if not work_users and not maintenance_pending:
        # Idle 短路（LIFE-003）：无 due trigger、无 goal 补扫、无维护到期
        # → 整轮跳过：0 LLM、0 run 行、仅时钟检查。
        stats["idle"] = True
        return stats
    for user_id in work_users:
        try:
            result = await _run_user_cycle(user_id, llm=llm, now=now)
            if result == "aborted":
                stats["aborted"] += 1
            else:
                stats["user_cycles"] += 1
        except Exception:
            stats["aborted"] += 1
            logger.exception("life loop 用户周期失败：%s", user_id)
    stats["maintenance"] = await _run_maintenance(now=now)
    stats["idle"] = not work_users and stats["maintenance"] == 0
    return stats


def _collect_work_users(now: datetime) -> list[str]:
    """工作发现：due 触发（排除重检型 inactivity）∪ 闲置 Eligible ∪ goal 补扫。"""
    users: set[str] = set()
    for user_id in conversation_repository.list_user_ids():
        if trigger_registry_repository.has_due(
            user_id, now=now, include_types=("scheduled_followup", "action_due")
        ):
            users.add(user_id)
            continue
        if _inactivity_eligible(user_id, now) or _goal_catchup_due(user_id):
            users.add(user_id)
    return sorted(users)


def _inactivity_eligible(user_id: str, now: datetime) -> bool:
    """闲置触发的廉价前置判定（完整守卫在 evaluate_inactivity 内复检）。"""
    settings = get_settings()
    conversation = conversation_repository.get_latest_for_user(user_id)
    if conversation is None:
        return False
    messages = conversation_repository.get_recent_messages(conversation.id, limit=5)
    last = messages[-1] if messages else None
    if last is None or last.created_at is None:
        return False
    if (now - last.created_at).total_seconds() / 60 < settings.autonomy_inactivity_minutes:
        return False
    last_user = next((m for m in reversed(messages) if m.role == "human"), None)
    if last_user is None or last_user.created_at is None:
        return False
    if (
        last.role == "human"
        and (now - last_user.created_at).total_seconds() / 60
        < settings.autonomy_min_user_reply_gap_minutes
    ):
        return False
    try:
        _, attempts = proactive_repository.aggregate_episode(
            user_id, episode_start=last_user.created_at
        )
    except Exception:
        logger.exception("episode 尝试数读取失败，按 0 处理")
        attempts = 0
    return attempts < settings.autonomy_max_attempts_per_episode


def _goal_catchup_due(user_id: str) -> bool:
    """是否存在上次对话结束时已应到期而未处理的 current goal（补扫口径）。"""
    expiring = [
        goal
        for goal in goal_repository.list_active(user_id)
        if goal.horizon == "current" and goal.expires_at_turn is not None
    ]
    if not expiring:
        return False
    conversation = conversation_repository.get_latest_for_user(user_id)
    if conversation is None:
        return False
    current_turn = (
        conversation_repository.count_human_messages(conversation.id) + 1
    )
    return any(goal.expires_at_turn < current_turn for goal in expiring)


async def _run_user_cycle(user_id: str, llm, now: datetime) -> str:
    """单用户周期：持 per-user 写锁串行执行步骤管线，loop_runs 全程记账。

    返回 run 终态（done|aborted）；critical 步骤（decision）失败 → aborted。
    decision 前置两道预算闸（LIFE-003）：全局日配额熔断 degraded → skip；
    周期步骤 LLM 预算耗尽 → skip（触发器留 pending，配额恢复后自然重试）。
    """
    settings = get_settings()
    run = loop_run_repository.create_run(
        user_id=user_id, kind="autonomy", reason=_cycle_reason(user_id, now), now=now
    )
    steps: list[dict] = []
    cycle_ctx: dict = {}
    budget = life_loop_budget.check_daily_budget(now=now)
    status = "done"
    try:
        async with get_user_write_lock(user_id):
            _record_step(run.id, steps, "perception", _step_perception, user_id, now)
            _record_step(run.id, steps, "state_update", _step_state_update, user_id, now)
            _record_step(run.id, steps, "goal_check", _step_goal_check, user_id, now)
            _record_step(
                run.id, steps, "memory_retrieval",
                _step_memory_retrieval, user_id, now, cycle_ctx,
            )
            _record_step(
                run.id, steps, "reflection_check", _step_reflection_check, user_id, now
            )
            if budget.status == life_loop_budget._STATUS_DEGRADED:
                _append_step(
                    run.id,
                    steps,
                    {
                        "step": "decision",
                        "status": "skipped",
                        "skip_reason": "quota_circuit_open",
                    },
                )
            elif _cycle_llm_budget_exhausted(steps, settings):
                _append_step(
                    run.id,
                    steps,
                    {
                        "step": "decision",
                        "status": "skipped",
                        "skip_reason": "step_budget",
                    },
                )
            else:
                await _record_step_async(
                    run.id, steps, "decision",
                    lambda: _step_decision(user_id, llm, now),
                    critical=True,
                )
            _record_step(
                run.id, steps, "world_experience", _step_world_experience, user_id, now
            )
    except Exception as exc:
        logger.exception("life loop 用户周期中止：%s", user_id)
        status = "aborted"
        steps.append(
            {"step": "abort", "status": "error", "error": exc.__class__.__name__}
        )
    digest_token = cycle_ctx.get("digest_token")
    if digest_token is not None:
        memory_digest_var.reset(digest_token)
    finished_at = datetime.now()
    try:
        llm_count = (
            llm_call_repository.count_calls_between(run.started_at, finished_at)
            if finished_at >= run.started_at
            else 0
        )
    except Exception:
        logger.exception("run 窗口 LLM 计数失败，按 0 记账")
        llm_count = 0
    loop_run_repository.finish_run(
        run.id,
        status=status,
        steps=steps,
        llm_call_count=llm_count,
        budget_state=budget.as_dict(),
        now=finished_at,
    )
    return status


def _append_step(run_id: str, steps: list[dict], entry: dict) -> None:
    entry.setdefault("duration_ms", 0.0)
    steps.append(entry)
    loop_run_repository.mark_step(run_id, entry)


def _cycle_llm_budget_exhausted(steps: list[dict], settings) -> bool:
    """周期步骤 LLM 预算（结构上限）：已执行的 LLM capable 步骤数达上限。"""
    used = sum(
        1
        for s in steps
        if s.get("llm_capable") and s.get("status") == "ok"
    )
    return used >= max(settings.v2_life_loop_cycle_llm_budget, 0)


async def _step_decision(user_id: str, llm, now: datetime) -> dict:
    """Decision+Action 步骤：v1 决策管线原样复用（周期内唯一 LLM capable 步骤）。"""
    await autonomy_engine.tick(user_ids=[user_id], llm=llm, now=now)
    return {"llm_capable": True}


def _cycle_reason(user_id: str, now: datetime) -> str:
    if trigger_registry_repository.has_due(
        user_id, now=now, include_types=("scheduled_followup", "action_due")
    ):
        return "due_trigger"
    if _goal_catchup_due(user_id):
        return "goal_catchup"
    return "inactivity_eligible"


def _record_step(run_id, steps, name, func, *args) -> None:
    started = time.perf_counter()
    entry: dict = {"step": name}
    try:
        detail = func(*args) or {}
        entry.update(detail)
        entry.setdefault("status", "ok")
    except Exception as exc:
        logger.exception("life loop 步骤失败：%s", name)
        entry.update({"status": "error", "error": exc.__class__.__name__})
    entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    steps.append(entry)
    loop_run_repository.mark_step(run_id, entry)


async def _record_step_async(run_id, steps, name, coro_factory, critical=False) -> None:
    started = time.perf_counter()
    entry: dict = {"step": name}
    try:
        detail = await coro_factory()
        entry.update(detail or {})
        entry.setdefault("status", "ok")
    except Exception as exc:
        logger.exception("life loop 步骤失败：%s", name)
        entry.update({"status": "error", "error": exc.__class__.__name__})
        if critical:
            entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            steps.append(entry)
            loop_run_repository.mark_step(run_id, entry)
            raise
    entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    steps.append(entry)
    loop_run_repository.mark_step(run_id, entry)


def _step_perception(user_id: str, now: datetime) -> dict:
    from app.application import action_engine

    world_facts = world_engine.collect_facts(user_id)
    action_facts: dict = {}
    if get_settings().action_enabled:
        try:
            action_facts = action_engine.collect_facts(user_id)
        except Exception:
            logger.exception("行动事实收集失败，返回空包")
    return {
        "status": "ok",
        "world_fact_keys": sorted(world_facts.keys()),
        "has_action_facts": bool(action_facts),
    }


def _step_state_update(user_id: str, now: datetime) -> dict:
    """读即衰减：load_states 内含 idle_recovery + emotion_decay 纯规则。"""
    character, _relationship = state_service.load_states(user_id)
    return {"status": "ok", "mood": character.mood}


def _step_goal_check(user_id: str, now: datetime) -> dict:
    expired = _expire_due_goals(user_id)
    return {"status": "ok", "expired": len(expired)}


def _expire_due_goals(user_id: str) -> list:
    """到期补扫：turn 基准过期规则与 goal_service.review 同口径
    （horizon=current ∧ expires_at_turn<current_turn → expire_goal）。"""
    expiring = [
        goal
        for goal in goal_repository.list_active(user_id)
        if goal.horizon == "current" and goal.expires_at_turn is not None
    ]
    if not expiring:
        return []
    conversation = conversation_repository.get_latest_for_user(user_id)
    if conversation is None:
        return []
    current_turn = (
        conversation_repository.count_human_messages(conversation.id) + 1
    )
    expired = []
    for goal in expiring:
        if current_turn > goal.expires_at_turn:
            record = goal_repository.expire_goal(goal.id)
            if record is not None:
                expired.append(record)
    return expired


def _step_memory_retrieval(user_id: str, now: datetime, cycle_ctx: dict) -> dict:
    """LIFE-005 周期记忆快查（显著度门槛，0 LLM）：digest 进 trace 并经
    contextvar 注入 proactive 生成上下文（recent_context 追加段）。"""
    from app.repositories import memory_repository

    settings = get_settings()
    if not settings.v2_memory_enabled:
        return {"status": "skipped", "skip_reason": "memory_disabled"}
    rows = memory_repository.list_top_salience(
        user_id,
        min_salience=settings.v2_life_loop_memory_min_salience,
        limit=settings.v2_life_loop_memory_limit,
    )
    if not rows:
        return {"status": "skipped", "skip_reason": "no_salient_memory", "count": 0}
    digest = _build_memory_digest(rows, settings.v2_life_loop_memory_digest_chars)
    cycle_ctx["digest_token"] = memory_digest_var.set(digest)
    return {
        "status": "ok",
        "count": len(rows),
        "memory_ids": [row.id for row in rows],
    }


def _build_memory_digest(rows, budget_chars: int) -> str:
    lines = [f"- [{row.type}] {row.content[:120]}" for row in rows]
    return ("与当前状态相关的重要记忆：\n" + "\n".join(lines))[:budget_chars]


def _step_reflection_check(user_id: str, now: datetime) -> dict:
    """LIFE-005 反思检查：复用 REF-003 触发器全链（证据门槛→额度→日桶幂等），
    本步骤只做频控调用；同周期/同日不重复入队由 REF-003 日桶键保证。"""
    from app.services.reflection import triggers as reflection_triggers

    settings = get_settings()
    if not settings.v2_reflection_enabled:
        return {"status": "skipped", "skip_reason": "reflection_disabled"}
    interval_minutes = settings.v2_life_loop_reflection_check_interval_minutes
    last = _reflection_check_last.get(user_id)
    if last is not None and (now - last).total_seconds() < interval_minutes * 60:
        return {"status": "skipped", "skip_reason": "throttled"}
    _reflection_check_last[user_id] = now
    outcome = reflection_triggers.trigger_for_user(user_id, trigger="event", now=now)
    return {"status": "ok", "outcome": outcome}


def _step_world_experience(user_id: str, now: datetime) -> dict:
    if not get_settings().world_enabled:
        return {"status": "skipped", "skip_reason": "world_disabled"}
    applied = world_engine.run_maintenance(user_id=user_id)
    return {"status": "ok", "applied": applied}


async def _run_maintenance(now: datetime) -> int:
    """维护步骤：world / action retry / trigger reconcile 按各自间隔调度。"""
    settings = get_settings()
    executed = 0
    if settings.world_enabled and _maintenance_due(
        "world_maintenance", settings.world_maintenance_interval_seconds
    ):
        _mark_maintenance("world_maintenance")
        entry = _safe_sync_call("world_maintenance", world_engine.run_maintenance)
        _record_maintenance_run("world_maintenance", [entry], now)
        executed += 1
    if settings.action_enabled and _maintenance_due(
        "action_retry", settings.action_maintenance_interval_seconds
    ):
        _mark_maintenance("action_retry")
        from app.application import action_engine

        entries: list[dict] = []
        try:
            await action_engine._process_due_retries()
            entries.append({"step": "action_retry", "status": "ok"})
        except Exception as exc:
            logger.exception("action retry 维护失败")
            entries.append(
                {"step": "action_retry", "status": "error", "error": exc.__class__.__name__}
            )
        try:
            expired = action_engine._expire_planned()
            entries.append({"step": "action_expire", "status": "ok", "result": expired})
        except Exception as exc:
            logger.exception("action 计划过期维护失败")
            entries.append(
                {"step": "action_expire", "status": "error", "error": exc.__class__.__name__}
            )
        status = (
            "aborted"
            if any(e["status"] == "error" for e in entries)
            else "done"
        )
        _record_maintenance_run("action_retry", entries, now, status=status)
        executed += 1
    if settings.v2_action_outbox_enabled:
        from app.application import outbox_consumer
        from app.repositories import outbox_repository

        pending = outbox_repository.list_pending(now=now, limit=1)
        if pending:
            stats = outbox_consumer.consume_pending(now=now)
            _record_maintenance_run(
                "outbox_consume",
                [{"step": "outbox_consume", "status": "ok", **stats}],
                now,
            )
            executed += 1
    if _maintenance_due("trigger_reconcile", _RECONCILE_INTERVAL_SECONDS):
        _mark_maintenance("trigger_reconcile")
        recovered = trigger_registry_repository.recover_stale(
            now=now,
            max_attempts=settings.v2_life_loop_trigger_max_attempts,
            backoff_seconds=settings.v2_life_loop_trigger_backoff_seconds,
        )
        _record_maintenance_run(
            "trigger_reconcile",
            [{"step": "trigger_reconcile", "status": "ok", "recovered": recovered}],
            now,
        )
        executed += 1
    return executed


def _maintenance_due(kind: str, interval: int) -> bool:
    last = _maintenance_last.get(kind)
    return last is None or (time.monotonic() - last) >= interval


def _maintenance_pending(settings) -> bool:
    """是否有维护步骤到期（Idle 判定项；不产生标记副作用）。"""
    if settings.world_enabled and _maintenance_due(
        "world_maintenance", settings.world_maintenance_interval_seconds
    ):
        return True
    if settings.action_enabled and _maintenance_due(
        "action_retry", settings.action_maintenance_interval_seconds
    ):
        return True
    if settings.v2_action_outbox_enabled:
        from app.repositories import outbox_repository

        if outbox_repository.list_pending(limit=1):
            return True
    return _maintenance_due("trigger_reconcile", _RECONCILE_INTERVAL_SECONDS)


def _mark_maintenance(kind: str) -> None:
    _maintenance_last[kind] = time.monotonic()


def _safe_sync_call(kind: str, func) -> dict:
    try:
        result = func()
        if isinstance(result, dict):
            return {"step": kind, "status": "ok", **result}
        return {"step": kind, "status": "ok", "result": result}
    except Exception as exc:
        logger.exception("维护步骤失败：%s", kind)
        return {"step": kind, "status": "error", "error": exc.__class__.__name__}


def _record_maintenance_run(
    kind: str, steps, now: datetime, status: str = "done"
) -> None:
    run = loop_run_repository.create_run(
        user_id=None, kind=kind, reason="interval_due", now=now
    )
    step_list = steps if isinstance(steps, list) else [steps]
    loop_run_repository.finish_run(
        run.id, status=status, steps=step_list, now=now
    )
