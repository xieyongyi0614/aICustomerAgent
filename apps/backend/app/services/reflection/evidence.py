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
from app.models.reflection import (
    TOOL_EVIDENCE_KIND,
    EvidenceMember,
    EvidenceWindow,
    ToolEvidenceWindow,
    WindowStats,
)
from app.repositories import memory_repository
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
    """主入口：候选池 → 聚类 → 组统计 → 门槛判定；异常/空池返回空列表。"""
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
    return result["windows"]


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

