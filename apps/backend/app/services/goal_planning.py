"""V2.0.0 AUT-002 Planning 执行器：供给装配 + 可执行性校验闸 + 规划 job。

供给装配（Runtime Flow 第一环「目标创建」的实体化，纯规则 0 LLM）：
Development 调制 / Relationship Pattern / 编排投影的 World 高显著事实
三来源产出层级 goal 候选，创建后立即 enqueue 规划 job。

规划本体（后台 job，main 档，唯一 LLM 面）：前置闸（attempt 封顶/在途
幂等）→ LLM 结构化提案 → 结构闸（判据白名单/能力对齐/深度数量封顶）→
validated→active（旧 active 版本 superseded 留痕）；拒绝/失败全 trace，
不静默降级执行。World 事实由编排方传入 payload（GAP-AUT-02 编排投影），
本模块零 World/Action 查询。
"""

import json
import logging
import time
from datetime import datetime

from pydantic import BaseModel, Field

from app.chains.structured import build_structured_chain
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError, get_settings
from app.models.action import ACTION_TYPES
from app.models.goal import (
    CRITERION_METRIC_PATHS,
    CRITERION_TYPES,
    GOAL_DESCRIPTION_MAX_LENGTH,
    GoalPlanRecord,
    GoalRecord,
    validate_sub_goals,
)
from app.repositories import (
    background_job_repository,
    goal_repository,
    memory_repository,
)
from app.services.development import aggregate as development_aggregate

logger = logging.getLogger(__name__)

STEP_NAME = "goal_planning"
JOB_TYPE_PLANNING = "goal_planning"

TRIGGER_CREATED = "goal_created"
TRIGGER_BLOCKED = "goal_blocked"
TRIGGER_REPLAN = "goal_replan"
PLANNING_TRIGGERS = (TRIGGER_CREATED, TRIGGER_BLOCKED, TRIGGER_REPLAN)

_LLM_RETRY_ATTEMPTS = 2
_LLM_RETRY_BACKOFF_SECONDS = 1.0

REASON_ATTEMPT_CAP = "attempt_cap"
REASON_COUNT_EXCEEDED = "subgoal_count_exceeded"
REASON_CAPABILITY_UNALIGNED = "capability_unaligned"
REASON_INVALID_SHAPE = "invalid_sub_goal_shape"
REASON_LLM_FAILED = "llm_failed"

_WORLD_IMPORTANCE_HIGH = "high"
_WORLD_TITLE_MAX_CHARS = GOAL_DESCRIPTION_MAX_LENGTH - 2


class PlanningProposal(BaseModel):
    sub_goals: list[dict] = Field(default_factory=list)


def _template(settings, domain: str) -> str:
    templates = json.loads(settings.v2_autonomy_supply_templates_json)
    return templates.get(domain, "")


def collect_candidates(user_id: str, world_facts: dict | None = None) -> list[dict]:
    """三来源规则候选：Development 调制 / Relationship Pattern / World 高显著
    事实与显著度记忆（World 事件的 Memory 投影）；world 事实由编排投影传入。"""
    settings = get_settings()
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _append(layer: str, domain: str, description: str, origin: str) -> None:
        if not description or len(description) > GOAL_DESCRIPTION_MAX_LENGTH:
            return
        key = (domain, description)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "layer": layer,
                "domain": domain,
                "description": description,
                "priority": 3,
                "origin": origin,
            }
        )

    overlay = development_aggregate.read_overlay(user_id)
    if overlay is not None and overlay.goal_weights:
        max_weight = max(
            (abs(float(value)) for value in overlay.goal_weights.values()),
            default=0.0,
        )
        if max_weight >= settings.v2_autonomy_supply_personal_min_weight:
            _append(
                "long_term",
                "personal",
                _template(settings, "personal"),
                "development_modulation",
            )

    try:
        from app.services import relationship_patterns as relationship_pattern_service

        patterns, _ = relationship_pattern_service.read_relationship_patterns(user_id)
    except Exception:
        logger.exception("关系模式读取失败，供给来源跳过")
        patterns = []
    if patterns:
        strongest = max(patterns, key=lambda pattern: pattern.strength)
        if strongest.strength >= settings.v2_autonomy_supply_relationship_min_strength:
            _append(
                "long_term",
                "relationship",
                _template(settings, "relationship"),
                f"relationship_pattern:{strongest.key}",
            )

    for event in (world_facts or {}).get("salient_events") or []:
        if event.get("importance") != _WORLD_IMPORTANCE_HIGH:
            continue
        title = str(event.get("title") or "").strip()[:_WORLD_TITLE_MAX_CHARS]
        if title:
            _append("short_term", "world", f"跟进{title}", "world_event")

    try:
        salient = memory_repository.list_top_salience(
            user_id,
            min_salience=settings.v2_autonomy_supply_world_min_salience,
            limit=3,
        )
    except Exception:
        logger.exception("显著度记忆快查失败，world 记忆来源跳过")
        salient = []
    for row in salient:
        if row.type not in ("experience", "milestone_event"):
            continue
        title = row.content.strip()[:_WORLD_TITLE_MAX_CHARS]
        if title:
            _append("short_term", "world", f"跟进{title}", "salient_memory")

    return candidates


def materialize(
    user_id: str, world_facts: dict | None = None, now: datetime | None = None
) -> dict:
    """候选去重落库并触发规划；long_term 每 (layer, domain) 活跃唯一。"""
    settings = get_settings()
    if not settings.v2_autonomy_advanced_enabled:
        return {"status": "skipped", "skip_reason": "flag_disabled", "created": 0}
    now = now or datetime.now()
    active_layered = goal_repository.list_layered_active(user_id)
    long_term_keys = {
        (goal.layer, goal.domain) for goal in active_layered if goal.layer == "long_term"
    }
    content_keys = {(goal.domain, goal.description) for goal in active_layered}
    created: list[str] = []
    enqueued = 0
    for candidate in collect_candidates(user_id, world_facts):
        if candidate["layer"] == "long_term":
            if (candidate["layer"], candidate["domain"]) in long_term_keys:
                continue
        elif (candidate["domain"], candidate["description"]) in content_keys:
            continue
        record = goal_repository.create_hierarchical_goal(
            user_id,
            candidate["layer"],
            candidate["domain"],
            candidate["description"],
            candidate["priority"],
        )
        created.append(record.id)
        if candidate["layer"] == "long_term":
            long_term_keys.add((record.layer, record.domain))
        content_keys.add((record.domain, record.description))
        if enqueue_planning(user_id, record.id, TRIGGER_CREATED, world_facts):
            enqueued += 1
    return {"status": "ok", "created": created, "enqueued": enqueued}


def enqueue_planning(
    user_id: str,
    goal_id: str,
    trigger: str,
    world_facts: dict | None = None,
) -> bool:
    if trigger not in PLANNING_TRIGGERS:
        raise ValueError(f"非法规划触发器：{trigger!r}")
    version_hint = goal_repository.count_plans(goal_id) + 1
    idempotency_key = f"{JOB_TYPE_PLANNING}:{goal_id}:{trigger}:{version_hint}"
    payload = {
        "goal_id": goal_id,
        "user_id": user_id,
        "trigger": trigger,
        "world_facts": world_facts or {},
    }
    return background_job_repository.enqueue_job(
        JOB_TYPE_PLANNING, payload, idempotency_key
    )


def run_planning_jobs() -> int:
    """job handler（无参签名对齐 _JOB_HANDLERS）：处理本类型 running 载荷。"""
    rows = background_job_repository.list_jobs(
        JOB_TYPE_PLANNING, status="running", limit=100
    )
    payloads = [dict(row.payload or {}) for row in rows]
    processed = 0
    for payload in payloads:
        goal_id = payload.get("goal_id")
        if not goal_id:
            continue
        outcome = plan_goal(
            goal_id,
            payload.get("trigger") or TRIGGER_CREATED,
            world_facts=payload.get("world_facts") or {},
        )
        if outcome.get("status") == "ok":
            processed += 1
    return processed


def register_runtime() -> None:
    """Flag ON 编排层注册：job handler（规划本体）。"""
    from app.services.memory2 import job_worker

    job_worker.register_job_type(JOB_TYPE_PLANNING, run_planning_jobs)


def _build_messages(goal: GoalRecord, overlay, world_facts: dict, settings) -> list[tuple]:
    system = (
        "你是角色目标规划器，把一个目标拆解为可执行的 Sub-Goal 步骤，只输出 JSON。"
        "每步字段：index(从1连续)、description(不超过"
        f"{GOAL_DESCRIPTION_MAX_LENGTH}字)、capability(只允许："
        f"{'、'.join(ACTION_TYPES)})、params(对象)、criteria(对象)、"
        "depends_on(前置步骤序号列表，不允许前向)、parent_index(可空，"
        "只允许引用更早的顶层步骤)。"
        f"criteria.type 只允许：{'、'.join(CRITERION_TYPES)}；"
        "action_succeeded 需 capability；field_equals 需 source(world|state|memory)"
        "/path/value；threshold_reached 需 source/path/op(>=|<=)/value，path 只允许 "
        f"{'、'.join(CRITERION_METRIC_PATHS)}；all_of/any_of 需非空 children 且只允许一层。"
        f"全树步骤数量不超过 {settings.v2_autonomy_subgoal_max_count}，嵌套不超过两层。"
        "每步必须是角色能真实执行或可客观判定的动作，不得输出无法验证的愿望。"
    )
    brief = goal
    constraints = {
        "goal": {
            "description": brief.description,
            "layer": brief.layer,
            "domain": brief.domain,
            "priority": brief.priority,
        },
        "development_constraints": (
            {
                "care_hint": overlay.care_hint,
                "goal_weights": overlay.goal_weights,
            }
            if overlay is not None
            else {}
        ),
        "world_facts": world_facts or {},
    }
    human = json.dumps(constraints, ensure_ascii=False, default=str)
    return [("system", system), ("human", human)]


def _resolve_llm(settings):
    profile = settings.v2_autonomy_planning_llm_profile or None
    try:
        return get_llm(profile)
    except SettingsError:
        return get_llm(None)


def _ask_llm_with_retry(messages: list[tuple], settings) -> PlanningProposal:
    llm = _resolve_llm(settings)
    chain = build_structured_chain(messages, PlanningProposal, llm)
    last_exc: Exception | None = None
    for attempt in range(_LLM_RETRY_ATTEMPTS):
        if attempt:
            time.sleep(_LLM_RETRY_BACKOFF_SECONDS)
        try:
            result = chain.invoke({})
            if isinstance(result, PlanningProposal):
                return result
            return PlanningProposal.model_validate(result)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "规划 LLM 调用失败（第 %d 次）：%s", attempt + 1, exc.__class__.__name__
            )
    assert last_exc is not None
    raise last_exc


def _persist_trace(trace, user_id: str) -> None:
    from app.application import observability
    from app.models.observability import TraceKind

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
        logger.exception("规划 trace 落库失败，已忽略")


def plan_goal(goal_id: str, trigger: str, world_facts: dict | None = None) -> dict:
    """单 goal 规划：前置闸 → LLM → 结构闸 → [validated→active | rejected]。"""
    from app.services.trace_collector import TurnTraceSession

    settings = get_settings()
    if not settings.v2_autonomy_advanced_enabled:
        return {"status": "skipped", "skip_reason": "flag_disabled"}
    goal = goal_repository.get_goal(goal_id)
    if goal is None or goal.status != "active" or goal.layer is None:
        return {"status": "skipped", "skip_reason": "goal_not_plannable"}
    attempts = goal_repository.count_plans(goal_id)
    if attempts >= settings.v2_autonomy_planning_max_attempts:
        trace = TurnTraceSession()
        trace.record(
            STEP_NAME,
            0.0,
            "rejected",
            reason=REASON_ATTEMPT_CAP,
            goal_id=goal_id,
            attempts=attempts,
        )
        _persist_trace(trace, goal.user_id)
        return {"status": "rejected", "reason": REASON_ATTEMPT_CAP}
    if trigger == TRIGGER_CREATED:
        in_flight = any(
            plan.status in ("draft", "validated", "active")
            for plan in goal_repository.list_plans(goal_id)
        )
        if in_flight:
            return {"status": "skipped", "skip_reason": "plan_exists"}

    started = time.perf_counter()
    trace = TurnTraceSession()
    overlay = development_aggregate.read_overlay(goal.user_id)
    try:
        messages = _build_messages(goal, overlay, world_facts or {}, settings)
        proposal = _ask_llm_with_retry(messages, settings)
        specs = validate_sub_goals(
            proposal.sub_goals, max_depth=settings.v2_autonomy_subgoal_max_depth
        )
        if len(specs) > settings.v2_autonomy_subgoal_max_count:
            raise ValueError(REASON_COUNT_EXCEEDED)
        unaligned = next(
            (spec.capability for spec in specs if spec.capability not in ACTION_TYPES),
            None,
        )
        if unaligned is not None:
            raise ValueError(f"{REASON_CAPABILITY_UNALIGNED}:{unaligned}")
    except ValueError as exc:
        reason = str(exc) or REASON_INVALID_SHAPE
        plan = _create_rejection(goal_id, attempts, reason)
        trace.record(
            STEP_NAME,
            (time.perf_counter() - started) * 1000,
            "rejected",
            reason=reason,
            goal_id=goal_id,
            plan_id=plan.id if plan else None,
        )
        _persist_trace(trace, goal.user_id)
        return {"status": "rejected", "reason": reason}
    except Exception as exc:
        trace.record(
            STEP_NAME,
            (time.perf_counter() - started) * 1000,
            "error",
            error=exc.__class__.__name__,
            reason=REASON_LLM_FAILED,
            goal_id=goal_id,
        )
        _persist_trace(trace, goal.user_id)
        return {"status": "llm_failed", "error": exc.__class__.__name__}

    version = attempts + 1
    now = datetime.now()
    plan = goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status="validated",
            sub_goals=specs,
            created_at=now,
            updated_at=now,
        )
    )
    for existing in goal_repository.list_plans(goal_id):
        if existing.id != plan.id and existing.status == "active":
            goal_repository.set_plan_status(existing.id, "superseded")
    goal_repository.set_plan_status(plan.id, "active")
    trace.record(
        STEP_NAME,
        (time.perf_counter() - started) * 1000,
        "ok",
        goal_id=goal_id,
        plan_id=plan.id,
        version=version,
        steps=[spec.index for spec in specs],
        capabilities=sorted({spec.capability for spec in specs}),
    )
    _persist_trace(trace, goal.user_id)
    return {"status": "ok", "plan_id": plan.id, "version": version}


def _create_rejection(goal_id: str, attempts: int, reason: str) -> GoalPlanRecord | None:
    now = datetime.now()
    try:
        return goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal_id,
                version=attempts + 1,
                status="rejected",
                rejection_reason=reason[:200],
                created_at=now,
                updated_at=now,
            )
        )
    except Exception:
        logger.exception("rejected 规划行落库失败（goal=%s）", goal_id)
        return None
