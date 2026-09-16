"""Evidence Window 聚合（REF-002）+ 工具效能证据窗（TOOL-009）。

从 memories（active、非 hypothetical）聚合合格证据组：窗口过滤 → 贪心单遍主题
聚类（语义邻域 ∪ same_topic 关键词路）→ 组统计（数量/跨度/独立来源/印证度/
成员 weight）→ 门槛前置判定。纯规则 0 LLM；单条记忆不成组；同数据同分组幂等。
「独立来源」口径 = ≥v2_reflection_min_evidence 个不同 source_ref.id（不同原始
消息/事件），source 类型分布仅作统计与 REF-004 折算输入。

TOOL-009 §2.1/§4.1 追加三个工具效能证据窗（工具使用效果 / Action 成功率 /
用户反馈）与 `passes_tool_gate`，数据来源纪律：工具执行事实一律从
`action_records` 投影读取（`memory2.sources.fetch_action_records`），**不读**
`ToolRegistry` 状态、**不读**健康度内存态——反思看的是"历史执行事实"，不是
"当前运维状态"。既有四个窗口（对话/记忆/世界/关系）聚合逻辑零改动。

PLAN-010 §4.1.3 ① 再追加一路**计划效能**证据通道（`EVIDENCE_CHANNEL_PLAN`），
三窗与工具侧**同构**：计划成功率（按目标类型）/ 步骤失败模式（按工具 × 失败类）/
判据可判定性（按判据类型）。数据来源纪律同样只有两条只读投影：`goal_plans`
（`goal_repository.list_active_plans` + `list_plans`）与 `action_records`
（`action_repository.list_records`）——**零新表、零写入**（证据即投影）。
上限常量（`TOOL_EVIDENCE_WINDOW_DAYS` / `TOOL_EVIDENCE_MAX_MEMBERS` /
`TOOL_EVIDENCE_RECORD_SCAN_LIMIT`）、分组键范式（`GROUP_KIND_*`）、证据 id 形态
（`PLAN_STEP_DEDUPE_KEY_TEMPLATE` 渲染的 `plan:<goal_id>:<version>:<step_index>`）
与门槛函数（`passes_tool_gate` / `tool_gate_reasons`）一律**复用**，本任务不自造
门槛数学。计划窗由 `aggregate_evidence_windows` 在子闸开启时追加，
故三道闸 / 幂等入队 / 额度**与用户证据走完全相同的一条路径**。
"""

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.character.asuna import evaluation as asuna_evaluation
from app.core.db import Memory, Message, SessionLocal
from app.core.settings import get_settings
from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE
from app.models.reflection import (
    EVIDENCE_CHANNEL_PLAN,
    TOOL_EVIDENCE_KIND,
    EvidenceMember,
    EvidenceWindow,
    PlanEvidenceWindow,
    ToolEvidenceWindow,
    WindowStats,
)
from app.repositories import action_repository, goal_repository, memory_repository
from app.services.memory2 import sources as memory_sources
from app.services.memory_conflict import _lcs_length, same_topic

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_evidence"

TOOL_EVIDENCE_STEP_NAME = "reflection_tool_evidence"

VISIBILITY_HYPOTHETICAL = "hypothetical"

TOOL_EVIDENCE_WINDOW_DAYS = 7
TOOL_FEEDBACK_FOLLOWUP_TURNS = 3
TOOL_EVIDENCE_MAX_MEMBERS = 12
TOOL_EVIDENCE_RECORD_SCAN_LIMIT = 200
TOOL_EVIDENCE_SESSION_MESSAGE_LIMIT = 40
TOOL_EVIDENCE_OBSERVATION_PAIRS = 3
TOOL_EVIDENCE_OBSERVATION_VALUE_CHARS = 40

TOOL_EXECUTION_SOURCE = "tool_execution"

TOOL_EVIDENCE_NAMESPACE = "tool"
"""工具证据 id 命名空间：`tool:<tool_id>:<record_id>:<index>`（反哺侧据此还原 tool_id）。"""

GROUP_KIND_TOOL = "tool_id"
GROUP_KIND_ACTION = "action_type"
GROUP_KIND_FAILURE = "failure_kind"

STATUS_TIMEOUT = "timeout"
STATUS_SUCCEEDED = "succeeded"
FAILED_STATUSES: frozenset[str] = frozenset({"failed", "timeout"})

_DEFAULT_SALIENCE = 0.5
_TOOL_FACT_SALIENCE = 0.8
_COHERENCE_PAIR_SAMPLE = 20
_TOPIC_DIGEST_CHARS = 40

_GATE_EVIDENCE_COUNT = "evidence_count"
_GATE_SPAN = "span"
_GATE_COHERENCE = "coherence"

TOOL_GATE_SAMPLES = "samples"
TOOL_GATE_FAILURES = "failures"
TOOL_GATE_SPAN = "span"



def _parse_vector(value) -> list[float] | None:
    """embedding 列可能为 str/list/None（同构复刻 memory2/retriever，不 import 私有函数）。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, list) else None
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_left * norm_right)))


def _topic_similarity(left: str, right: str) -> float:
    longer = max(len(left), len(right))
    if longer == 0:
        return 0.0
    return _lcs_length(left, right) / longer


def _naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


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


def _source_identity(memory_id: str, source_ref) -> str:
    if isinstance(source_ref, dict):
        ref_id = source_ref.get("id")
        if ref_id:
            return str(ref_id)
    return f"memory:{memory_id}"


def _member_weight(salience: float | None, reference: datetime | None, now: datetime) -> float:
    half_life = get_settings().memory_recency_half_life_days
    reference = _naive(reference) or now
    days = max((now - reference).total_seconds() / 86400, 0.0)
    recency = 0.5 ** (days / half_life)
    return round((salience if salience is not None else _DEFAULT_SALIENCE) * recency, 6)


def passes_gate(window: EvidenceWindow, settings=None) -> tuple[bool, list[str]]:
    """三闸前置判定（REF-003 复用）：数量（独立来源）/跨度/印证度。"""
    settings = settings or get_settings()
    stats = window.stats
    reasons: list[str] = []
    if stats.distinct_source_refs < settings.v2_reflection_min_evidence:
        reasons.append(_GATE_EVIDENCE_COUNT)
    if stats.span_hours < settings.v2_reflection_min_span_hours:
        reasons.append(_GATE_SPAN)
    if stats.coherence < settings.v2_reflection_min_coherence:
        reasons.append(_GATE_COHERENCE)
    return not reasons, reasons


class _Cluster:
    def __init__(self, member: EvidenceMember, vector: list[float] | None):
        self.members: list[EvidenceMember] = [member]
        self.member_vectors: list[list[float] | None] = [vector]
        self.rep_content = member.content
        self._vectors = [vector] if vector is not None else []
        self.rep_vector = list(vector) if vector is not None else None

    def add(self, member: EvidenceMember, vector: list[float] | None) -> None:
        self.members.append(member)
        self.member_vectors.append(vector)
        if vector is not None:
            self._vectors.append(vector)
            self.rep_vector = [
                sum(values) / len(self._vectors) for values in zip(*self._vectors)
            ]
        if len(member.content) > len(self.rep_content):
            self.rep_content = member.content


def _coherence(cluster: _Cluster) -> float:
    members = cluster.members
    if len(members) < 2:
        return 1.0
    pairs: list[float] = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if len(pairs) >= _COHERENCE_PAIR_SAMPLE:
                break
            left_vector = cluster.member_vectors[i]
            right_vector = cluster.member_vectors[j]
            if left_vector is not None and right_vector is not None:
                pairs.append(_cosine(left_vector, right_vector))
            else:
                pairs.append(_topic_similarity(members[i].content, members[j].content))
    if not pairs:
        return 1.0
    return sum(pairs) / len(pairs)


def _build_window(cluster: _Cluster, degraded: str | None, settings) -> EvidenceWindow:
    members = cluster.members
    for member, vector in zip(members, cluster.member_vectors):
        member.semantic_sim = round(_cosine(vector, cluster.rep_vector), 4)
        member.topic_sim = round(_topic_similarity(member.content, cluster.rep_content), 4)
    created = [member.created_at for member in members]
    span_hours = (
        (max(created) - min(created)).total_seconds() / 3600.0 if len(created) > 1 else 0.0
    )
    distinct_refs = {member.source_ref for member in members}
    type_mix: dict[str, int] = {}
    for member in members:
        type_mix[member.source] = type_mix.get(member.source, 0) + 1
    stats = WindowStats(
        member_count=len(members),
        span_hours=round(span_hours, 4),
        distinct_source_refs=len(distinct_refs),
        source_type_mix=type_mix,
        coherence=round(_coherence(cluster), 4),
    )
    window = EvidenceWindow(
        topic_digest=cluster.rep_content[:_TOPIC_DIGEST_CHARS],
        members=members,
        stats=stats,
        degraded=degraded,
    )
    _, window.gate_reasons = passes_gate(window, settings)
    return window


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
                semantic >= settings.v2_reflection_cluster_cosine
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
    window_start = now - timedelta(days=settings.v2_reflection_window_days)
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


def _window_digest(window: EvidenceWindow) -> dict:
    return {
        "topic_digest": window.topic_digest,
        "member_count": window.stats.member_count,
        "span_hours": window.stats.span_hours,
        "distinct_source_refs": window.stats.distinct_source_refs,
        "coherence": window.stats.coherence,
        "passes_gate": window.passes_gate,
        "gate_reasons": window.gate_reasons,
        "member_ids": [member.memory_id for member in window.members],
    }


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)


def _plan_channel_windows(
    user_id: str, now: datetime, trace
) -> list[PlanEvidenceWindow]:
    """计划通道扩源（PLAN-010 §4.1.3 ①）：子闸 off 时零调用零读取。

    计划窗**追加在既有窗口之后**：既有优先序纪律（既有窗口优先、取不到才回退）与
    `reflector._select_evidence` 的用户通道同款；本任务不改变既有窗口的相对顺序。
    计划窗的聚合异常只降级为空窗（不拉垮既有窗口）。
    """
    if not plan_evidence_enabled():
        return []
    try:
        return list(aggregate_plan_evidence(user_id, now=now, trace=trace).windows)
    except Exception:
        logger.exception("计划效能证据窗聚合异常，降级为空窗：%s", user_id)
        return []


# --- TOOL-009：三个工具效能证据窗 ---------------------------------------------


@dataclass(frozen=True)
class ToolExecutionFact:
    """一次工具执行的只读事实（`action_records.steps[].result` 投影）。"""

    evidence_id: str
    record_id: str
    tool_id: str
    action_type: str
    status: str
    failure_kind: str | None
    observed_at: datetime
    source: str
    session_id: str | None
    target_record_id: str | None
    observations: dict = field(default_factory=dict)


@dataclass
class ToolEvidencePackage:
    """工具效能证据包（§2.2）：三个窗口的聚合结果 + 达门槛的窗口。"""

    tool_windows: dict[str, dict[str, dict]] = field(default_factory=dict)
    windows: list[ToolEvidenceWindow] = field(default_factory=list)
    passing: int = 0
    executions: int = 0

    @property
    def judged(self) -> int:
        """参与门槛判定的分组数（含未达门槛者；审计用窗口计数）。"""
        return sum(len(groups) for groups in self.tool_windows.values())

    def summary(self) -> dict:
        """证据摘要（落 `reflection_runs.evidence_summary` 的 `tool_windows` 段）。"""
        return {
            "window_kinds": {
                kind: {
                    "groups": len(groups),
                    "passing": sum(
                        1
                        for entry in groups.values()
                        if passes_tool_gate(
                            entry, asuna_evaluation.thresholds_for(kind)
                        )
                    ),
                }
                for kind, groups in self.tool_windows.items()
            },
            "passing": self.passing,
            "executions": self.executions,
        }


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


def passes_tool_gate(window: dict, thresholds: dict) -> bool:
    """工具证据窗门槛：样本数 / 失败数 / 时间跨度任一不足即不过（与既有三道闸同款纪律）。"""
    if not window:
        return False
    if _sample_count(window) < int(thresholds.get("min_samples", 0) or 0):
        return False
    min_failures = thresholds.get("min_failures")
    if min_failures is not None and _failed_count(window) < int(min_failures):
        return False
    if float(window.get("span_hours", 0.0) or 0.0) < float(
        thresholds.get("min_span_hours", 0.0) or 0.0
    ):
        return False
    return True


def tool_gate_reasons(window: dict, thresholds: dict) -> list[str]:
    """未过门槛的原因清单（审计与 trace 用；过门槛返回空列表）。"""
    reasons: list[str] = []
    if _sample_count(window) < int(thresholds.get("min_samples", 0) or 0):
        reasons.append(TOOL_GATE_SAMPLES)
    min_failures = thresholds.get("min_failures")
    if min_failures is not None and _failed_count(window) < int(min_failures):
        reasons.append(TOOL_GATE_FAILURES)
    if float(window.get("span_hours", 0.0) or 0.0) < float(
        thresholds.get("min_span_hours", 0.0) or 0.0
    ):
        reasons.append(TOOL_GATE_SPAN)
    return reasons


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


def build_tool_evidence_windows(
    tool_windows: dict[str, dict[str, dict]],
    facts: list[ToolExecutionFact],
    *,
    now: datetime,
) -> list[ToolEvidenceWindow]:
    """逐组过门槛 → 达门槛组转为 ToolEvidenceWindow（复用既有闸门语义与成员结构）。"""
    windows: list[ToolEvidenceWindow] = []
    for kind in asuna_evaluation.TOOL_WINDOW_KINDS:
        thresholds = asuna_evaluation.thresholds_for(kind)
        for entry in (tool_windows.get(kind) or {}).values():
            if not passes_tool_gate(entry, thresholds):
                continue
            members = _window_members(kind, entry, facts, now)
            if len(members) < int(thresholds.get("min_samples", 0) or 0):
                continue
            windows.append(_build_tool_window(kind, entry, members))
    windows.sort(
        key=lambda window: (
            _kind_priority(window.window_kind),
            -window.stats.member_count,
            window.group_key,
        )
    )
    return windows


def _kind_priority(window_kind: str) -> int:
    priority = asuna_evaluation.TOOL_WINDOW_PRIORITY
    return priority.index(window_kind) if window_kind in priority else len(priority)


def order_tool_window_kinds(kinds: list[str] | tuple[str, ...]) -> list[str]:
    """达门槛窗口名按资产优先序排序（多次同门槛时的确定性选择顺序）。"""
    return sorted(
        {kind for kind in kinds if kind in asuna_evaluation.TOOL_WINDOW_KINDS},
        key=_kind_priority,
    )


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
                    observations=_step_observations(step),
                )
            )
    facts.sort(key=lambda fact: fact.observed_at)
    return facts


def tool_evidence_id(tool_id: str, record_id: str, index: int) -> str:
    """工具证据 id（`evidence_links.memory_id` 落库口径）：`tool:<tool_id>:<record>:<index>`。"""
    return f"{TOOL_EVIDENCE_NAMESPACE}:{tool_id}:{record_id}:{index}"


def tool_id_of_evidence_id(evidence_id: str) -> str | None:
    """证据 id → tool_id；非工具证据（记忆来源）返回 None。"""
    parts = str(evidence_id or "").split(":", 2)
    if len(parts) < 3 or parts[0] != TOOL_EVIDENCE_NAMESPACE:
        return None
    return parts[1] or None


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


def _record_reference_time(record) -> datetime | None:
    return _naive(record.executed_at) or _naive(record.updated_at) or _naive(
        record.created_at
    )


def _step_status(step: dict) -> str:
    result = step.get("result") or {}
    status = str(result.get("status") or "")
    if status:
        return status
    step_status = str(step.get("status") or "")
    return {
        "succeeded": STATUS_SUCCEEDED,
        "failed": "failed",
        "skipped": "unavailable",
    }.get(step_status, step_status or "failed")


def _step_failure_kind(step: dict) -> str | None:
    result = step.get("result") or {}
    kind = result.get("failure_kind") or (result.get("payload") or {}).get("failure_kind")
    if kind:
        return str(kind)
    if _step_status(step) in FAILED_STATUSES:
        return "transient"
    return None


def _step_observations(step: dict) -> dict:
    observations = (step.get("result") or {}).get("observations")
    return dict(observations) if isinstance(observations, dict) else {}


def _observations_digest(observations: dict) -> str:
    items = []
    for key, value in list(observations.items())[:TOOL_EVIDENCE_OBSERVATION_PAIRS]:
        text = str(value)[:TOOL_EVIDENCE_OBSERVATION_VALUE_CHARS]
        items.append(f"{key}={text}")
    return "；".join(items)


def _span_hours(earliest: datetime, latest: datetime) -> float:
    return round((latest - earliest).total_seconds() / 3600.0, 4)


def _sample_count(window: dict) -> int:
    for key in ("samples", "executions", "total"):
        if window.get(key) is not None:
            return int(window[key])
    return 0


def _failed_count(window: dict) -> int:
    for key in ("failed", "failure_count"):
        if window.get(key) is not None:
            return int(window[key])
    return 0


def _accumulate_rate_group(
    groups: dict[str, dict],
    group_kind: str,
    group_key: str,
    fact: ToolExecutionFact,
    window_days: int,
    *,
    parent_tool_id: str | None = None,
    failure_kind: str | None = None,
) -> None:
    key = f"{group_kind}:{group_key}"
    entry = groups.setdefault(
        key,
        {
            "group_kind": group_kind,
            "group_key": group_key,
            "parent_tool_id": parent_tool_id,
            "total": 0,
            "failed": 0,
            "success": 0,
            "failure_kinds": {},
            "failure_kind": failure_kind,
            "window_days": window_days,
            "first_at": fact.observed_at,
            "last_at": fact.observed_at,
        },
    )
    entry["total"] += 1
    entry["first_at"] = min(entry["first_at"], fact.observed_at)
    entry["last_at"] = max(entry["last_at"], fact.observed_at)
    if fact.status == STATUS_SUCCEEDED:
        entry["success"] += 1
    else:
        entry["failed"] += 1
        if fact.failure_kind:
            entry["failure_kinds"][fact.failure_kind] = (
                entry["failure_kinds"].get(fact.failure_kind, 0) + 1
            )
    entry["span_hours"] = _span_hours(entry["first_at"], entry["last_at"])
    entry["failure_rate"] = round(entry["failed"] / entry["total"], 4)


def _is_revoke(fact: ToolExecutionFact) -> bool:
    return asuna_evaluation.is_revoke_action(fact.source, fact.action_type)


def _revokes(anchor: ToolExecutionFact, revoke: ToolExecutionFact) -> bool:
    """撤销命中（E9）：同用户、时间在后，且指向同一记录 / 同一会话 / 同一工具。"""
    if revoke.observed_at <= anchor.observed_at:
        return False
    if revoke.target_record_id and revoke.target_record_id == anchor.record_id:
        return True
    if anchor.session_id and revoke.session_id == anchor.session_id:
        return True
    return revoke.tool_id == anchor.tool_id


def _silence_eligible(fact: ToolExecutionFact, now: datetime) -> bool:
    age_hours = (now - fact.observed_at).total_seconds() / 3600.0
    return age_hours >= asuna_evaluation.TOOL_FEEDBACK_SILENCE_MIN_AGE_HOURS


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


def _followups_for(
    fact: ToolExecutionFact,
    messages: dict[str, list[tuple[datetime, str]]],
    followup_turns: int,
) -> list[str]:
    rows = messages.get(fact.session_id or "", [])
    after = [
        content for created_at, content in rows if created_at and created_at > fact.observed_at
    ]
    return after[: max(followup_turns, 1)]


def _window_members(
    kind: str,
    entry: dict,
    facts: list[ToolExecutionFact],
    now: datetime,
) -> list[EvidenceMember]:
    selected = [fact for fact in facts if _fact_in_group(kind, entry, fact)]
    selected = selected[-TOOL_EVIDENCE_MAX_MEMBERS:]
    members: list[EvidenceMember] = []
    for fact in selected:
        members.append(
            EvidenceMember(
                memory_id=fact.evidence_id,
                content=_fact_content(fact),
                created_at=fact.observed_at,
                source=TOOL_EXECUTION_SOURCE,
                source_ref=fact.evidence_id,
                salience=_TOOL_FACT_SALIENCE,
                weight=_member_weight(_TOOL_FACT_SALIENCE, fact.observed_at, now),
            )
        )
    return members


def _fact_in_group(kind: str, entry: dict, fact: ToolExecutionFact) -> bool:
    """组归属判定：按聚合键（tool_id / action_type / failure_kind）精确匹配。"""
    if kind == asuna_evaluation.TOOL_WINDOW_USER_FEEDBACK:
        return fact.tool_id == entry["group_key"] and not _is_revoke(fact)
    group_kind = entry.get("group_kind")
    if group_kind == GROUP_KIND_TOOL:
        return fact.tool_id == entry["group_key"]
    if group_kind == GROUP_KIND_ACTION:
        return fact.action_type == entry["group_key"]
    if group_kind == GROUP_KIND_FAILURE:
        return (
            fact.tool_id == entry.get("parent_tool_id")
            and fact.failure_kind == entry.get("failure_kind")
        )
    return False


def _fact_content(fact: ToolExecutionFact) -> str:
    if fact.status == STATUS_SUCCEEDED:
        head = f"工具 {fact.tool_id} 执行成功"
    elif fact.status == STATUS_TIMEOUT:
        head = f"工具 {fact.tool_id} 执行超时"
    else:
        head = f"工具 {fact.tool_id} 执行失败"
    parts = [head, f"（{fact.observed_at:%Y-%m-%d %H:%M} {fact.action_type}）"]
    if fact.failure_kind:
        parts.append(f"failure_kind={fact.failure_kind}")
    digest = _observations_digest(fact.observations)
    if digest:
        parts.append(f"观测：{digest}")
    return "".join(parts)[: asuna_evaluation.TOOL_EVIDENCE_CONTENT_MAX_CHARS]


def _build_tool_window(
    kind: str,
    entry: dict,
    members: list[EvidenceMember],
) -> ToolEvidenceWindow:
    created = [member.created_at for member in members]
    span_hours = _span_hours(min(created), max(created)) if len(created) > 1 else 0.0
    group_key = str(entry.get("group_key"))
    stats = WindowStats(
        member_count=len(members),
        span_hours=round(span_hours, 4),
        distinct_source_refs=len({member.source_ref for member in members}),
        source_type_mix={TOOL_EXECUTION_SOURCE: len(members)},
        coherence=1.0,
    )
    window = ToolEvidenceWindow(
        topic_digest=f"工具效能：{group_key}（{kind}）"[:_TOPIC_DIGEST_CHARS],
        members=members,
        stats=stats,
        degraded=None,
        kind=TOOL_EVIDENCE_KIND,
        window_kind=kind,
        group_key=group_key,
        insight_types=asuna_evaluation.allowed_insight_types(kind),
    )
    window.gate_reasons = tool_gate_reasons(
        entry, asuna_evaluation.thresholds_for(kind)
    )
    return window


def _tool_trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(TOOL_EVIDENCE_STEP_NAME, duration, status, **extra)


# --- PLAN-010：三个计划效能证据窗 ---------------------------------------------

PLAN_EVIDENCE_STEP_NAME = "reflection_plan_evidence"

PLAN_STEP_SOURCE = "plan_step"
"""计划证据成员的来源标记（`WindowStats.source_type_mix` 与反哺侧判别用）。"""

PLAN_EVIDENCE_NAMESPACE = EVIDENCE_CHANNEL_PLAN
"""计划证据 id 命名空间（取值与通道常量同源；id 形态的唯一声明处是
`models/plan.py::PLAN_STEP_DEDUPE_KEY_TEMPLATE`）。"""

PLAN_STEP_EVIDENCE_PREFIX = PLAN_STEP_DEDUPE_KEY_TEMPLATE.split("{", 1)[0]
"""计划证据 id 前缀（`plan:`）：由模板字面段推导，零硬编码。"""

GROUP_KIND_PLAN = "plan_kind"
GROUP_KIND_STEP = "step_kind"
GROUP_KIND_CRITERIA = "criteria_kind"
"""新增分组键（沿用既有 `GROUP_KIND_*` 命名范式，§4.2.1）。

`GROUP_KIND_FAILURE` 复用工具侧的既有常量（同义同形，不新造第二份）。
"""

PLAN_WINDOW_SUCCESS_RATE = "plan_success_rate"
PLAN_WINDOW_STEP_FAILURE = "step_failure_mode"
PLAN_WINDOW_CRITERIA_DECIDABILITY = "criteria_decidability"

PLAN_WINDOW_KINDS: tuple[str, ...] = (
    PLAN_WINDOW_SUCCESS_RATE,
    PLAN_WINDOW_STEP_FAILURE,
    PLAN_WINDOW_CRITERIA_DECIDABILITY,
)
"""三个计划效能证据窗（§4.2.1 表序 = 本元组序）。"""

PLAN_WINDOW_PRIORITY: tuple[str, ...] = PLAN_WINDOW_KINDS
"""同门槛时的确定性选择顺序（形态对齐 `asuna_evaluation.TOOL_WINDOW_PRIORITY`）。"""

PLAN_WINDOW_ALLOWED_INSIGHTS: dict[str, tuple[str, ...]] = {
    PLAN_WINDOW_SUCCESS_RATE: ("capability_note",),
    PLAN_WINDOW_STEP_FAILURE: ("capability_note", "usage_preference"),
    PLAN_WINDOW_CRITERIA_DECIDABILITY: ("pattern",),
}
"""窗口 → 允许的 Insight 类型（§4.2.1 表）。类型闸由既有 reflector 的
`_window_insight_types` 机制消费：计划窗**结构性**不可能产出性格 / 人格类 Insight。"""

PLAN_WINDOW_FAILURE_DRIVEN_KINDS: tuple[str, ...] = PLAN_WINDOW_KINDS
"""受 `min_failures`（负样本下限）约束的窗口——三窗**全部**是失败/异常驱动的。

与工具侧 `TOOL_WINDOW_THRESHOLDS[ACTION_SUCCESS_RATE]` 的 `min_failures` 同款纪律：
计划效能窗只在「确实出了问题」时才成窗（一个 100% 顺利的计划不构成可学的认知，
也就没有理由占用当日反思额度）。负样本口径逐窗见各聚合器：成功率 = 失败步，
失败模式 = 失败执行，可判定性 = 判不出来的步。
"""

STEP_STATUS_DONE = "done"
STEP_STATUS_FAILED = "failed"

PLAN_STEP_STATUS_WORDS: dict[str, str] = {
    STEP_STATUS_DONE: "已完成",
    STEP_STATUS_FAILED: "已失败",
    "pending": "待执行",
    "in_progress": "进行中",
    STATUS_SUCCEEDED: "执行成功",
    STATUS_TIMEOUT: "执行超时",
    "unavailable": "不可用",
}

PLAN_WINDOW_LABELS: dict[str, str] = {
    PLAN_WINDOW_SUCCESS_RATE: "计划成功率",
    PLAN_WINDOW_STEP_FAILURE: "步骤失败模式",
    PLAN_WINDOW_CRITERIA_DECIDABILITY: "判据可判定性",
}

PLAN_WINDOW_METRICS: dict[str, str] = {
    PLAN_WINDOW_SUCCESS_RATE: "这类计划的步骤做成率",
    PLAN_WINDOW_STEP_FAILURE: "这一步反复失败的方式",
    PLAN_WINDOW_CRITERIA_DECIDABILITY: "这类判据常年判不出来",
}

_UNKNOWN_GROUP_KEY = "unknown"


def plan_evidence_id(goal_id: str, version: int, step_index: int) -> str:
    """计划证据 id（`evidence_links.memory_id` 落库口径）：`plan:<goal_id>:<version>:<step_index>`。

    形态的唯一声明处是 `models/plan.py::PLAN_STEP_DEDUPE_KEY_TEMPLATE`（与步骤幂等键同源）：
    证据 id 因此与「哪一步」一一对应，可供反哺侧（记忆 / 自治）直接还原目标与步序号。
    """
    return PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
        goal_id=goal_id, version=int(version), index=int(step_index)
    )


def plan_evidence_id_of(dedupe_key: str) -> tuple[str, int, int] | None:
    """证据 id / 步级幂等键 → `(goal_id, version, step_index)`；非计划域键返回 `None`。"""
    text = str(dedupe_key or "")
    if not text.startswith(PLAN_STEP_EVIDENCE_PREFIX):
        return None
    parts = text.split(":")
    if len(parts) != 4:
        return None
    try:
        return parts[1], int(parts[2]), int(parts[3])
    except ValueError:
        return None


def plan_thresholds(window_kind: str = "", settings=None) -> dict[str, float]:
    """计划证据窗门槛（复用既有 settings 语义与既有门槛函数，不新造数学）。

    | 项 | 取值 | 对齐来源 |
    |---|---|---|
    | `min_samples` | `v25_plan_reflection_min_samples`（3） | `v2_reflection_min_evidence` |
    | `min_span_hours` | `v2_reflection_min_span_hours`（24.0） | 既有反思窗跨度纪律 |
    | `min_failures` | 同 `min_samples`，**仅失败驱动窗** | `TOOL_WINDOW_THRESHOLDS` 的 `min_failures` |

    形状与 `asuna_evaluation.TOOL_WINDOW_THRESHOLDS` 同构，直接喂既有 `passes_tool_gate` /
    `tool_gate_reasons`。
    """
    resolved = settings if settings is not None else get_settings()
    min_samples = int(resolved.v25_plan_reflection_min_samples)
    thresholds: dict[str, float] = {
        "min_samples": min_samples,
        "min_span_hours": float(resolved.v2_reflection_min_span_hours),
    }
    if window_kind in PLAN_WINDOW_FAILURE_DRIVEN_KINDS:
        thresholds["min_failures"] = min_samples
    return thresholds


def plan_evidence_enabled(settings=None) -> bool:
    """计划证据通道子闸：总闸（`v2_reflection_enabled`）之外的 `v25_plan_reflection_enabled`。

    与 `triggers.tool_channel_enabled` 同款纪律：子闸 off 时**零计划窗、零额外读取**
    （`aggregate_evidence_windows` 的两通道行为与 V2.4.0 逐字节一致）。
    """
    resolved = settings if settings is not None else get_settings()
    return bool(
        getattr(resolved, "v2_reflection_enabled", False)
        and getattr(resolved, "v25_plan_reflection_enabled", False)
    )


@dataclass(frozen=True)
class PlanStepFact:
    """一步计划执行的只读事实（`goal_plans.sub_goals` / `action_records` 投影）。

    `evidence_id` 恒为 `plan_evidence_id(...)` 形态；结构事实（`goal_plans`）带
    `criteria_kind` / `step_status`，执行事实（`action_records`）带 `tool_id` /
    `failure_kind`；两者都只带事实，不带判断。
    """

    evidence_id: str
    goal_id: str
    version: int
    step_index: int
    observed_at: datetime
    source: str = PLAN_STEP_SOURCE
    goal_type: str = ""
    plan_status: str = ""
    step_status: str = ""
    tool_id: str | None = None
    failure_kind: str | None = None
    criteria_kind: str = ""
    undecided: bool = False


@dataclass
class PlanEvidencePackage:
    """计划效能证据包（§4.2.1）：三窗的聚合结果 + 达门槛的窗口。"""

    plan_windows: dict[str, dict[str, dict]] = field(default_factory=dict)
    windows: list[PlanEvidenceWindow] = field(default_factory=list)
    passing: int = 0
    steps: int = 0
    executions: int = 0

    @property
    def judged(self) -> int:
        """参与门槛判定的分组数（含未达门槛者；审计用窗口计数）。"""
        return sum(len(groups) for groups in self.plan_windows.values())

    def summary(self) -> dict:
        """证据摘要（落 `reflection_runs.evidence_summary` 的 `plan_windows` 段）。"""
        return {
            "channel": PLAN_EVIDENCE_NAMESPACE,
            "window_kinds": {
                kind: {
                    "groups": len(groups),
                    "passing": sum(
                        1
                        for entry in groups.values()
                        if passes_tool_gate(entry, plan_thresholds(kind))
                    ),
                }
                for kind, groups in self.plan_windows.items()
            },
            "passing": self.passing,
            "steps": self.steps,
            "executions": self.executions,
        }


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

    子闸 off 时直接返回空包（**零计划窗、零额外读取**：Flag off 下与 V2.4.0 逐字节一致）。
    证据不足（样本 < `v25_plan_reflection_min_samples` 或跨度不足）→ 该组不成窗，
    故不产 Insight：调用链上不存在「证据不足仍调 LLM」的路径。
    """
    started = time.perf_counter()
    now = now or datetime.now()
    settings = get_settings()
    if not plan_evidence_enabled(settings):
        return PlanEvidencePackage()
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


def build_plan_evidence_windows(
    plan_windows: dict[str, dict[str, dict]],
    facts: list[PlanStepFact],
    *,
    now: datetime,
    settings=None,
) -> list[PlanEvidenceWindow]:
    """逐组过门槛 → 达门槛组转为 `PlanEvidenceWindow`（复用既有闸门语义与成员结构）。"""
    windows: list[PlanEvidenceWindow] = []
    for kind in PLAN_WINDOW_KINDS:
        thresholds = plan_thresholds(kind, settings)
        for entry in (plan_windows.get(kind) or {}).values():
            if not passes_tool_gate(entry, thresholds):
                continue
            members = _plan_window_members(kind, entry, facts, now)
            if len(members) < int(thresholds.get("min_samples", 0) or 0):
                continue
            windows.append(_build_plan_window(kind, entry, members, thresholds))
    windows.sort(
        key=lambda window: (
            _plan_kind_priority(window.window_kind),
            -window.stats.member_count,
            window.group_key,
        )
    )
    return windows


def _plan_kind_priority(window_kind: str) -> int:
    return (
        PLAN_WINDOW_PRIORITY.index(window_kind)
        if window_kind in PLAN_WINDOW_PRIORITY
        else len(PLAN_WINDOW_PRIORITY)
    )


def _resolve_plan_facts(
    user_id: str,
    now: datetime,
    window_days: int,
    facts: list[PlanStepFact] | None,
    resolver,
) -> list[PlanStepFact]:
    """注入式事实（同一批事实供多窗复用）；未注入则按窗口只读投影。"""
    if facts is not None:
        return facts
    return resolver(user_id, now, window_days)


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


def _criteria_kind(criteria) -> str:
    """判据类型（分组键 `criteria_kind`）：缺失 / 非法形状一律归 `unknown`（不猜测）。"""
    if not isinstance(criteria, dict):
        return ""
    return str(criteria.get("type") or "")


def _step_undecided(spec) -> bool:
    """该步的判据是否「判不出来」（`goal_plans.sub_goals` 上唯一可投影的痕迹）。

    `goal_observation.advance_goal` 在 `evaluate_criteria` 返回 `None` 时只做两件事：
    推进 `last_observed_at` 与保存进度——**状态不变、尝试计数不增**。故
    「已观测过 ∧ 未到终态 ∧ 从未计数」即当步判据在观测中判不出来。
    （判据结果本身只出现在 `decision_records` 的 `facts_digest`，而计划证据的数据源
    纪律只有 `goal_plans` 与 `action_records` 两张表，故不从那里取。）
    """
    return bool(
        spec.last_observed_at is not None
        and str(spec.status or "") not in (STEP_STATUS_DONE, STEP_STATUS_FAILED)
        and int(spec.attempt_count or 0) == 0
    )


def _accumulate_plan_step_group(
    groups: dict[str, dict],
    group_kind: str,
    group_key: str,
    fact: PlanStepFact,
    *,
    parent_tool_id: str | None = None,
    failure_kind: str | None = None,
) -> None:
    """步骤失败模式的组累加（形态同构既有 `_accumulate_rate_group`）。"""
    entry = groups.setdefault(
        f"{group_kind}:{group_key}",
        {
            "group_kind": group_kind,
            "group_key": group_key,
            "parent_tool_id": parent_tool_id,
            "failure_kind": failure_kind,
            "samples": 0,
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "failure_kinds": {},
            "first_at": fact.observed_at,
            "last_at": fact.observed_at,
        },
    )
    entry["samples"] += 1
    entry["first_at"] = min(entry["first_at"], fact.observed_at)
    entry["last_at"] = max(entry["last_at"], fact.observed_at)
    if fact.step_status == STATUS_SUCCEEDED:
        entry["success"] += 1
    else:
        entry["failed"] += 1
        if fact.step_status == STATUS_TIMEOUT:
            entry["timeout"] += 1
        if fact.failure_kind:
            entry["failure_kinds"][fact.failure_kind] = (
                entry["failure_kinds"].get(fact.failure_kind, 0) + 1
            )
    entry["failure_rate"] = round(entry["failed"] / entry["samples"], 4)
    entry["span_hours"] = _span_hours(entry["first_at"], entry["last_at"])


def _plan_window_members(
    kind: str,
    entry: dict,
    facts: list[PlanStepFact],
    now: datetime,
) -> list[EvidenceMember]:
    """窗口成员（有界：`TOOL_EVIDENCE_MAX_MEMBERS`，取最近者）。"""
    selected = [fact for fact in facts if _plan_fact_in_group(kind, entry, fact)]
    selected = selected[-TOOL_EVIDENCE_MAX_MEMBERS:]
    return [
        EvidenceMember(
            memory_id=fact.evidence_id,
            content=_plan_fact_content(fact),
            created_at=fact.observed_at,
            source=PLAN_STEP_SOURCE,
            source_ref=fact.evidence_id,
            salience=_TOOL_FACT_SALIENCE,
            weight=_member_weight(_TOOL_FACT_SALIENCE, fact.observed_at, now),
        )
        for fact in selected
    ]


def _plan_fact_in_group(kind: str, entry: dict, fact: PlanStepFact) -> bool:
    """组归属判定：按聚合键（目标类型 / tool_id / tool|failure_kind / 判据类型）精确匹配。"""
    if kind == PLAN_WINDOW_SUCCESS_RATE:
        return (
            (fact.goal_type or _UNKNOWN_GROUP_KEY) == entry["group_key"]
            and fact.step_status in (STEP_STATUS_DONE, STEP_STATUS_FAILED)
        )
    if kind == PLAN_WINDOW_STEP_FAILURE:
        if entry.get("group_kind") == GROUP_KIND_FAILURE:
            return (
                str(fact.tool_id or "") == str(entry.get("parent_tool_id") or "")
                and fact.failure_kind == entry.get("failure_kind")
            )
        return str(fact.tool_id or "") == entry["group_key"]
    if kind == PLAN_WINDOW_CRITERIA_DECIDABILITY:
        return (fact.criteria_kind or _UNKNOWN_GROUP_KEY) == entry["group_key"]
    return False


def _plan_fact_content(fact: PlanStepFact) -> str:
    """成员内容（有界；只陈述事实，不给结论——结论一律由 LLM 提案 + 代码校准产生）。"""
    parts = [f"计划（{fact.goal_type or '未知'}）第 {fact.step_index} 步"]
    if fact.tool_id:
        parts.append(f"工具 {fact.tool_id}")
    parts.append(PLAN_STEP_STATUS_WORDS.get(fact.step_status, fact.step_status or "未观测"))
    if fact.criteria_kind:
        parts.append(f"判据 {fact.criteria_kind}")
    if fact.undecided:
        parts.append("判据未判出")
    if fact.failure_kind:
        parts.append(f"failure_kind={fact.failure_kind}")
    if fact.plan_status:
        parts.append(f"计划版本状态 {fact.plan_status}")
    parts.append(f"（{fact.observed_at:%Y-%m-%d %H:%M}）")
    return "；".join(parts)[: asuna_evaluation.TOOL_EVIDENCE_CONTENT_MAX_CHARS]


def _build_plan_window(
    kind: str,
    entry: dict,
    members: list[EvidenceMember],
    thresholds: dict,
) -> PlanEvidenceWindow:
    """成员 + 组统计 → `PlanEvidenceWindow`（门槛理由复用既有 `tool_gate_reasons`）。"""
    created = [member.created_at for member in members]
    span_hours = _span_hours(min(created), max(created)) if len(created) > 1 else 0.0
    group_key = str(entry.get("group_key"))
    stats = WindowStats(
        member_count=len(members),
        span_hours=round(span_hours, 4),
        distinct_source_refs=len({member.source_ref for member in members}),
        source_type_mix={PLAN_STEP_SOURCE: len(members)},
        coherence=1.0,
    )
    window = PlanEvidenceWindow(
        topic_digest=(
            f"计划效能（{PLAN_WINDOW_LABELS.get(kind, kind)}·{group_key}）："
            f"{PLAN_WINDOW_METRICS.get(kind, '')}"
        )[: _TOPIC_DIGEST_CHARS],
        members=members,
        stats=stats,
        degraded=None,
        window_kind=kind,
        group_key=group_key,
        insight_types=PLAN_WINDOW_ALLOWED_INSIGHTS.get(kind, ()),
    )
    window.gate_reasons = tool_gate_reasons(entry, thresholds)
    return window


def _plan_trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(PLAN_EVIDENCE_STEP_NAME, duration, status, **extra)

