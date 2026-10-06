"""Reflection 证据窗构造与门槛数学（纯函数，零 IO）。

窗体/数据类/门槛判定在此，聚合采集（DB/trace）见 `collectors`。
"""

from app.core import timeutil
from app.character.asuna import evaluation as asuna_evaluation
from app.core.settings import get_settings
from app.engines.memory_conflict import _lcs_length, same_topic
from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE
from app.models.reflection import EVIDENCE_CHANNEL_PLAN
from app.models.reflection import EvidenceMember
from app.models.reflection import EvidenceWindow
from app.models.reflection import PlanEvidenceWindow
from app.models.reflection import TOOL_EVIDENCE_KIND
from app.models.reflection import ToolEvidenceWindow
from app.models.reflection import WindowStats
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
import math


import logging

logger = logging.getLogger(__name__)


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
    """embedding 列可能为 str/list/None（同构复刻 memory/retriever，不 import 私有函数）。"""
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

def _source_identity(memory_id: str, source_ref) -> str:
    if isinstance(source_ref, dict):
        ref_id = source_ref.get("id")
        if ref_id:
            return str(ref_id)
    return f"memory:{memory_id}"

def _member_weight(salience: float | None, reference: datetime | None, now: datetime) -> float:
    half_life = get_settings().memory_recency_half_life_days
    now = timeutil.ensure_aware(now)
    reference = timeutil.ensure_aware(reference) or now
    days = max((now - reference).total_seconds() / 86400, 0.0)
    recency = 0.5 ** (days / half_life)
    return round((salience if salience is not None else _DEFAULT_SALIENCE) * recency, 6)

def passes_gate(window: EvidenceWindow, settings=None) -> tuple[bool, list[str]]:
    """三闸前置判定（REF-003 复用）：数量（独立来源）/跨度/印证度。"""
    settings = settings or get_settings()
    stats = window.stats
    reasons: list[str] = []
    if stats.distinct_source_refs < settings.reflection_min_evidence:
        reasons.append(_GATE_EVIDENCE_COUNT)
    if stats.span_hours < settings.reflection_min_span_hours:
        reasons.append(_GATE_SPAN)
    if stats.coherence < settings.reflection_min_coherence:
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

def tool_evidence_id(tool_id: str, record_id: str, index: int) -> str:
    """工具证据 id（`evidence_links.memory_id` 落库口径）：`tool:<tool_id>:<record>:<index>`。"""
    return f"{TOOL_EVIDENCE_NAMESPACE}:{tool_id}:{record_id}:{index}"

def tool_id_of_evidence_id(evidence_id: str) -> str | None:
    """证据 id → tool_id；非工具证据（记忆来源）返回 None。"""
    parts = str(evidence_id or "").split(":", 2)
    if len(parts) < 3 or parts[0] != TOOL_EVIDENCE_NAMESPACE:
        return None
    return parts[1] or None

def _record_reference_time(record) -> datetime | None:
    return timeutil.ensure_aware(record.executed_at) or timeutil.ensure_aware(record.updated_at) or timeutil.ensure_aware(
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

PLAN_EVIDENCE_STEP_NAME = "reflection_plan_evidence"

PLAN_STEP_SOURCE = "plan_step"

PLAN_EVIDENCE_NAMESPACE = EVIDENCE_CHANNEL_PLAN

PLAN_STEP_EVIDENCE_PREFIX = PLAN_STEP_DEDUPE_KEY_TEMPLATE.split("{", 1)[0]

GROUP_KIND_PLAN = "plan_kind"

GROUP_KIND_STEP = "step_kind"

GROUP_KIND_CRITERIA = "criteria_kind"

PLAN_WINDOW_SUCCESS_RATE = "plan_success_rate"

PLAN_WINDOW_STEP_FAILURE = "step_failure_mode"

PLAN_WINDOW_CRITERIA_DECIDABILITY = "criteria_decidability"

PLAN_WINDOW_KINDS: tuple[str, ...] = (
    PLAN_WINDOW_SUCCESS_RATE,
    PLAN_WINDOW_STEP_FAILURE,
    PLAN_WINDOW_CRITERIA_DECIDABILITY,
)

PLAN_WINDOW_PRIORITY: tuple[str, ...] = PLAN_WINDOW_KINDS

PLAN_WINDOW_ALLOWED_INSIGHTS: dict[str, tuple[str, ...]] = {
    PLAN_WINDOW_SUCCESS_RATE: ("capability_note",),
    PLAN_WINDOW_STEP_FAILURE: ("capability_note", "usage_preference"),
    PLAN_WINDOW_CRITERIA_DECIDABILITY: ("pattern",),
}

PLAN_WINDOW_FAILURE_DRIVEN_KINDS: tuple[str, ...] = PLAN_WINDOW_KINDS

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
    | `min_samples` | `plan_reflection_min_samples`（3） | `reflection_min_evidence` |
    | `min_span_hours` | `reflection_min_span_hours`（24.0） | 既有反思窗跨度纪律 |
    | `min_failures` | 同 `min_samples`，**仅失败驱动窗** | `TOOL_WINDOW_THRESHOLDS` 的 `min_failures` |

    形状与 `asuna_evaluation.TOOL_WINDOW_THRESHOLDS` 同构，直接喂既有 `passes_tool_gate` /
    `tool_gate_reasons`。
    """
    resolved = settings if settings is not None else get_settings()
    min_samples = int(resolved.plan_reflection_min_samples)
    thresholds: dict[str, float] = {
        "min_samples": min_samples,
        "min_span_hours": float(resolved.reflection_min_span_hours),
    }
    if window_kind in PLAN_WINDOW_FAILURE_DRIVEN_KINDS:
        thresholds["min_failures"] = min_samples
    return thresholds

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
    now = timeutil.ensure_aware(now)
    if facts is not None:
        return facts
    return resolver(user_id, now, window_days)

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
