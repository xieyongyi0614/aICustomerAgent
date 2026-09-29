"""DevPolicy 编译器（DEV-002）：Insight → 行为参数调制的确定性纯函数，0 LLM。

编译输入 = active Insight 行（confidence 终值已由 REF-004 校准）；输出 =
ModulationProposal 列表（一个调制槽位一条），规则表全部 settings JSON 驱动、
离线可校准。规则未命中 → 空提案（不写 state，job 正常 done）。

strength = 源 Insight confidence 直接映射（不叠加累积——幅度=strength×预设封顶
天然满足「强化不超顶」，且时间序重放确定性成立）。仲裁比较器注入 aggregate：
strength 高者生效，同 strength 取源 Insight 较新者（architecture §3）。

运行时接线（register_runtime，main lifespan Flag ON 调用）：创建事件 → enqueue
development_compile job（幂等键 dev_compile:{insight_id}，MEM-009 协议）；handler
处理自身 job_type 的 running 载荷，非 active Insight 跳过。
"""

import json
import logging
import time

from app.core.db import BackgroundJobRow, InsightRow, SessionLocal
from app.core.settings import get_settings
from app.models.development import ModulationProposal
from app.models.reflection import Insight
from app.services.development import aggregate
from app.repositories import background_job_repository
from app.services.memory import job_worker as memory_job_worker
from app.services.reflection import lifecycle as reflection_lifecycle

logger = logging.getLogger(__name__)

STEP_NAME = "development_compile"

JOB_TYPE_COMPILE = "development_compile"

KEY_RESPONSE_STYLE_LENGTH = "response_style.length"
KEY_RESPONSE_STYLE_TONE = "response_style.tone"
KEY_BEHAVIOR_CARE_TOPICS = "behavior.care_topics"
KEY_BEHAVIOR_HABIT_CANDIDATES = "behavior.habit_candidates"
KEY_GOAL_USER_CARE_WEIGHT = "goal.user_care.weight"
KEY_AUTONOMY_TIME_PREFERENCE = "autonomy.time_preference"

STATUS_ACTIVE = "active"


def compile_insight(insight: Insight, settings=None) -> list[ModulationProposal]:
    """纯函数：同一 Insight 重复编译输出逐字节一致（E-DEV-01 幂等的源头）。"""
    settings = settings or get_settings()
    strength = insight.confidence
    statement = insight.statement
    base = {
        "kind": insight.type,
        "strength": strength,
        "insight_id": insight.id,
        "insight_created_at": insight.created_at,
    }
    if insight.type == "preference":
        return _compile_preference(base, statement, strength, settings)
    if insight.type == "belief":
        return _compile_belief(base, statement, settings)
    if insight.type == "pattern":
        return _compile_pattern(base, strength, settings)
    return []


def arbitration_comparator(proposal: dict, existing) -> bool:
    """strength 高者生效；同 strength 取源 Insight 较新者。"""
    if proposal["strength"] != existing.strength:
        return proposal["strength"] > existing.strength
    proposal_time = proposal.get("source_insight_created_at")
    existing_time = _insight_created_at(existing.source_insight_id)
    if proposal_time is None or existing_time is None:
        return False
    return proposal_time > existing_time


def apply_proposals(
    user_id: str, proposals: list[ModulationProposal], trace=None, now=None
) -> list[dict]:
    """逐提案经 aggregate 仲裁落库；返回逐 key 结果（trace 与评估消费）。"""
    results = []
    for proposal in proposals:
        outcome = aggregate.upsert_modulation(
            user_id,
            proposal.kind,
            proposal.key,
            proposal.value,
            proposal.strength,
            proposal.insight_id,
            source_insight_created_at=proposal.insight_created_at,
            comparator=arbitration_comparator,
            now=now,
            trace=trace,
        )
        results.append({"key": proposal.key, "outcome": outcome.outcome})
    return results


def on_insight_created(user_id: str, created: list[dict]) -> None:
    """创建事件回调：逐 Insight enqueue 编译 job（幂等键拦截重复事件）。"""
    for item in created or []:
        insight_id = item.get("insight_id")
        if not insight_id:
            continue
        background_job_repository.enqueue_job(
            JOB_TYPE_COMPILE,
            {"insight_id": insight_id},
            f"{JOB_TYPE_COMPILE}:{insight_id}",
        )


def run_compile_jobs() -> int:
    """job handler（无参签名对齐 _JOB_HANDLERS）：处理本类型 running 载荷。

    同 job_type 多 job 被同批认领时逐个处理（重复处理 = aggregate noop 幂等安全，
    僵尸回收重跑同理）；Insight 缺失或非 active → skip（job 正常 done）。
    """
    processed = 0
    with SessionLocal() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(
                BackgroundJobRow.job_type == JOB_TYPE_COMPILE,
                BackgroundJobRow.status == "running",
            )
            .all()
        )
        insight_ids = [
            (row.payload or {}).get("insight_id")
            for row in rows
        ]
    for insight_id in insight_ids:
        if not insight_id:
            continue
        if compile_insight_by_id(insight_id):
            processed += 1
    return processed


def compile_insight_by_id(insight_id: str, trace=None) -> bool:
    """单 Insight 编译落库；返回是否产出调制（含落败留痕）。"""
    started = time.perf_counter()
    with SessionLocal() as session:
        row = session.get(InsightRow, insight_id)
        if row is None or row.status != STATUS_ACTIVE:
            _trace(trace, started, insight_id=insight_id, reason="skip_inactive")
            return False
        insight = Insight(
            id=row.id,
            user_id=row.user_id,
            character_id=row.character_id,
            statement=row.statement,
            type=row.type,
            confidence=row.confidence,
            scope=row.scope,
            status=row.status,
            run_id=row.run_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    proposals = compile_insight(insight)
    if not proposals:
        _trace(trace, started, insight_id=insight_id, reason="no_rule")
        return False
    results = apply_proposals(insight.user_id, proposals, trace=trace)
    _trace(
        trace,
        started,
        insight_id=insight_id,
        reason="compiled",
        proposals=[item.key for item in proposals],
        results=results,
    )
    return True


def register_runtime() -> None:
    """Flag ON 编排层注册：job handler + 创建事件订阅（Reflection 不感知消费方）。"""

    memory_job_worker.register_job_type(JOB_TYPE_COMPILE, run_compile_jobs)
    reflection_lifecycle.register_insight_created_listener(on_insight_created)


def _compile_preference(base, statement: str, strength: float, settings) -> list:
    max_delta = settings.development_preference_max_token_delta
    proposals = []
    delta = -int(strength * max_delta)
    if delta < 0:
        proposals.append(
            _proposal(base, KEY_RESPONSE_STYLE_LENGTH, {"max_tokens_delta": delta})
        )
    tone = _first_keyword_rule(settings.development_preference_tone_rules_json, statement)
    if tone:
        proposals.append(_proposal(base, KEY_RESPONSE_STYLE_TONE, {"tone_hint": tone}))
    return proposals


def _compile_belief(base, statement: str, settings) -> list:
    proposals = []
    topics = _keyword_matches(settings.development_belief_topic_rules_json, statement)
    if topics:
        proposals.append(
            _proposal(
                base,
                KEY_BEHAVIOR_CARE_TOPICS,
                {"topics": topics, "care_hint": _care_hint(topics)},
            )
        )
    candidates = _keyword_values(
        settings.development_belief_habit_templates_json, statement
    )
    if candidates:
        proposals.append(
            _proposal(base, KEY_BEHAVIOR_HABIT_CANDIDATES, {"candidates": candidates})
        )
    return proposals


def _compile_pattern(base, strength: float, settings) -> list:
    max_delta = settings.development_pattern_goal_tier_delta_max
    goal_delta = round(strength * max_delta, 2)
    return [
        _proposal(base, KEY_GOAL_USER_CARE_WEIGHT, {"tier_delta": goal_delta}),
        _proposal(base, KEY_AUTONOMY_TIME_PREFERENCE, {"late_night_bias": round(strength, 2)}),
    ]


def _proposal(base, key: str, value: dict) -> ModulationProposal:
    return ModulationProposal(
        kind=base["kind"],
        key=key,
        value=value,
        strength=base["strength"],
        insight_id=base["insight_id"],
        insight_created_at=base.get("insight_created_at"),
    )


def _care_hint(topics: list[str]) -> str:
    return f"最近特别在意他的{('、'.join(topics))}，主动多问一句"


def _first_keyword_rule(rules_json: str, statement: str) -> str | None:
    rules = json.loads(rules_json)
    for keyword in sorted(rules, key=len, reverse=True):
        if keyword in statement:
            return rules[keyword]
    return None


def _keyword_matches(rules_json: str, statement: str) -> list[str]:
    rules = json.loads(rules_json)
    matched = [rules[keyword] for keyword in rules if keyword in statement]
    return list(dict.fromkeys(matched))


def _keyword_values(rules_json: str, statement: str) -> list[dict]:
    rules = json.loads(rules_json)
    seen: set[str] = set()
    matched: list[dict] = []
    for keyword in rules:
        if keyword not in statement:
            continue
        item = rules[keyword]
        frozen = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if frozen not in seen:
            seen.add(frozen)
            matched.append(item)
    return matched


def _insight_created_at(insight_id: str):
    if not insight_id:
        return None
    with SessionLocal() as session:
        row = session.get(InsightRow, insight_id)
        return row.created_at if row is not None else None


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
