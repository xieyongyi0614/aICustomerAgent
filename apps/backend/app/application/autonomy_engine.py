"""V7 AutonomyEngine（architecture.md §2 / scheduler.md §2）。

tick：候选用户枚举 → TriggerEvaluator → AutonomyPolicy → 入队 → Executor 同 tick 执行。
复用 V6 goal_service.select 与 V6.5 行为层，不绕行（architecture.md §4）。

V2.4.0 TOOL-006：总闸开启时自治 tick 首次实传 `capabilities=surface.tool_ids`
（关闭断层 B7；off 时保持 `None` 原状），并把有界工具事实段并入 `action_facts`
（`PolicySnapshot.tool_facts`）。**编排关系不变**：自治只产出意图（ActionIntent），
执行仍经既有 `action_engine.run_action_planning`（Action = Intent，Tool = Execution）。

P2-3：工具面解析降级不再静默——异常次数记入进程级 `tool_surface_degrade_count()`
（经 `/debug/tools` 的 `tool_surface_degrade_count` 字段暴露），返回 `None` + 日志的行为不变。

V2.5.0 PLAN-007：`plan_facts`（计划运行态只读事实段）在**既有行动事实收集处同源扩展、
一处装配**（`_collect_plan_facts` 的唯一调用点），关闭断层 B9——自治策略由此看得见
「用户身上还有一个进行中的计划」。**编排关系不变**：`tick` 语句序列零改动（形状快照对照）、
`_produce_autonomy_action` 原样复用、计划事实只读（`goal_repository.list_active_plans` +
`PlanScheduler` 纯函数 + `decision_repository` 只读投影），子闸 off / 无计划 / 装配异常一律
降级为 `{}` 且**不阻塞 tick**。
"""

import logging
import time
import uuid
from datetime import datetime
from types import SimpleNamespace

from app.core.settings import get_settings
from app.application import observability, world_engine
from app.models.autonomy import ProactiveAction, TriggerSignal
from app.models.observability import (
    DecisionKind,
    DecisionRecord,
    TraceKind,
    bound_extra,
)
from app.models.tool import ToolBinding, ToolSurface
from app.repositories import (
    conversation_repository,
    decision_repository,
    goal_repository,
    proactive_repository,
)
from app.services import autonomy_policy
from app.services.goal import service as goal_service
from app.services.autonomy import executor as proactive_executor
from app.services.conversation import scene as scene_service
from app.services.conversation import state as state_service
from app.services.autonomy import trigger as trigger_evaluator
from app.services.planning import scheduler as plan_scheduler
from app.services.observability.collector import TurnTraceSession, get_trace_collector
from app.application.action_engine import collect_facts, run_action_planning
from app.application.chat_pipeline import active_generations
from app.character.asuna.action import (
    PROACTIVE_ACTION_MAP,
    build_autonomy_action_params,
)
from app.character.asuna.tool import RUN_KIND_AUTONOMOUS_TICK
from app.models.action import ActionIntent
from app.repositories import action_repository, relationship_milestone_repository
from app.services.relationship import patterns as relationship_pattern_service
from app.services.tool.context import ToolContext
from app.services.tool.registry import get_tool_registry
from app.services.tool.surface import ToolSelector, ToolSurfaceResolver

logger = logging.getLogger(__name__)

_DATETIME_MIN = datetime(1970, 1, 1)
_ACTION_FACTS_CACHE: dict[str, dict] = {}

AUTONOMY_SOURCE = "autonomy"

AUTONOMY_TOOL_SURFACE_STEP = "autonomy_tool_surface"

TOOL_FACTS_AVAILABLE_LIMIT = 5
TOOL_FACTS_RECENT_FAILURE_LIMIT = 3
TOOL_FACTS_BREAKER_LIMIT = 3
TOOL_FACTS_RECORDS_SCAN_LIMIT = 50

_TOOL_STEP_FAILED_STATUS = "failed"

_TOOL_SURFACE_DEGRADE_COUNT = 0

PLAN_FACTS_ADVANCE_SCAN_LIMIT = 50
"""`last_advanced_at` 的审计扫描上限（既有 `decision_repository.search` 的既有 limit 语义）。"""

PLAN_ADVANCE_DECISION_ADVANCED = "advanced"
"""`PlanAdvance.decision` 的推进取值——必须落在 `app.models.plan` 的六值域内（用例对照）。"""


def tool_surface_degrade_count() -> int:
    """自治工具面降级计数（进程级，重启归零）：`_resolve_tick_capabilities` 解析异常的次数。

    只计数、不改行为——降级仍返回 `None` + 日志。**总闸 off（注册表缺失 → `None`）不计入**：
    那是设计路径（断层 B7 原状）而非降级，计入会让指标失去意义。
    """
    return _TOOL_SURFACE_DEGRADE_COUNT


def reset_tool_surface_degrade_count() -> None:
    """计数器归零（测试隔离用；生产无调用方）。"""
    global _TOOL_SURFACE_DEGRADE_COUNT
    _TOOL_SURFACE_DEGRADE_COUNT = 0


def _record_tool_surface_degrade() -> None:
    global _TOOL_SURFACE_DEGRADE_COUNT
    _TOOL_SURFACE_DEGRADE_COUNT += 1


def _autonomy_tool_context(user_id: str, now: datetime | None = None) -> ToolContext:
    """自治来源 ToolContext（只读快照）：世界事实维度留空（TOOL-007 装配），
    工具面投影据此降级为不裁剪那些维度（TOOL-004 E5/E14）。"""
    return ToolContext(
        user_id=user_id,
        now=now,
        settings=get_settings(),
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        source=AUTONOMY_SOURCE,
    )


def resolve_autonomy_surface(
    user_id: str, now: datetime | None = None, ctx: ToolContext | None = None
) -> ToolSurface | None:
    """自治工具面（TOOL-006 §4.2）：总闸 off → None（调用方传 `capabilities=None`）。

    总闸 on → 按 `autonomous_tick` Profile 投影：Profile 维度剔除 `channel` 命名空间，
    日时段维度在 `late_night` 再剔除 `social` 标签（规则资产属 TOOL-004，本任务只消费）。
    """
    registry = get_tool_registry()
    if registry is None:
        return None
    return ToolSurfaceResolver(registry).resolve(
        RUN_KIND_AUTONOMOUS_TICK,
        ctx if ctx is not None else _autonomy_tool_context(user_id, now),
    )


def _autonomy_binding(action_type: str, now: datetime) -> ToolBinding | None:
    """`action_type` 在自治工具面内的工具绑定；不在面内 → None。

    工具面投影不读 `user_id`（TOOL-004 规则只读 source / world / scene /
    relationship 维度），故以无用户自治上下文解析；
    TOOL-007 装配用户维度世界事实后，此处须改为按用户解析（风险已登记）。
    """
    registry = get_tool_registry()
    if registry is None:
        return None
    surface = resolve_autonomy_surface("", now)
    if surface is None:
        return None
    intent = ActionIntent(
        action_type=action_type, confidence="confident", params={}, dedupe_key=""
    )
    return ToolSelector(registry).select(intent, surface)


def _recent_tool_failures(
    user_id: str, limit: int = TOOL_FACTS_RECENT_FAILURE_LIMIT
) -> list[dict]:
    """最近工具失败（执行台账 `action_records.steps` 是 `failure_kind` 的唯一落点）。

    记录按 `created_at` 倒序给出，步骤按序扫描；同一 `tool_id` 只保留最近一次，
    达到上限即停（确定性截断）。
    """
    failures: list[dict] = []
    seen: set[str] = set()
    for record in action_repository.list_records(user_id, limit=TOOL_FACTS_RECORDS_SCAN_LIMIT):
        for step in record.steps or []:
            tool_id = step.get("tool_id")
            failure_kind = (step.get("result") or {}).get("failure_kind")
            if not tool_id or failure_kind is None:
                continue
            if step.get("status") != _TOOL_STEP_FAILED_STATUS or tool_id in seen:
                continue
            seen.add(tool_id)
            failures.append({"tool_id": tool_id, "failure_kind": failure_kind})
            if len(failures) >= limit:
                return failures
    return failures


def collect_tool_facts(user_id: str, ctx: ToolContext | None = None) -> dict:
    """有界工具事实段（TOOL-006 §4.1）：`{available, recent_failures, breaker_open}`。

    任何异常 → `{}`（降级为空包 + 日志，不抛出、不阻塞 tick）；
    整体经既有 `observability.bound_extra` 预算裁剪（不新增预算机制）。
    """
    try:
        settings = get_settings()
        registry = get_tool_registry()
        surface = resolve_autonomy_surface(user_id, ctx=ctx)
        if surface is None:
            return {}
        health = registry.health()
        facts = {
            "available": list(surface.tool_ids)[:TOOL_FACTS_AVAILABLE_LIMIT],
            "recent_failures": _recent_tool_failures(user_id),
            "breaker_open": [
                tool_id for tool_id in sorted(health) if health[tool_id].tripped
            ][:TOOL_FACTS_BREAKER_LIMIT],
        }
        payload, _ = bound_extra(facts, settings.observability_step_extra_max_chars)
        return payload
    except Exception:
        logger.exception("工具事实收集失败，返回空包")
        return {}


def collect_tool_insights(user_id: str) -> dict:
    """工具效能 Insight 只读信号段（TOOL-009 §2.3）：`{count, notes, insights, ...}`。

    无 active Insight / 任何异常 → `{}`（降级为空包 + 日志，不阻塞 tick）；
    信号只读（`reflection.tool_feed` 无写方法），自治侧只把它当输入面追加理由。
    """
    try:
        from app.services.reflection import tool_feed

        return tool_feed.autonomy_signal(user_id)
    except Exception:
        logger.exception("工具效能 Insight 收集失败，返回空包")
        return {}


def _collect_action_facts(user_id: str) -> dict:
    try:
        facts = collect_facts(user_id)
    except Exception:
        logger.exception("行动事实收集失败，返回空包")
        return {}
    tool_facts = collect_tool_facts(user_id)
    if tool_facts:
        facts["tool_facts"] = tool_facts
    tool_insights = collect_tool_insights(user_id)
    if tool_insights:
        facts["tool_insights"] = tool_insights
    return facts


def _latest_active_plan(user_id: str):
    """最近 `updated_at` 的 active 计划（多计划时取最新）。

    `goal_repository.list_active_plans` 按 `updated_at` 升序 + `id` 升序给出，
    故**末位即最新**且同刻可复现（确定性取值规则，不引入第二套排序）。
    """
    pairs = goal_repository.list_active_plans(user_id)
    return pairs[-1] if pairs else None


def _plan_schedule_context(user_id: str, now: datetime):
    """`PlanScheduler.blocked_reason` 的鸭子类型上下文（只读投影）。

    工具面解析失败即降级为「无面」（`blocked_reason` 随之不判 `off_surface`）——
    计划事实的装配不得因工具系统不可用而失败。
    """
    try:
        surface = resolve_autonomy_surface(user_id, now)
    except Exception:
        logger.exception("自治工具面解析失败，计划阻塞判定按无面处理")
        surface = None
    return SimpleNamespace(now=now, settings=get_settings(), tool_surface=surface)


def _blocked_steps(plan, user_id: str, now: datetime) -> int:
    """被阻塞计数（§4.2.1「`PlanScheduler.blocked_reason` 计数」）：
    `0` = 有可执行步，`1` = 三类阻塞之一（`off_surface` / `cooldown` / `predecessor_failed`）。

    该纯函数对**一份计划**给出单一首个可判因（不是逐步计数），故本字段恒为 0 / 1——
    有界且可判定，不臆造第二套阻塞判定。
    """
    reason = plan_scheduler.PlanScheduler.blocked_reason(
        plan, _plan_schedule_context(user_id, now)
    )
    return 0 if reason is None else 1


def _last_advanced_at(user_id: str, goal_id: str) -> str | None:
    """最近一次 `advanced` 的推进时刻（`PlanAdvance.at`，既有 `decision_records` 只读投影）。

    取扫描窗内命中行的**最大时刻**而非首行——审计行的 `created_at` 是落库时刻（同一批
    推进可能同秒落库），按 `at` 求最大才是「最近一次推进」的确定性口径；无命中 → `None`
    （降级为「无最近推进」，不影响其余字段）。
    """
    moments = [
        _advance_moment(record.input_snapshot or {}, record.created_at)
        for record in decision_repository.search(
            user_id=user_id,
            kind=DecisionKind.GOAL_LIFECYCLE,
            limit=PLAN_FACTS_ADVANCE_SCAN_LIMIT,
        )
        if _is_advance_for(record, goal_id)
    ]
    return max(moments).isoformat() if moments else None


def _is_advance_for(record, goal_id: str) -> bool:
    """是否为目标 `goal_id` 的一次 `advanced` 推进审计。"""
    if record.decision != PLAN_ADVANCE_DECISION_ADVANCED:
        return False
    return (record.input_snapshot or {}).get("goal_id") == goal_id


def _advance_moment(snapshot: dict, fallback: datetime | None) -> datetime:
    """审计行的推进时刻：`PlanAdvance.at`（ISO 字符串）优先，缺省回退落库时刻。"""
    reported = snapshot.get("at")
    if isinstance(reported, str) and reported:
        try:
            return datetime.fromisoformat(reported)
        except ValueError:
            logger.warning("推进审计的时刻不可解析，回退落库时刻：%s", reported)
    return fallback if fallback is not None else datetime.min


def _collect_plan_facts(user_id: str, now: datetime | None = None) -> dict:
    """有界计划事实段（PLAN-007 §4.2.1 / §6.2）：固定七键、单目标、只读、失败降级为空包。

    与既有事实段同款纪律：无 active 计划 → `{}`；任何异常 → `{}` + 日志，**不阻塞
    tick**；整体经既有 `observability.bound_extra` 预算裁剪（不新增预算机制）。
    子闸 `plan_autonomy_enabled` 已随开关体系删除，本段常开。字段契约见
    `autonomy_policy.PLAN_FACTS_KEYS`（唯一声明处）。
    """
    try:
        settings = get_settings()
        pair = _latest_active_plan(user_id)
        if pair is None:
            return {}
        goal, plan = pair
        moment = now or datetime.now()
        current = plan_scheduler.PlanScheduler.current_step(plan)
        facts = {
            "active_goal_id": goal.id,
            "plan_version": plan.version,
            "current_step": None if current is None else current.index,
            "current_action_type": None if current is None else current.capability,
            "steps_total": len(plan.sub_goals),
            "blocked_steps": _blocked_steps(plan, user_id, moment),
            "last_advanced_at": _last_advanced_at(user_id, goal.id),
        }
        payload, _ = bound_extra(facts, settings.observability_step_extra_max_chars)
        return payload
    except Exception:
        logger.exception("计划事实收集失败，返回空包")
        return {}


def _params_for_autonomy_action(action_type: str, now: datetime) -> dict:
    """自治产行动参数模板（autonomy-integration.md §4）；无模板返回空参。"""
    return build_autonomy_action_params(
        action_type, now, _autonomy_binding(action_type, now)
    )


def _autonomy_action_today(user_id: str, now: datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    records = action_repository.list_records(user_id, limit=200)
    return sum(
        1
        for r in records
        if r.source in ("autonomy", "plan")
        and r.created_at is not None
        and r.created_at >= start
    )


async def _produce_autonomy_action(
    verdict, user_id: str, session_id: str, now: datetime
) -> bool:
    """自治产行动分支（autonomy-integration.md §4）：默认关，仅命中开启才求值。"""
    settings = get_settings()
    if not settings.autonomy_action_enabled:
        return False

    action_type = PROACTIVE_ACTION_MAP.get(verdict.intention or "")
    if action_type is None:
        return False
    if _autonomy_action_today(user_id, now) >= settings.autonomy_action_daily_limit:
        logger.info("自治产行动日额度已满：%s", user_id)
        return False
    intent = ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=_params_for_autonomy_action(action_type, now),
        dedupe_key=f"autonomy:{action_type}:{now.date().isoformat()}",
    )
    record = await run_action_planning(
        user_id, intent, session_id=session_id, source="autonomy"
    )
    return record is not None


def _session_tail(messages, now: datetime) -> trigger_evaluator.SessionTail:
    last = messages[-1] if messages else None
    last_user = next((m for m in reversed(messages) if m.role == "human"), None)
    return trigger_evaluator.SessionTail(
        last_message_at=last.created_at if last is not None else None,
        last_message_role=last.role if last is not None else None,
        last_user_message_at=last_user.created_at if last_user is not None else None,
        last_user_message_id=str(last_user.id) if last_user is not None else None,
    )


def _snapshot_for(
    user_id: str, session_id: str, now: datetime, episode_start: datetime
):
    character, relationship = state_service.load_states(user_id)
    scene_state = scene_service.load(session_id)
    goals = [
        goal
        for goal in goal_repository.list_active(user_id)
        if goal.layer is None
    ]
    late_night_start = get_settings().goal_late_night_start
    late_night_end = get_settings().goal_late_night_end
    late_night = now.hour >= late_night_start or now.hour < late_night_end
    selected = goal_service.select(
        goals,
        tension=relationship.tension,
        user_emotion=state_service.load_last_user_emotion(user_id),
        character_mood=character.mood,
        character_intensity=character.intensity,
        scene_pending=False,
        late_night=late_night,
    )
    last_proactive_at, attempts = proactive_repository.aggregate_episode(
        user_id,
        episode_start=episode_start,
    )
    try:
        unlocks = relationship_milestone_repository.list_unlocks(user_id)
    except Exception:
        unlocks = ()
    relationship_patterns: tuple[str, ...] = ()
    try:
        patterns, _ = relationship_pattern_service.read_relationship_patterns(user_id)
        relationship_patterns = tuple(pattern.key for pattern in patterns)
    except Exception:
        logger.exception("关系模式读取失败，闸门参考为空")
    action_facts = _collect_action_facts(user_id)
    plan_facts = _collect_plan_facts(user_id, now)
    return autonomy_policy.PolicySnapshot(
        generating=active_generations.get(user_id, False),
        has_active_action=proactive_repository.has_non_terminal(user_id),
        last_proactive_at=last_proactive_at,
        attempt_count=attempts,
        intimacy=relationship.intimacy,
        tension=relationship.tension,
        mood=character.mood,
        current_activity=(
            scene_state.current_activity if scene_state is not None else None
        ),
        selected_goal_type=selected.goal.type if selected.goal is not None else None,
        goal_degraded=selected.goal is None,
        extra_flags={"goal_id": selected.goal.id if selected.goal is not None else None},
        world_facts=world_engine.collect_facts(user_id),
        action_facts=action_facts,
        tool_facts=action_facts.get("tool_facts") or {},
        tool_insights=action_facts.get("tool_insights") or {},
        plan_facts=plan_facts,
        respect=getattr(relationship, "respect", 0.6),
        comfort=getattr(relationship, "comfort", 0.6),
        conflict_status=getattr(relationship, "conflict_status", "none") or "none",
        neglect_active=bool(getattr(relationship, "neglect_active", False)),
        unlocks=unlocks,
        trust=relationship.trust,
        stage=relationship.stage,
        relationship_patterns=relationship_patterns,
    )


def _build_action(
    verdict, session_id: str, now: datetime, intention_override: str | None = None
) -> ProactiveAction:
    return ProactiveAction(
        id=uuid.uuid4().hex,
        user_id=verdict.trigger.user_id,
        session_id=session_id,
        trigger_type=verdict.trigger.type,
        dedupe_key=verdict.trigger.dedupe_key,
        goal_id=verdict.goal_id,
        intention=intention_override or verdict.intention or "check_in",
        reason=verdict.reason,
        created_at=now,
        updated_at=now,
    )


def _resolve_tick_capabilities(
    user_id: str, now: datetime, trace, tool_facts: dict | None = None
) -> list[str] | None:
    """自治 tick 的工具面（TOOL-006 §5 Step1）：总闸 on 实传 `surface.tool_ids`（可为空，E1）；
    off 或无 registry → None（断层 B7 原状，逐字节一致）。

    工具面与工具事实经既有 `trace.record()` 落 `runtime_traces.steps`（不新建观测表）；
    解析异常降级为 None + 日志，不阻塞 tick（异常次数记入进程级
    `tool_surface_degrade_count()`——降级不再静默）。
    """
    started = time.perf_counter()
    try:
        surface = resolve_autonomy_surface(user_id, now)
    except Exception:
        logger.exception("自治工具面解析失败，capabilities 退化为 None")
        _record_tool_surface_degrade()
        return None
    if surface is None:
        return None
    payload, _ = bound_extra(
        {
            "run_kind": surface.run_kind,
            "tool_ids": list(surface.tool_ids),
            "excluded": [dict(item) for item in surface.excluded],
            "surface_hash": surface.surface_hash,
            "tool_facts": tool_facts or {},
        },
        get_settings().observability_step_extra_max_chars,
    )
    trace.record(
        AUTONOMY_TOOL_SURFACE_STEP,
        (time.perf_counter() - started) * 1000,
        "ok",
        **payload,
    )
    return list(surface.tool_ids)


def _pipeline_intention(
    verdict,
    user_id: str,
    now: datetime,
    capabilities: list[str] | None = None,
    tool_insights: list[dict] | None = None,
) -> tuple[str | None, dict | None]:
    """AGENT-004 统一决策管线接线：Flag 开启时五段管线裁决主动意图，
    候选审计落 decision_records.candidates；管线失败回退 verdict 原值。

    TOOL-006：`capabilities` 由调用方传入自治工具面（off 时为 None，管线行为不变）。
    TOOL-009：`tool_insights` 为只读反哺信号（缺省 None，interest 维行为不变）。
    """
    try:
        from app.application import agent_state_context
        from app.services import decision_pipeline
        from app.services.goal import stack as goal_stack_service

        stack = goal_stack_service.evaluate_stack(user_id, now)
        facts = world_engine.collect_facts(user_id)
        world_impacts = facts.get("impacts")
        world_schedule = {
            "current_block": facts.get("current_block"),
            "part_of_day": facts.get("part_of_day"),
        }
        result = decision_pipeline.run_pipeline(
            stack=stack,
            snapshot=agent_state_context.get_snapshot(),
            trigger_intention=verdict.intention,
            trigger_goal_id=verdict.goal_id,
            capabilities=capabilities,
            run=None,
            now=now,
            world_impacts=world_impacts,
            world_schedule=world_schedule,
            tool_insights=tool_insights,
        )
        return result.intention, result.audit
    except Exception:
        logger.exception("决策管线失败，回退 verdict 原值")
        return None, None


def reset_episode(user_id: str) -> None:
    """用户发言开启新 episode；预留钩子位（dedupe 幂等由 repository 兜底）。"""


def _decision_record(
    verdict,
    signal,
    snapshot,
    user_id: str,
    session_id: str,
    action_id=None,
    outcome=None,
    candidates=None,
) -> DecisionRecord:
    audit_fields: dict = {
        "generating": snapshot.generating,
        "has_active_action": snapshot.has_active_action,
        "last_proactive_at": (
            str(snapshot.last_proactive_at) if snapshot.last_proactive_at else None
        ),
        "attempt_count": snapshot.attempt_count,
        "intimacy": snapshot.intimacy,
        "tension": snapshot.tension,
        "mood": snapshot.mood,
        "current_activity": snapshot.current_activity,
        "selected_goal_type": snapshot.selected_goal_type,
        "goal_degraded": snapshot.goal_degraded,
        "goal_id": snapshot.extra_flags.get("goal_id"),
        "relationship_patterns": list(snapshot.relationship_patterns),
    }
    if snapshot.tool_facts:
        audit_fields["tool_facts"] = snapshot.tool_facts
    if snapshot.plan_facts:
        audit_fields["plan_facts"] = snapshot.plan_facts
    payload, _ = bound_extra(
        audit_fields, get_settings().observability_step_extra_max_chars
    )
    return DecisionRecord(
        kind=DecisionKind.PROACTIVE_AUTONOMY,
        user_id=user_id,
        conversation_id=session_id,
        action_id=action_id,
        trigger=signal.type,
        input_snapshot=payload,
        decision=verdict.decision,
        reason=verdict.reason,
        candidates=candidates,
    )


def _record_decision(**kwargs) -> None:
    try:
        observability.on_decision(_decision_record(**kwargs))
    except Exception:
        logger.exception("主动决策记录失败，已忽略")


async def _process_user(user_id: str, llm, now: datetime) -> str | None:
    conversation = conversation_repository.get_latest_for_user(user_id)
    if conversation is None:
        return None
    messages = conversation_repository.get_recent_messages(conversation.id, limit=5)
    tail = _session_tail(messages, now)
    _, attempts = proactive_repository.aggregate_episode(
        user_id,
        episode_start=tail.last_user_message_at or _DATETIME_MIN,
    )
    due_action = trigger_evaluator.poll_due_actions(user_id, now)
    if due_action is not None:
        signal: TriggerSignal | None = due_action
    else:
        followup = trigger_evaluator.poll_due_followup(user_id, now)
        if followup is not None:
            signal = followup
        else:
            signal = trigger_evaluator.evaluate_inactivity(
                tail,
                user_id,
                episode_attempts=attempts,
                now=now,
            )
    if signal is None:
        return None

    started = time.perf_counter()
    trace = TurnTraceSession()
    snapshot = _snapshot_for(
        user_id,
        conversation.id,
        now,
        episode_start=tail.last_user_message_at or _DATETIME_MIN,
    )
    verdict = autonomy_policy.evaluate(signal, snapshot, get_settings(), now)
    trace.record(
        "autonomy_policy",
        (time.perf_counter() - started) * 1000,
        verdict.decision,
        reason=verdict.reason,
        goal_id=verdict.goal_id,
        intention=verdict.intention,
    )
    logger.info(
        "主动行为裁决：user=%s decision=%s reason=%s",
        user_id,
        verdict.decision,
        verdict.reason,
    )
    if verdict.decision != "act" or verdict.goal_id is None:
        _record_decision(
            verdict=verdict,
            signal=signal,
            snapshot=snapshot,
            user_id=user_id,
            session_id=conversation.id,
        )
        observability.on_turn_finished(
            trace,
            turn_id=None,
            user_id=user_id,
            session_id=conversation.id,
            kind=TraceKind.AUTONOMY_TICK,
            drain_background=False,
        )
        return None

    produced_action = await _produce_autonomy_action(verdict, user_id, conversation.id, now)
    if produced_action:
        _record_decision(
            verdict=verdict,
            signal=signal,
            snapshot=snapshot,
            user_id=user_id,
            session_id=conversation.id,
        )
        observability.on_turn_finished(
            trace,
            turn_id=None,
            user_id=user_id,
            session_id=conversation.id,
            kind=TraceKind.AUTONOMY_TICK,
            drain_background=False,
        )
        return None

    capabilities = _resolve_tick_capabilities(user_id, now, trace, snapshot.tool_facts)
    intention_override, pipeline_audit = _pipeline_intention(
        verdict,
        user_id,
        now,
        capabilities=capabilities,
        tool_insights=(snapshot.tool_insights or {}).get("insights") or None,
    )
    action = _build_action(
        verdict, conversation.id, now, intention_override=intention_override
    )
    enqueued = proactive_repository.enqueue(action)
    _record_decision(
        verdict=verdict,
        signal=signal,
        snapshot=snapshot,
        user_id=user_id,
        session_id=conversation.id,
        action_id=action.id,
        outcome=None if enqueued else "enqueue_failed",
        candidates=pipeline_audit,
    )
    if not enqueued:
        return None
    active = proactive_repository.get_active(user_id, now)
    if active is None or active.id != action.id:
        return None
    observability_token = observability.current_trace.set(trace)
    try:
        delivered = await proactive_executor.execute(
            active, llm=llm, trace=trace, now=now
        )
    finally:
        observability.current_trace.reset(observability_token)
    if delivered is not None and delivered.status == "delivered":
        collector = get_trace_collector()
        collector.attach(trace, str(delivered.message_id))
        observability.on_turn_finished(
            trace,
            turn_id=str(delivered.message_id),
            user_id=user_id,
            session_id=conversation.id,
            kind=TraceKind.PROACTIVE,
            action_id=action.id,
            drain_background=False,
        )
        if signal.type == "action_due":
            event_id = signal.context.get("event_id")
            if event_id:
                trigger_evaluator.mark_action_reported(user_id, event_id)
        return delivered.message_id
    observability.on_turn_finished(
        trace,
        turn_id=None,
        user_id=user_id,
        session_id=conversation.id,
        kind=TraceKind.PROACTIVE,
        action_id=action.id,
        drain_background=False,
    )
    return None


async def tick(user_ids: list[str] | None = None, llm=None, now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    users = user_ids or conversation_repository.list_user_ids()
    delivered_ids: list[str] = []
    for user_id in users:
        try:
            message_id = await _process_user(user_id, llm, now)
        except Exception:
            logger.exception("autonomy tick 用户评估失败：%s", user_id)
            continue
        if message_id is not None:
            delivered_ids.append(message_id)
    return delivered_ids
