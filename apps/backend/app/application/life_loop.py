"""V2.0.0 LIFE-002 Life Loop Controller：统一周期编排（生活时刻）。

Perception → State Update → Goal Check → Memory Retrieval / Reflection
Check（LIFE-005 接入）→ Decision → World/Experience 的步骤管线；维护
步骤归并 world maintenance / action retry / action schedule / trigger
reconcile 的调度入口（引擎函数原样复用，本体零改动）。

只调度不持有业务语义：不写业务域表（唯一写面 = loop_runs +
trigger_registry 状态接口）；Controller 本体 0 LLM（周期内 LLM 仅出现
于 decision 步骤内部的既有 proactive 链，受 LIFE-003 预算约束）。
"""

import asyncio
import logging
import time
from dataclasses import fields, is_dataclass
from datetime import datetime
from types import SimpleNamespace

from app.core import timeutil
from app.core.settings import get_settings
from app.application import (
    agent_runtime,
    autonomy_engine,
    world_engine,
    action_engine,
    observability,
    outbox_consumer,
)
from app.repositories import (
    conversation_repository,
    goal_repository,
    loop_run_repository,
    proactive_repository,
    trigger_registry_repository,
)
from app.application.life_loop_context import memory_digest_var
from app.services.tool.confirmation import non_todo_payload_kinds
from app.services.life import budget as life_loop_budget
from app.services.conversation import state as state_service
from app.services.goal import planning as goal_planning
from app.services.goal import arbitration as goal_arbitration
from app.services.goal import execution as goal_execution
from app.services.goal import observation as goal_observation
from app.engines import autonomy as autonomy_policy
from app.services.planning import engine as planning_engine
from app.services.planning import observer as plan_observer
from app.services.planning import executor_bridge as plan_executor_bridge
from app.services.planning import revision as plan_revision
from app.services.planning import scheduler as plan_scheduler
from app.application.worker_loop import run_worker_loop
from app.models.observability import TraceKind
from app.repositories import memory_repository, outbox_repository
from app.services.reflection import triggers as reflection_triggers
from app.services.observability.collector import TurnTraceSession

logger = logging.getLogger(__name__)

_RECONCILE_INTERVAL_SECONDS = 300
_maintenance_last: dict[str, float] = {}
_reflection_check_last: dict[str, datetime] = {}
_supply_last: dict[str, datetime] = {}


async def run_life_loop_worker(tick_seconds: int | None = None, llm=None) -> None:
    """常驻循环：先 sleep 后 tick（对齐 v1 循环节奏），异常吞掉下轮继续。"""

    async def _tick():
        await run_life_loop_tick(llm=llm)

    await run_worker_loop(
        "life loop worker",
        _tick,
        tick_seconds or get_settings().life_loop_tick_seconds,
    )


async def run_life_loop_tick(llm=None, now: datetime | None = None) -> dict:
    """单周期：工作发现（纯 SQL/规则，0 LLM）→ 用户周期 → 维护步骤。"""
    settings = get_settings()
    now = timeutil.ensure_aware(now) or timeutil.now()
    stats: dict = {"user_cycles": 0, "maintenance": 0, "aborted": 0, "idle": False}
    work_users = await asyncio.to_thread(_collect_work_users, now)
    maintenance_pending = await asyncio.to_thread(_maintenance_pending, settings)
    if not work_users and not maintenance_pending:
        # Idle 短路（LIFE-003）：无 due trigger、无 goal 补扫、无维护到期
        # → 整轮跳过：0 LLM、0 run 行、仅时钟检查。
        stats["idle"] = True
        return stats
    for user_id in work_users:
        try:
            result = await agent_runtime.run_autonomous_cycle(
                user_id, llm=llm, now=now
            )
            if result == "aborted":
                stats["aborted"] += 1
            else:
                stats["user_cycles"] += 1
        except Exception:
            stats["aborted"] += 1
            logger.exception("life loop 用户周期失败：%s", user_id)
    await agent_runtime.run_event_pregate(llm=llm, now=now)
    stats["maintenance"] = await _run_maintenance(now=now)
    stats["idle"] = not work_users and stats["maintenance"] == 0
    return stats


def _due_trigger_present(user_id: str, now: datetime) -> bool:
    """到期待办触发判定（工作发现 / 周期原因共用）。

    P2-1：排除借表的确认请求行与授权行（`payload.kind`）——它们用
    `due_at` 只表达 TTL，从到期到清理的窗口里不应被算成"到期待办"而多跑一轮自治 tick。
    """
    return trigger_registry_repository.has_due(
        user_id,
        now=now,
        include_types=("scheduled_followup", "action_due"),
        exclude_payload_kinds=non_todo_payload_kinds(),
    )


def _collect_work_users(now: datetime) -> list[str]:
    """工作发现：due 触发（排除重检型 inactivity）∪ goal 追求 ∪ 闲置 Eligible ∪ goal 补扫。"""
    users: set[str] = set()
    for user_id in conversation_repository.list_user_ids():
        if _due_trigger_present(user_id, now):
            users.add(user_id)
            continue
        if _goal_work_due(user_id, now) or _inactivity_eligible(
            user_id, now
        ) or _goal_catchup_due(user_id):
            users.add(user_id)
    return sorted(users)


def _goal_work_due(user_id: str, now: datetime) -> bool:
    """AUT-003 第四来源：active plan 存在待推进 Sub-Goal 且执行窗已到。"""
    settings = get_settings()
    try:
        pairs = goal_repository.list_active_plans(user_id)
    except Exception:
        logger.exception("active plans 读取失败，goal 追求来源跳过")
        return False
    for _goal, plan in pairs:
        for spec in plan.sub_goals:
            if spec.status not in ("pending", "in_progress"):
                continue
            last = spec.last_attempt_at or spec.last_observed_at
            if last is None:
                return True
            if (now - last).total_seconds() >= (
                settings.autonomy_subgoal_execute_cooldown_minutes * 60
            ):
                return True
    return False


def _inactivity_eligible(user_id: str, now: datetime) -> bool:
    """闲置触发的廉价前置判定（完整守卫在 evaluate_inactivity 内复检）。"""
    settings = get_settings()
    now = timeutil.ensure_aware(now)
    conversation = conversation_repository.get_latest_for_user(user_id)
    if conversation is None:
        return False
    messages = conversation_repository.get_recent_messages(conversation.id, limit=5)
    last = messages[-1] if messages else None
    if last is None or last.created_at is None:
        return False
    last_at = timeutil.ensure_aware(last.created_at)
    if (now - last_at).total_seconds() / 60 < settings.autonomy_inactivity_minutes:
        return False
    last_user = next((m for m in reversed(messages) if m.role == "human"), None)
    if last_user is None or last_user.created_at is None:
        return False
    last_user_at = timeutil.ensure_aware(last_user.created_at)
    if (
        last.role == "human"
        and (now - last_user_at).total_seconds() / 60
        < settings.autonomy_min_user_reply_gap_minutes
    ):
        return False
    try:
        _, attempts = proactive_repository.aggregate_episode(
            user_id, episode_start=last_user_at
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


def _cycle_llm_budget_exhausted(steps: list[dict], settings) -> bool:
    """周期步骤 LLM 预算（结构上限）：已执行的 LLM capable 步骤数达上限。"""
    used = sum(
        1
        for s in steps
        if s.get("llm_capable") and s.get("status") == "ok"
    )
    return used >= max(settings.life_loop_cycle_llm_budget, 0)


async def _step_decision(user_id: str, llm, now: datetime) -> dict:
    """Decision+Action 步骤：v1 决策管线原样复用（周期内唯一 LLM capable 步骤）。"""
    await autonomy_engine.tick(user_ids=[user_id], llm=llm, now=now)
    return {"llm_capable": True}


def cycle_reason(user_id: str, now: datetime) -> str:
    return _cycle_reason(user_id, now)


def _cycle_reason(user_id: str, now: datetime) -> str:
    if _due_trigger_present(user_id, now):
        return "due_trigger"
    if _goal_work_due(user_id, now):
        return "goal_work"
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
    world_facts = world_engine.collect_facts(user_id)
    action_facts: dict = {}
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


def _step_goal_supply(user_id: str, now: datetime) -> dict:
    """AUT-002 供给装配（纯规则 0 LLM）：三来源候选→层级 goal→规划 job 入队。
    World 事实由本编排步骤采集传入（GAP-AUT-02 编排投影），degraded 熔断。

    V2.5.0 PLAN-003 接线（总闸已随开关体系删除，本步恒走）：`PlanningEngine.enqueue` /
    `run_jobs`（规划在供给步内被处理完，不再只依赖后台 job worker）。入队幂等
    （`idempotency_key` 含 trigger），故对 `materialize` 已入队的目标重复入队返回
    False、不产生第二个 job。
    """

    settings = get_settings()
    budget = life_loop_budget.check_daily_budget(now=now)
    if budget.status == life_loop_budget._STATUS_DEGRADED:
        return {"status": "skipped", "skip_reason": "quota_circuit_open"}
    interval_minutes = settings.autonomy_supply_interval_minutes
    last = _supply_last.get(user_id)
    if last is not None and (now - last).total_seconds() < interval_minutes * 60:
        return {"status": "skipped", "skip_reason": "throttled"}
    _supply_last[user_id] = now
    world_facts = world_engine.collect_facts(user_id)
    result = goal_planning.materialize(user_id, world_facts=world_facts, now=now)
    _route_planning_jobs(user_id, result, settings)
    return {"status": result.get("status", "ok"), **result}


def _route_planning_jobs(user_id: str, result: dict, settings) -> None:
    """V2.5.0 规划接线：规划入队经引擎 + 本步内处理本类型 job。

    入队幂等：`materialize` 已入队的目标在此重复入队返回 False，不产生第二个 job
    （`job_type` 仍为既有 `goal_planning`，`idempotency_key` 含 trigger）。
    """
    engine = planning_engine.get_planning_engine()
    for goal_id in result.get("created") or []:
        engine.enqueue(user_id, str(goal_id), goal_planning.TRIGGER_CREATED)
    engine.run_jobs()


def _observation_facts(user_id: str, now: datetime) -> dict:
    """AUT-003 观察事实编排投影（GAP-AUT-02）：action 窗口/world/state/memory。

    V2.5.0 PLAN-005：投影本体搬运到 `PlanObserver.collect_facts`（第四源 `tool` 在同一处装配，
    避免两套事实装配）；本函数保留一个版本窗口作为既有调用点（`life_loop` 与 V2.0.0 用例）的
    兼容出口，`observation_keys=()`（显式空白名单）使本路径**零额外读取**——查询面与 V2.4.0 逐一相同。
    """

    return plan_observer.PlanObserver().collect_facts(
        user_id,
        plan_observer.ObservationContext(now=now),
        observation_keys=(),
    )


def _current_plan_step(goal, plan, settings):
    """当前可执行步（`PlanScheduler.current_step`，§4.2 #11 收口后的唯一实现）。"""
    return plan_scheduler.PlanScheduler.current_step(plan)


def _execution_ctx(now: datetime, facts: dict):
    """执行桥上下文（鸭子类型）：只需 `now` 与规划期世界事实投影。"""
    return SimpleNamespace(now=now, world=dict(facts.get("world") or {}))


def _should_skip_user_facing(step, now, settings) -> dict | None:
    """静音时段克制（编排规则，与既有 `goal_execution` 同款，不入 Policy）。"""
    if step.capability not in goal_execution._USER_FACING_CAPABILITIES:  # pylint: disable=protected-access
        return None
    if not autonomy_policy.in_quiet_hours(
        now,
        settings.autonomy_quiet_hours_start,
        settings.autonomy_quiet_hours_end,
    ):
        return None
    return {"status": "skipped", "skip_reason": "quiet_hours"}


def _revision_ctx(settings) -> SimpleNamespace:
    return SimpleNamespace(
        step_max_attempts=settings.plan_step_max_attempts,
        off_surface_streak=0,
        undecidable_streak=0,
        insight_driven=False,
    )


async def execute_plan_step(goal, plan, now: datetime, facts: dict, settings) -> dict:
    """公开门面（M-6）：计划步骤执行本体。

    Runtime 的 Act 段经此调用（RT-010「既有 `_execute_plan_step` 本体，非重写」），
    不触私有名。语义与 `_execute_plan_step` 完全一致。
    """
    return await _execute_plan_step(goal, plan, now, facts, settings)


async def _execute_plan_step(goal, plan, now: datetime, facts: dict, settings) -> dict:
    """V2.5.0 执行桥接线：一步走 `execute_step`。

    链路：`current_step` → `execute_step`（两道防御性断言 + 六闸门）→ `reconcile`
    → `update_plan_progress`；重规划子闸 on 时追加 `PlanRevisionPolicy` 裁决入队。
    落库仍只经 `goal_repository` 计划面（单一写面）。
    """
    step = _current_plan_step(goal, plan, settings)
    if step is None:
        return {"status": "skipped", "skip_reason": "no_current_step", "goal_id": goal.id}
    quiet = _should_skip_user_facing(step, now, settings)
    if quiet is not None:
        return {**quiet, "goal_id": goal.id}
    bridge = plan_executor_bridge.PlanExecutorBridge()
    ctx = _execution_ctx(now, facts)
    outcome = await bridge.execute_step(goal, plan, step, ctx)
    updated = bridge.reconcile(outcome, step)
    specs = list(plan.sub_goals)
    for position, existing in enumerate(specs):
        if existing.index == updated.index:
            specs[position] = updated
            break
    goal_repository.update_plan_progress(plan.id, specs)
    revised_plan = plan.model_copy(update={"sub_goals": specs})
    reason = plan_revision.PlanRevisionPolicy().should_replan(
        outcome, revised_plan, _revision_ctx(settings)
    )
    if reason:
        goal_planning.enqueue_planning(
            goal.user_id, goal.id, goal_planning.TRIGGER_REPLAN
        )
    return {
        "status": "ok",
        "goal_id": goal.id,
        "step_index": updated.index,
        "outcome": outcome.status,
        "step_status": updated.status,
        "action_id": outcome.action_id,
        "failure_kind": outcome.failure_kind,
    }


async def _execute_active_plans(user_id: str, now: datetime, facts: dict) -> list[dict]:
    """步骤执行（计划执行桥，§4.2 #12 收口后的唯一路径）。"""
    settings = get_settings()
    pairs = goal_repository.list_active_plans(user_id)
    return [await _execute_plan_step(goal, plan, now, facts, settings) for goal, plan in pairs]


def _observe_goals(user_id: str, now: datetime) -> tuple[dict, dict, dict]:
    """观察事实与推进裁决（PLAN-005 接线点 §5.6，§4.2 #13 收口后的唯一路径）。

    `PlanObserver.collect_facts`（四源）+ `observe_user_goals`（推进裁决落
    `decision_records`、终态经 `settle` 单一写面）。
    """
    observer = plan_observer.PlanObserver()
    facts = observer.collect_facts(user_id, plan_observer.ObservationContext(now=now))
    advance = observer.observe_user_goals(user_id, facts, now=now)
    return facts, advance, {
        "goals": advance.get("goals", 0),
        "settled": advance.get("settled", 0),
    }


async def _step_goal_advance(user_id: str, now: datetime) -> dict:
    """AUT-004 仲裁（复活/冲突/放弃）→ AUT-003 观察调整 → Sub-Goal 执行尝试。
    仲裁与观察全确定性 0 LLM；执行走 V9 既有闸门。

    V2.5.0 PLAN-005 接线（§5.6 / §8 Step 8）：观测经 `_observe_goals`、执行经
    `_execute_active_plans`（二者均常开）。**签名、九步序列与返回字段集不变**；计划阶段
    子步骤以 `plan_observe` / `plan_execute` 记入返回投影。
    """

    settings = get_settings()
    pairs = goal_repository.list_active_plans(user_id)
    if not pairs:
        return {"status": "ok", "goals": 0, "observations": 0, "executions": 0}
    started = time.perf_counter()
    facts, advance, plan_observe = _observe_goals(user_id, now)
    arbitration = goal_arbitration.run_user_arbitration(user_id, facts, now)
    executions = await _execute_active_plans(user_id, now, facts)
    plan_execute = {
        "steps": len(executions),
        "outcomes": [item.get("outcome") for item in executions],
    }
    trace = TurnTraceSession()
    trace.record(
        "goal_observation",
        (time.perf_counter() - started) * 1000,
        "ok",
        goals=advance.get("goals", 0),
        results=advance.get("results", []),
        executions=executions,
        arbitration_changes=arbitration.get("arbitration_changes", []),
        abandoned=arbitration.get("abandoned", []),
    )
    _persist_goal_trace(trace, user_id)
    return {
        "status": "ok",
        "goals": advance.get("goals", 0),
        "observations": sum(
            1
            for item in advance.get("results", [])
            if isinstance(item, dict) and item.get("observations")
        ),
        "executions": len(executions),
        "arbitration_changes": len(arbitration.get("arbitration_changes", [])),
        "abandoned": len(arbitration.get("abandoned", [])),
        **({"plan_observe": plan_observe} if plan_observe else {}),
        **({"plan_execute": plan_execute} if plan_execute else {}),
    }


def _persist_goal_trace(trace, user_id: str) -> None:
    try:
        observability.on_turn_finished(
            trace,
            turn_id=None,
            user_id=user_id,
            session_id=None,
            kind=TraceKind.AUTONOMY_TICK,
            drain_background=False,
        )
    except Exception:
        logger.exception("goal 观察 trace 落库失败，已忽略")


async def _step_memory_retrieval(user_id: str, now: datetime, cycle_ctx: dict) -> dict:
    """LIFE-005 周期记忆快查（显著度门槛，0 LLM）：digest 进 trace 并经
    contextvar 注入 proactive 生成上下文（recent_context 追加段）。

    ContextVar 的 set/reset 必须在主上下文，DB 读经 to_thread 下放。
    """

    settings = get_settings()
    rows = await asyncio.to_thread(
        memory_repository.list_top_salience,
        user_id,
        min_salience=settings.life_loop_memory_min_salience,
        limit=settings.life_loop_memory_limit,
    )
    if not rows:
        return {"status": "skipped", "skip_reason": "no_salient_memory", "count": 0}
    digest = _build_memory_digest(rows, settings.life_loop_memory_digest_chars)
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

    settings = get_settings()
    interval_minutes = settings.life_loop_reflection_check_interval_minutes
    last = _reflection_check_last.get(user_id)
    if last is not None and (now - last).total_seconds() < interval_minutes * 60:
        return {"status": "skipped", "skip_reason": "throttled"}
    _reflection_check_last[user_id] = now
    outcome = reflection_triggers.trigger_for_user(user_id, trigger="event", now=now)
    return {"status": "ok", "outcome": outcome}


def _step_world_experience(user_id: str, now: datetime) -> dict:
    applied = world_engine.run_maintenance(user_id=user_id)
    return {"status": "ok", "applied": applied}


async def _run_maintenance(now: datetime) -> int:
    """维护步骤：world / action retry / trigger reconcile 按各自间隔调度。"""
    settings = get_settings()
    executed = 0
    if _maintenance_due(
        "world_maintenance", settings.world_maintenance_interval_seconds
    ):
        _mark_maintenance("world_maintenance")
        entry = await _safe_sync_call("world_maintenance", world_engine.run_maintenance)
        _record_maintenance_run("world_maintenance", [entry], now)
        executed += 1
    if _maintenance_due("world_simulation", settings.world_sim_interval_seconds):
        _mark_maintenance("world_simulation")
        entry = await _safe_sync_call("world_simulation", world_engine.run_simulation_maintenance)
        _record_maintenance_run("world_simulation", [entry], now)
        executed += 1
    if _maintenance_due(
        "action_retry", settings.action_maintenance_interval_seconds
    ):
        _mark_maintenance("action_retry")

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
    if _maintenance_due(
        "action_schedule", settings.action_maintenance_interval_seconds
    ):
        _mark_maintenance("action_schedule")
        from app.services.action import scheduler as action_scheduler

        try:
            result = await action_scheduler.step_action_schedule(now) or {}
            entry = {"step": "action_schedule", **result}
            entry.setdefault("status", "ok")
        except Exception as exc:
            logger.exception("action schedule 维护失败")
            entry = {
                "step": "action_schedule",
                "status": "error",
                "error": exc.__class__.__name__,
            }
        _record_maintenance_run("action_schedule", [entry], now)
        executed += 1
    if settings.action_outbox_enabled:
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
            max_attempts=settings.life_loop_trigger_max_attempts,
            backoff_seconds=settings.life_loop_trigger_backoff_seconds,
        )
        _record_maintenance_run(
            "trigger_reconcile",
            [{"step": "trigger_reconcile", "status": "ok", "recovered": recovered}],
            now,
        )
        executed += 1
    if _maintenance_due("ledger_digest", 60):
        _mark_maintenance("ledger_digest")
        from app.services.ledger import alert as ledger_alert
        from app.services.ledger import digest as ledger_digest

        try:
            result = await asyncio.to_thread(ledger_digest.run_maintenance, now) or {}
            entry = {"step": "ledger_digest", "status": "ok", **result}
        except Exception as exc:
            logger.exception("ledger digest 维护失败")
            entry = {
                "step": "ledger_digest",
                "status": "error",
                "error": exc.__class__.__name__,
            }
        _record_maintenance_run("ledger_digest", [entry], now)
        executed += 1
    if _maintenance_due("ledger_alert", 60):
        _mark_maintenance("ledger_alert")
        from app.services.ledger import alert as ledger_alert

        try:
            result = await asyncio.to_thread(ledger_alert.run_maintenance, now) or {}
            entry = {"step": "ledger_alert", "status": "ok", **result}
        except Exception as exc:
            logger.exception("ledger alert 维护失败")
            entry = {
                "step": "ledger_alert",
                "status": "error",
                "error": exc.__class__.__name__,
            }
        _record_maintenance_run("ledger_alert", [entry], now)
        executed += 1
    if get_settings().runtime_orphan_run_sweep_enabled:
        from app.application.agent_runtime import recovery as runtime_recovery

        try:
            swept = runtime_recovery.sweep_orphan_runs(now=now)
            if swept:
                logger.info("runtime orphan sweep：%d 条", len(swept))
        except Exception:
            logger.exception("runtime orphan sweep 失败")
    return executed


def _maintenance_due(kind: str, interval: int) -> bool:
    last = _maintenance_last.get(kind)
    return last is None or (time.monotonic() - last) >= interval


def _maintenance_pending(settings) -> bool:
    """是否有维护步骤到期（Idle 判定项；不产生标记副作用）。"""
    if _maintenance_due(
        "world_maintenance", settings.world_maintenance_interval_seconds
    ):
        return True
    if _maintenance_due(
        "world_simulation", settings.world_sim_interval_seconds
    ):
        return True
    if _maintenance_due(
        "action_retry", settings.action_maintenance_interval_seconds
    ):
        return True
    if _maintenance_due(
        "action_schedule", settings.action_maintenance_interval_seconds
    ):
        return True
    if settings.action_outbox_enabled:
        if outbox_repository.list_pending(limit=1):
            return True
    if _maintenance_due("ledger_digest", 60):
        return True
    if _maintenance_due("ledger_alert", 60):
        return True
    return _maintenance_due("trigger_reconcile", _RECONCILE_INTERVAL_SECONDS)


def _mark_maintenance(kind: str) -> None:
    _maintenance_last[kind] = time.monotonic()


async def _safe_sync_call(kind: str, func) -> dict:
    try:
        result = await asyncio.to_thread(func)
        if isinstance(result, dict):
            return {"step": kind, "status": "ok", **result}
        return {"step": kind, "status": "ok", "result": result}
    except Exception as exc:
        logger.exception("维护步骤失败：%s", kind)
        return {"step": kind, "status": "error", "error": exc.__class__.__name__}


def _json_safe(value):
    """维护步返回值归一为 JSON 可序列化形态。

    `loop_runs.steps` 是 JSON 列，而各维护步的返回值形态不一：`world_maintenance`
    返回 int、`action_retry` 传 dict，`world_simulation` 则把
    `run_simulation_maintenance` 的返回值原样带回——那是一串 `TimeAdvanceResult`
    （dataclass，含 `datetime` 字段），直接落库即
    `TypeError: Object of type TimeAdvanceResult is not JSON serializable`。
    在唯一写入路径统一收口，后续新增维护步不必各自处理。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_safe(getattr(value, field.name)) for field in fields(value)
        }
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _json_safe(dump(mode="json"))
    return str(value)


def _record_maintenance_run(
    kind: str, steps, now: datetime, status: str = "done"
) -> None:
    run = loop_run_repository.create_run(
        user_id=None, kind=kind, reason="interval_due", now=now
    )
    step_list = steps if isinstance(steps, list) else [steps]
    loop_run_repository.finish_run(
        run.id, status=status, steps=_json_safe(step_list), now=now
    )
