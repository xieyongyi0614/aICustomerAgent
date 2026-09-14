"""Reflection 域模型（REF-001）。

Insight / ReflectionRun 服务层投影；状态与枚举是生命周期状态机的事实源。
类型终值由代码校准与复检决定（LLM 自报值仅作提案）。
EvidenceMember / EvidenceWindow（REF-002）为证据聚合的计算结构。
TOOL-009：Insight 类型值域增三类工具效能类型（capability_note /
usage_preference / interaction_calibration），并新增工具效能证据窗结构
ToolEvidenceWindow（复用 EvidenceWindow 结构与既有闸门语义）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

InsightStatus = Literal["active", "superseded", "invalidated"]

InsightType = Literal[
    "belief",
    "preference",
    "pattern",
    "capability_note",
    "usage_preference",
    "interaction_calibration",
]

InsightTypeCore = Literal["belief", "preference", "pattern"]

ToolInsightType = Literal[
    "capability_note", "usage_preference", "interaction_calibration"
]

TOOL_INSIGHT_TYPES: tuple[str, ...] = (
    "capability_note",
    "usage_preference",
    "interaction_calibration",
)
"""工具效能 Insight 类型值域（TOOL-009 §2.2）：只增类型；性格/人格/关系类不新增。"""

TOOL_INSIGHT_SCOPES: tuple[str, ...] = ("user", "world")
"""工具效能 Insight 允许的 scope（TOOL-009 边界：不做关系域信号映射）。"""

EVIDENCE_CHANNEL_MEMORY = "memory"
EVIDENCE_CHANNEL_TOOL = "tool"

EVIDENCE_CHANNELS: tuple[str, ...] = (EVIDENCE_CHANNEL_MEMORY, EVIDENCE_CHANNEL_TOOL)

TOOL_EVIDENCE_KIND = "tool_evidence"
CORE_EVIDENCE_KIND = "memory_evidence"

InsightScope = Literal["user", "relationship", "world"]

ReflectionRunStatus = Literal["queued", "running", "done", "skipped", "failed"]

ReflectionTrigger = Literal["scheduled", "event"]

INVALIDATION_SOURCE = Literal["user_clarification", "new_evidence", "judge"]


class InsightStatusEnum(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class InsightTypeEnum(StrEnum):
    BELIEF = "belief"
    PREFERENCE = "preference"
    PATTERN = "pattern"
    CAPABILITY_NOTE = "capability_note"
    USAGE_PREFERENCE = "usage_preference"
    INTERACTION_CALIBRATION = "interaction_calibration"


class InsightScopeEnum(StrEnum):
    USER = "user"
    RELATIONSHIP = "relationship"
    WORLD = "world"


class ReflectionRunStatusEnum(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class ReflectionTriggerEnum(StrEnum):
    SCHEDULED = "scheduled"
    EVENT = "event"


@dataclass
class EvidenceMember:
    memory_id: str
    content: str
    created_at: datetime
    source: str
    source_ref: str
    salience: float
    weight: float
    semantic_sim: float = 0.0
    topic_sim: float = 0.0


@dataclass
class WindowStats:
    member_count: int
    span_hours: float
    distinct_source_refs: int
    source_type_mix: dict = field(default_factory=dict)
    coherence: float = 0.0


@dataclass
class EvidenceWindow:
    topic_digest: str
    members: list[EvidenceMember] = field(default_factory=list)
    stats: WindowStats | None = None
    gate_reasons: list[str] = field(default_factory=list)
    degraded: str | None = None

    @property
    def passes_gate(self) -> bool:
        return not self.gate_reasons


@dataclass
class ToolEvidenceWindow(EvidenceWindow):
    """工具效能证据窗（TOOL-009 §2.2 / §4.1）：沿用 EvidenceWindow 结构走同一闸门。

    members 由 `action_records` 投影的执行事实合成（`memory_id` 为 `tool:` 前缀的
    证据 id），`window_kind` 标识三窗之一，`group_key` 为聚合键（tool_id /
    action_type / failure_kind）。既有四个窗口结构零改动。
    """

    kind: str = TOOL_EVIDENCE_KIND
    window_kind: str = ""
    group_key: str = ""
    insight_types: tuple[str, ...] = ()


class Insight(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    statement: str
    type: InsightType
    confidence: float
    scope: InsightScope
    status: InsightStatus = "active"
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None = None
    invalidated_reason: str | None = None
    superseded_by: str | None = None


class InsightDraft(BaseModel):
    """LLM 反思提案单元：counter_evidence 必填（无反例写「无」），缺字段即整体不合规。"""

    statement: str
    type: InsightType
    scope: InsightScope
    evidence_ids: list[str]
    counter_evidence: str
    self_confidence: float = 0.0


class InsightSummary(BaseModel):
    """prompt 投影（REF-007）：insight 段渲染用的最小只读摘要。"""

    insight_id: str
    statement: str
    type: InsightType
    confidence: float


class ReflectionProposal(BaseModel):
    """反思 LLM 结构化输出：仅提案，confidence 终值由代码按证据强度校准。"""

    insights: list[InsightDraft] = []


class ReflectionRun(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    trigger: ReflectionTrigger
    status: ReflectionRunStatus
    evidence_summary: dict | None = None
    outcome: str | None = None
    llm_used: bool = False
    insight_ids: list[str] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
