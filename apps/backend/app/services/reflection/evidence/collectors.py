"""Reflection 证据聚合采集（只读 DB / trace 记录 / 聚合编排）。

由 `evidence.py` 拆分归位（services-reorganization-plan §十②，2026-09-30）；
窗构造与门槛数学见 `windows`（单向依赖 collectors → windows）。
"""

from app.character.asuna import evaluation as asuna_evaluation
from app.core.db import Memory, Message
from app.core.settings import get_settings
from app.engines.memory_conflict import _lcs_length, same_topic
from app.models.reflection import EvidenceMember
from app.models.reflection import EvidenceWindow
from app.models.reflection import PlanEvidenceWindow
from app.repositories import action_repository, goal_repository, memory_repository
from app.services.memory import sources as memory_sources
from datetime import datetime, timedelta
import time

from app.core.db import SessionLocal

from app.services.reflection.evidence.windows import (
    GROUP_KIND_ACTION,
    GROUP_KIND_CRITERIA,
    GROUP_KIND_FAILURE,
    GROUP_KIND_PLAN,
    GROUP_KIND_STEP,
    GROUP_KIND_TOOL,
    PLAN_EVIDENCE_STEP_NAME,
    PLAN_WINDOW_CRITERIA_DECIDABILITY,
    PLAN_WINDOW_STEP_FAILURE,
    PLAN_WINDOW_SUCCESS_RATE,
    PlanEvidencePackage,
    PlanStepFact,
    STATUS_SUCCEEDED,
    STATUS_TIMEOUT,
    STEP_NAME,
    STEP_STATUS_DONE,
    STEP_STATUS_FAILED,
    TOOL_EVIDENCE_MAX_MEMBERS,
    TOOL_EVIDENCE_OBSERVATION_PAIRS,
    TOOL_EVIDENCE_RECORD_SCAN_LIMIT,
    TOOL_EVIDENCE_SESSION_MESSAGE_LIMIT,
    TOOL_EVIDENCE_STEP_NAME,
    TOOL_EVIDENCE_WINDOW_DAYS,
    TOOL_FEEDBACK_FOLLOWUP_TURNS,
    ToolEvidencePackage,
    ToolExecutionFact,
    VISIBILITY_HYPOTHETICAL,
    _Cluster,
    _DEFAULT_SALIENCE,
    _UNKNOWN_GROUP_KEY,
    _accumulate_plan_step_group,
    _accumulate_rate_group,
    _build_window,
    _cosine,
    _criteria_kind,
    _followups_for,
    _is_revoke,
    _member_weight,
    _naive,
    _observations_digest,
    _parse_vector,
    _record_reference_time,
    _resolve_plan_facts,
    _revokes,
    _silence_eligible,
    _source_identity,
    _span_hours,
    _step_failure_kind,
    _step_observations,
    _step_status,
    _step_undecided,
    _topic_similarity,
    _window_digest,
    build_plan_evidence_windows,
    build_tool_evidence_windows,
    plan_evidence_id,
    plan_evidence_id_of,
    tool_evidence_id,
)

import logging

logger = logging.getLogger(__name__)


def _row_facts(memory_ids: list[str]) -> dict[str, dict]:
    """批量补读 UserMemory 未携带的生命周期字段（DB 为 SoT）。"""
    facts: dict[str, dict] = {}
    if not memory_ids:
        return facts
    with SessionLocal() as session:
        rows = (
            session.query(
                Memory.id,
                Memory.salience,
                Memory.embedding,
                Memory.visibility,
                Memory.source,
                Memory.source_ref,
                Memory.last_reinforced_at,
                Memory.created_at,
            )
            .filter(Memory.id.in_(memory_ids))
            .all()
        )
        for (
            memory_id,
            salience,
            embedding,
            visibility,
            source,
            source_ref,
            last_reinforced_at,
            created_at,
        ) in rows:
            facts[memory_id] = {
                "salience": salience,
                "embedding": _parse_vector(embedding),
                "visibility": visibility,
                "source": source,
                "source_ref": source_ref,
                "last_reinforced_at": _naive(last_reinforced_at),
                "created_at": _naive(created_at),
            }
    return facts

def aggregate_evidence_windows(
    user_id: str,
    character_id: str = "asuna",
    now: datetime | None = None,
    trace=None,
) -> list[EvidenceWindow]:
    """主入口：候选池 → 聚类 → 组统计 → 门槛判定；异常/空池返回空列表。

    PLAN-010 §4.1.3 ①：计划效能通道在此**扩源**（子闸 off 时零调用零读取）——三道闸、
    幂等入队与额度由既有 `trigger_for_user` 承担，故计划证据与用户证据走**完全相同**
    的一条路径（零豁免、零旁路）。
    """
    started = time.perf_counter()
    now = now or datetime.now()
    try:
        result = _aggregate(user_id, character_id, now)
    except Exception as exc:
        logger.exception("证据聚合异常，按无证据处理")
        _trace(trace, started, status="error", error=f"{exc.__class__.__name__}: {exc}")
        return []
    _trace(
        trace,
        started,
        status="ok",
        pool_size=result["pool_size"],
        clusters=result["clusters"],
        degraded=result["degraded"],
        windows=[_window_digest(window) for window in result["windows"]],
    )
    return result["windows"] + _plan_channel_windows(user_id, now, trace)

def _aggregate(user_id: str, character_id: str, now: datetime) -> dict:
    settings = get_settings()
    pool = _pool(user_id, character_id, now)
    vector_count = sum(1 for entry in pool if entry["vector"] is not None)
    degraded = "keyword_only" if pool and vector_count == 0 else None

    clusters: list[_Cluster] = []
    ordered = sorted(
        pool,
        key=lambda entry: (entry["salience"], entry["memory"].created_at),
        reverse=True,
    )
    for entry in ordered:
        memory = entry["memory"]
        vector = entry["vector"]
        member = EvidenceMember(
            memory_id=memory.id,
            content=memory.content.strip(),
            created_at=entry["created_at"],
            source=entry["source"],
            source_ref=entry["source_identity"],
            salience=entry["salience"],
            weight=_member_weight(entry["salience"], entry["reference"], now),
        )
        best: _Cluster | None = None
        best_score = -1.0
        for cluster in clusters:
            semantic = _cosine(vector, cluster.rep_vector)
            topic_sim = _topic_similarity(member.content, cluster.rep_content)
            matched = (
                semantic >= settings.reflection_cluster_cosine
                or same_topic(member.content, cluster.rep_content)
            )
            if not matched:
                continue
            score = max(semantic, topic_sim)
            if score > best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append(_Cluster(member, vector))
        else:
            best.add(member, vector)

    windows = [_build_window(cluster, degraded, settings) for cluster in clusters]
    windows.sort(key=lambda window: (-window.stats.member_count, -window.stats.coherence))
    return {"pool_size": len(pool), "clusters": len(clusters), "windows": windows, "degraded": degraded}

def _pool(user_id: str, character_id: str, now: datetime) -> list[dict]:
    settings = get_settings()
    memories = memory_repository.list_active(
        user_id, character_id, limit=settings.memory_candidate_pool_limit
    )
    facts = _row_facts([memory.id for memory in memories])
    window_start = now - timedelta(days=settings.reflection_window_days)
    candidates: list[dict] = []
    for memory in memories:
        fact = facts.get(memory.id, {})
        if fact.get("visibility") == VISIBILITY_HYPOTHETICAL:
            continue
        content = (memory.content or "").strip()
        if not content or memory.superseded_by is not None:
            continue
        reference = _naive(fact.get("last_reinforced_at")) or _naive(
            fact.get("created_at")
        ) or _naive(memory.created_at)
        if reference < window_start:
            continue
        candidates.append(
            {
                "memory": memory,
                "vector": fact.get("embedding"),
                "salience": fact.get("salience")
                if fact.get("salience") is not None
                else _DEFAULT_SALIENCE,
                "source": fact.get("source") or memory.source,
                "source_identity": _source_identity(memory.id, fact.get("source_ref")),
                "reference": reference,
                "created_at": _naive(fact.get("created_at")) or memory.created_at,
            }
        )
    return candidates

def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)

def _plan_channel_windows(
    user_id: str, now: datetime, trace
) -> list[PlanEvidenceWindow]:
    """计划通道扩源（PLAN-010 §4.1.3 ①）：子闸已随开关体系删除，扩源恒发生。

    计划窗**追加在既有窗口之后**：既有优先序纪律（既有窗口优先、取不到才回退）与
    `reflector._select_evidence` 的用户通道同款；本任务不改变既有窗口的相对顺序。
    计划窗的聚合异常只降级为空窗（不拉垮既有窗口）。
    """
    try:
        return list(aggregate_plan_evidence(user_id, now=now, trace=trace).windows)
    except Exception:
        logger.exception("计划效能证据窗聚合异常，降级为空窗：%s", user_id)
        return []

def aggregate_tool_usage(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    facts: list[ToolExecutionFact] | None = None,
) -> dict[str, dict]:
    """窗口一（工具使用效果）：按 tool_id 聚合成功 / 失败 / 超时 + 观测摘要（有界）。"""
    started = time.perf_counter()
    try:
        facts = _resolve_facts(user_id, now, window_days, facts)
        groups: dict[str, dict] = {}
        for fact in facts:
            entry = groups.setdefault(
                fact.tool_id,
                {
                    "group_kind": GROUP_KIND_TOOL,
                    "group_key": fact.tool_id,
                    "success_count": 0,
                    "failure_count": 0,
                    "timeout_count": 0,
                    "sample_observations": [],
                    "first_used_at": fact.observed_at,
                    "last_used_at": fact.observed_at,
                },
            )
            if fact.status == STATUS_TIMEOUT:
                entry["timeout_count"] += 1
                entry["failure_count"] += 1
            elif fact.status == STATUS_SUCCEEDED:
                entry["success_count"] += 1
            else:
                entry["failure_count"] += 1
            entry["first_used_at"] = min(entry["first_used_at"], fact.observed_at)
            entry["last_used_at"] = max(entry["last_used_at"], fact.observed_at)
            digest = _observations_digest(fact.observations)
            if (
                digest
                and len(entry["sample_observations"]) < TOOL_EVIDENCE_OBSERVATION_PAIRS
            ):
                entry["sample_observations"].append(digest)
        for entry in groups.values():
            entry["executions"] = (
                entry["success_count"] + entry["failure_count"]
            )
            entry["span_hours"] = _span_hours(
                entry["first_used_at"], entry["last_used_at"]
            )
        return groups
    except Exception:
        logger.exception("工具使用效果聚合异常，按门槛未过处理：%s", user_id)
        return {}

def aggregate_success_rate(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    facts: list[ToolExecutionFact] | None = None,
) -> dict[str, dict]:
    """窗口二（Action 成功率）：按 tool_id / action_type 分组统计失败率 + failure_kind 分布。

    E3：`failure_kind` 各自成组独立计数、独立判门槛（同 tool_id 不同失败原因不合并）。
    """
    started = time.perf_counter()
    try:
        facts = _resolve_facts(user_id, now, window_days, facts)
        groups: dict[str, dict] = {}
        for group_kind, key_of in (
            (GROUP_KIND_TOOL, lambda fact: fact.tool_id),
            (GROUP_KIND_ACTION, lambda fact: fact.action_type),
        ):
            for fact in facts:
                _accumulate_rate_group(
                    groups, group_kind, key_of(fact), fact, window_days
                )
        for fact in facts:
            if fact.failure_kind is None:
                continue
            _accumulate_rate_group(
                groups,
                GROUP_KIND_FAILURE,
                f"{fact.tool_id}|{fact.failure_kind}",
                fact,
                window_days,
                parent_tool_id=fact.tool_id,
                failure_kind=fact.failure_kind,
            )
        return groups
    except Exception:
        logger.exception("Action 成功率聚合异常，按门槛未过处理：%s", user_id)
        return {}

def aggregate_user_feedback(
    user_id: str,
    *,
    now: datetime,
    followup_turns: int = TOOL_FEEDBACK_FOLLOWUP_TURNS,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    facts: list[ToolExecutionFact] | None = None,
) -> dict[str, dict]:
    """窗口三（用户反馈）：工具执行后 N 轮用户消息极性 + 撤销检测 + 沉默检测。

    极性判定为词表规则（零 LLM）；用户消息按锚点会话只读（`messages` 表投影），
    工具锚点仍只来自 `action_records`。锚点未老于沉默门槛时不计沉默（E8 防误判）。
    """
    started = time.perf_counter()
    try:
        facts = _resolve_facts(user_id, now, window_days, facts)
        revokes = [fact for fact in facts if _is_revoke(fact)]
        messages = _human_messages_after(facts, followup_turns)
        groups: dict[str, dict] = {}
        for fact in facts:
            if _is_revoke(fact):
                continue
            entry = groups.setdefault(
                fact.tool_id,
                {
                    "group_kind": GROUP_KIND_TOOL,
                    "group_key": fact.tool_id,
                    "executions": 0,
                    "followup_negative": 0,
                    "followup_positive": 0,
                    "followup_neutral": 0,
                    "revoked_after": 0,
                    "silence_after": 0,
                    "first_at": fact.observed_at,
                    "last_at": fact.observed_at,
                },
            )
            entry["executions"] += 1
            entry["first_at"] = min(entry["first_at"], fact.observed_at)
            entry["last_at"] = max(entry["last_at"], fact.observed_at)
            follows = _followups_for(fact, messages, followup_turns)
            if follows:
                polarity = asuna_evaluation.classify_feedback_polarity(follows[0])
                if polarity == asuna_evaluation.TOOL_FEEDBACK_POLARITY_NEGATIVE:
                    entry["followup_negative"] += 1
                elif polarity == asuna_evaluation.TOOL_FEEDBACK_POLARITY_POSITIVE:
                    entry["followup_positive"] += 1
                else:
                    entry["followup_neutral"] += 1
            elif _silence_eligible(fact, now):
                entry["silence_after"] += 1
            if any(_revokes(fact, revoke) for revoke in revokes):
                entry["revoked_after"] += 1
        for entry in groups.values():
            entry["span_hours"] = _span_hours(entry["first_at"], entry["last_at"])
        return groups
    except Exception:
        logger.exception("用户反馈窗聚合异常，按门槛未过处理：%s", user_id)
        return {}

def aggregate_tool_windows(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    followup_turns: int = TOOL_FEEDBACK_FOLLOWUP_TURNS,
    facts: list[ToolExecutionFact] | None = None,
) -> dict[str, dict[str, dict]]:
    """三窗聚合总入口（异常按门槛未过处理，各自返回空 dict + 日志）。"""
    resolved = _resolve_facts(user_id, now, window_days, facts)
    return {
        asuna_evaluation.TOOL_WINDOW_USAGE_EFFECT: aggregate_tool_usage(
            user_id, now=now, window_days=window_days, facts=resolved
        ),
        asuna_evaluation.TOOL_WINDOW_ACTION_SUCCESS_RATE: aggregate_success_rate(
            user_id, now=now, window_days=window_days, facts=resolved
        ),
        asuna_evaluation.TOOL_WINDOW_USER_FEEDBACK: aggregate_user_feedback(
            user_id,
            now=now,
            followup_turns=followup_turns,
            window_days=window_days,
            facts=resolved,
        ),
    }

def aggregate_tool_evidence(
    user_id: str,
    *,
    now: datetime | None = None,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    followup_turns: int = TOOL_FEEDBACK_FOLLOWUP_TURNS,
    trace=None,
) -> ToolEvidencePackage:
    """工具效能证据包：三窗聚合 → 逐组门槛 → 达门槛窗口（纯读、零 LLM）。"""
    started = time.perf_counter()
    now = now or datetime.now()
    try:
        facts = _window_facts(user_id, now, window_days)
        tool_windows = aggregate_tool_windows(
            user_id,
            now=now,
            window_days=window_days,
            followup_turns=followup_turns,
            facts=facts,
        )
        windows = build_tool_evidence_windows(tool_windows, facts, now=now)
        package = ToolEvidencePackage(
            tool_windows=tool_windows,
            windows=windows,
            passing=len(windows),
            executions=len(facts),
        )
    except Exception as exc:
        logger.exception("工具效能证据聚合异常，按门槛未过处理：%s", user_id)
        _tool_trace(
            trace,
            started,
            status="error",
            error=f"{exc.__class__.__name__}: {exc}",
        )
        return ToolEvidencePackage()
    _tool_trace(
        trace,
        started,
        executions=package.executions,
        passing=package.passing,
        windows=[
            {
                "window_kind": window.window_kind,
                "group_key": window.group_key,
                "member_count": window.stats.member_count,
                "span_hours": window.stats.span_hours,
            }
            for window in package.windows
        ],
    )
    return package

def _resolve_facts(
    user_id: str,
    now: datetime,
    window_days: int,
    facts: list[ToolExecutionFact] | None,
) -> list[ToolExecutionFact]:
    """注入式事实（同一批事实供三窗复用）；未注入则按窗口只读 `action_records`。"""
    if facts is not None:
        return facts
    return _window_facts(user_id, now, window_days)

def _window_facts(
    user_id: str, now: datetime, window_days: int
) -> list[ToolExecutionFact]:
    """窗口内工具执行事实（`action_records` 终态投影，超出时间窗的丢弃）。"""
    records = memory_sources.fetch_action_records(
        user_id, limit=TOOL_EVIDENCE_RECORD_SCAN_LIMIT
    )
    start = now - timedelta(days=window_days)
    facts: list[ToolExecutionFact] = []
    for record in records:
        reference = _record_reference_time(record)
        if reference is None or reference < start or reference > now:
            continue
        for index, step in enumerate(record.steps or []):
            tool_id = step.get("tool_id")
            if not tool_id:
                continue
            observations = _step_observations(step)
            stored_result = record.result if isinstance(record.result, dict) else {}
            if stored_result.get("feedback_kinds") is not None:
                observations = {
                    **observations,
                    "feedback_kinds": list(stored_result.get("feedback_kinds") or []),
                    "temporary_execution": bool(
                        stored_result.get("temporary_execution", False)
                    ),
                }
            facts.append(
                ToolExecutionFact(
                    evidence_id=tool_evidence_id(str(tool_id), record.id, index),
                    record_id=record.id,
                    tool_id=str(tool_id),
                    action_type=str(record.action_type),
                    status=_step_status(step),
                    failure_kind=_step_failure_kind(step),
                    observed_at=reference,
                    source=str(record.source),
                    session_id=record.session_id,
                    target_record_id=record.target_record_id,
                    observations=observations,
                )
            )
    facts.sort(key=lambda fact: fact.observed_at)
    return facts

def tool_fact_projection(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
) -> list[ToolExecutionFact]:
    """工具执行事实投影（只读 `action_records`）：三窗聚合与 reinforce 补扫共用入口。"""
    try:
        return _window_facts(user_id, now, window_days)
    except Exception:
        logger.exception("工具执行事实投影异常，返回空清单：%s", user_id)
        return []

def _human_messages_after(
    facts: list[ToolExecutionFact], followup_turns: int
) -> dict[str, list[tuple[datetime, str]]]:
    """按锚点会话批量取后续用户消息（只读 `messages` 投影，每会话有界取前 N 条）。"""
    sessions = {fact.session_id for fact in facts if fact.session_id}
    if not sessions:
        return {}
    limit = max(followup_turns, 1) * TOOL_EVIDENCE_MAX_MEMBERS
    messages: dict[str, list[tuple[datetime, str]]] = {}
    with SessionLocal() as session:
        for session_id in sorted(sessions):
            rows = (
                session.query(Message.created_at, Message.content)
                .filter(
                    Message.conversation_id == session_id,
                    Message.role == "human",
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
                .limit(min(limit, TOOL_EVIDENCE_SESSION_MESSAGE_LIMIT))
                .all()
            )
            messages[session_id] = [
                (_naive(created_at), content or "") for created_at, content in rows
            ]
    return messages

def _tool_trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(TOOL_EVIDENCE_STEP_NAME, duration, status, **extra)

def aggregate_plan_success_rate(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    facts: list[PlanStepFact] | None = None,
) -> dict[str, dict]:
    """窗口一（计划成功率）：`goal_plans` 按目标类型（`plan_kind`）聚合步骤终态。

    样本 = **已到终态的步骤**（`done` / `failed`），成功率 = done / 样本数；
    同时记录所选计划版本的状态分布（`plan.status`，即 §4.2.1 的「按 status 聚合」），
    使「这类计划 4 步做不完」这类认知有可判定的数据来源。
    """
    try:
        facts = _resolve_plan_facts(
            user_id, now, window_days, facts, _plan_structure_facts
        )
        groups: dict[str, dict] = {}
        for fact in facts:
            if fact.step_status not in (STEP_STATUS_DONE, STEP_STATUS_FAILED):
                continue
            entry = groups.setdefault(
                fact.goal_type or _UNKNOWN_GROUP_KEY,
                {
                    "group_kind": GROUP_KIND_PLAN,
                    "group_key": fact.goal_type or _UNKNOWN_GROUP_KEY,
                    "samples": 0,
                    "success": 0,
                    "failed": 0,
                    "success_rate": 0.0,
                    "plan_status_counts": {},
                    "first_at": fact.observed_at,
                    "last_at": fact.observed_at,
                },
            )
            entry["samples"] += 1
            if fact.step_status == STEP_STATUS_DONE:
                entry["success"] += 1
            else:
                entry["failed"] += 1
            status = fact.plan_status or "unknown"
            entry["plan_status_counts"][status] = (
                entry["plan_status_counts"].get(status, 0) + 1
            )
            entry["first_at"] = min(entry["first_at"], fact.observed_at)
            entry["last_at"] = max(entry["last_at"], fact.observed_at)
            entry["success_rate"] = round(entry["success"] / entry["samples"], 4)
        for entry in groups.values():
            entry["span_hours"] = _span_hours(entry["first_at"], entry["last_at"])
        return groups
    except Exception:
        logger.exception("计划成功率聚合异常，按门槛未过处理：%s", user_id)
        return {}

def aggregate_step_failure_modes(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    facts: list[PlanStepFact] | None = None,
) -> dict[str, dict]:
    """窗口二（步骤失败模式）：`action_records.steps` 按 `tool_id` × `failure_kind` 聚合。

    两个分组键：`step_kind`（按工具）与 `failure_kind`（按「工具|失败类」各自成组，
    同工具不同失败原因不合并）——与既有工具成功率窗的组形态同构。
    """
    try:
        facts = _resolve_plan_facts(user_id, now, window_days, facts, _plan_action_facts)
        groups: dict[str, dict] = {}
        for fact in facts:
            if not fact.tool_id:
                continue
            _accumulate_plan_step_group(groups, GROUP_KIND_STEP, str(fact.tool_id), fact)
        for fact in facts:
            if not fact.tool_id or fact.failure_kind is None:
                continue
            _accumulate_plan_step_group(
                groups,
                GROUP_KIND_FAILURE,
                f"{fact.tool_id}|{fact.failure_kind}",
                fact,
                parent_tool_id=str(fact.tool_id),
                failure_kind=fact.failure_kind,
            )
        return groups
    except Exception:
        logger.exception("步骤失败模式聚合异常，按门槛未过处理：%s", user_id)
        return {}

def aggregate_criteria_decidability(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    facts: list[PlanStepFact] | None = None,
) -> dict[str, dict]:
    """窗口三（判据可判定性）：按判据类型（`criteria_kind`）聚合「判不出来」的步占比。

    样本 = 已被观测过的步骤（`last_observed_at` 非空）；`undecided` 的判别见
    `_step_undecided`（`goal_plans.sub_goals` 上唯一可投影的不可判定痕迹）。
    负样本口径：`undecided`（同时以 `failed` 键暴露给既有门槛函数的 `min_failures`——
    「判不出来」就是本窗的失败语义，成功率窗的 `failed`、失败模式窗的 `failed` 同理）。
    """
    try:
        facts = _resolve_plan_facts(
            user_id, now, window_days, facts, _plan_structure_facts
        )
        groups: dict[str, dict] = {}
        for fact in facts:
            key = fact.criteria_kind or _UNKNOWN_GROUP_KEY
            entry = groups.setdefault(
                key,
                {
                    "group_kind": GROUP_KIND_CRITERIA,
                    "group_key": key,
                    "samples": 0,
                    "decided": 0,
                    "undecided": 0,
                    "failed": 0,
                    "undecided_rate": 0.0,
                    "first_at": fact.observed_at,
                    "last_at": fact.observed_at,
                },
            )
            entry["samples"] += 1
            if fact.undecided:
                entry["undecided"] += 1
                entry["failed"] += 1
            else:
                entry["decided"] += 1
            entry["first_at"] = min(entry["first_at"], fact.observed_at)
            entry["last_at"] = max(entry["last_at"], fact.observed_at)
            entry["undecided_rate"] = round(entry["undecided"] / entry["samples"], 4)
        for entry in groups.values():
            entry["span_hours"] = _span_hours(entry["first_at"], entry["last_at"])
        return groups
    except Exception:
        logger.exception("判据可判定性聚合异常，按门槛未过处理：%s", user_id)
        return {}

def aggregate_plan_windows(
    user_id: str,
    *,
    now: datetime,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    structure_facts: list[PlanStepFact] | None = None,
    action_facts: list[PlanStepFact] | None = None,
) -> dict[str, dict[str, dict]]:
    """三窗聚合总入口（异常按门槛未过处理，各自返回空 dict + 日志）。"""
    resolved_structure = _resolve_plan_facts(
        user_id, now, window_days, structure_facts, _plan_structure_facts
    )
    resolved_action = _resolve_plan_facts(
        user_id, now, window_days, action_facts, _plan_action_facts
    )
    return {
        PLAN_WINDOW_SUCCESS_RATE: aggregate_plan_success_rate(
            user_id, now=now, window_days=window_days, facts=resolved_structure
        ),
        PLAN_WINDOW_STEP_FAILURE: aggregate_step_failure_modes(
            user_id, now=now, window_days=window_days, facts=resolved_action
        ),
        PLAN_WINDOW_CRITERIA_DECIDABILITY: aggregate_criteria_decidability(
            user_id, now=now, window_days=window_days, facts=resolved_structure
        ),
    }

def aggregate_plan_evidence(
    user_id: str,
    *,
    now: datetime | None = None,
    window_days: int = TOOL_EVIDENCE_WINDOW_DAYS,
    trace=None,
) -> PlanEvidencePackage:
    """计划效能证据包：三窗聚合 → 逐组门槛 → 达门槛窗口（纯读、零 LLM、零写入）。

    子闸已随开关体系删除，聚合恒发生。证据不足（样本 < `plan_reflection_min_samples`
    或跨度不足）→ 该组不成窗，故不产 Insight：调用链上不存在「证据不足仍调 LLM」的路径。
    """
    started = time.perf_counter()
    now = now or datetime.now()
    settings = get_settings()
    try:
        structure_facts, action_facts = _plan_facts(user_id, now, window_days)
        plan_windows = aggregate_plan_windows(
            user_id,
            now=now,
            window_days=window_days,
            structure_facts=structure_facts,
            action_facts=action_facts,
        )
        windows = build_plan_evidence_windows(
            plan_windows, structure_facts + action_facts, now=now, settings=settings
        )
        package = PlanEvidencePackage(
            plan_windows=plan_windows,
            windows=windows,
            passing=len(windows),
            steps=len(structure_facts),
            executions=len(action_facts),
        )
    except Exception as exc:
        logger.exception("计划效能证据聚合异常，按门槛未过处理：%s", user_id)
        _plan_trace(
            trace,
            started,
            status="error",
            error=f"{exc.__class__.__name__}: {exc}",
        )
        return PlanEvidencePackage()
    _plan_trace(
        trace,
        started,
        steps=package.steps,
        executions=package.executions,
        passing=package.passing,
        windows=[
            {
                "window_kind": window.window_kind,
                "group_key": window.group_key,
                "member_count": window.stats.member_count,
                "span_hours": window.stats.span_hours,
            }
            for window in package.windows
        ],
    )
    return package

def _plan_facts(
    user_id: str, now: datetime, window_days: int
) -> tuple[list[PlanStepFact], list[PlanStepFact]]:
    """计划事实投影总入口：`(结构事实, 执行事实)`（两者都只读、都异常降级为空）。"""
    return (
        _plan_structure_facts(user_id, now, window_days),
        _plan_action_facts(user_id, now, window_days),
    )

def _plan_structure_facts(
    user_id: str, now: datetime, window_days: int
) -> list[PlanStepFact]:
    """`goal_plans` 投影：活跃目标及其计划版本链的步级事实（只读、零写入）。

    读取面只有既有两个函数：`list_active_plans`（活跃目标 × 活跃计划）与
    `list_plans`（该目标的版本链）；超出时间窗的步按窗口纪律丢弃。
    """
    start = now - timedelta(days=window_days)
    facts: list[PlanStepFact] = []
    for goal, _plan in goal_repository.list_active_plans(user_id):
        for plan in goal_repository.list_plans(goal.id):
            reference = _naive(plan.updated_at) or _naive(plan.created_at)
            for spec in plan.sub_goals:
                observed = _naive(spec.last_observed_at) or reference
                if observed is None or observed < start or observed > now:
                    continue
                facts.append(
                    PlanStepFact(
                        evidence_id=plan_evidence_id(goal.id, plan.version, spec.index),
                        goal_id=str(goal.id),
                        version=int(plan.version),
                        step_index=int(spec.index),
                        observed_at=observed,
                        goal_type=str(goal.type or ""),
                        plan_status=str(plan.status or ""),
                        step_status=str(spec.status or ""),
                        tool_id=spec.tool_id,
                        criteria_kind=_criteria_kind(spec.criteria),
                        undecided=_step_undecided(spec),
                    )
                )
    facts.sort(key=lambda fact: fact.observed_at)
    return facts

def _plan_action_facts(
    user_id: str, now: datetime, window_days: int
) -> list[PlanStepFact]:
    """`action_records` 投影：计划域步骤的执行事实（只读、零写入）。

    计划域台账按幂等键前缀收敛（`plan:<goal_id>:`，即执行桥渲染的步级幂等键）；
    记录恒为单步记录（执行桥一次一 intent），故证据 id 即记录级 `dedupe_key`——
    与 `PLAN_STEP_DEDUPE_KEY_TEMPLATE` 同源，零硬编码。
    """
    records = action_repository.list_records(
        user_id, limit=TOOL_EVIDENCE_RECORD_SCAN_LIMIT
    )
    start = now - timedelta(days=window_days)
    facts: list[PlanStepFact] = []
    for record in records:
        parsed = plan_evidence_id_of(str(record.dedupe_key or ""))
        if parsed is None:
            continue
        reference = _record_reference_time(record)
        if reference is None or reference < start or reference > now:
            continue
        step = (record.steps or [{}])[0]
        tool_id = step.get("tool_id")
        if not tool_id:
            continue
        goal_id, version, index = parsed
        facts.append(
            PlanStepFact(
                evidence_id=str(record.dedupe_key),
                goal_id=goal_id,
                version=version,
                step_index=index,
                observed_at=reference,
                step_status=_step_status(step),
                tool_id=str(tool_id),
                failure_kind=_step_failure_kind(step),
            )
        )
    facts.sort(key=lambda fact: fact.observed_at)
    return facts

def _plan_trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(PLAN_EVIDENCE_STEP_NAME, duration, status, **extra)
