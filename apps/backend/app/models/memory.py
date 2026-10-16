from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MemoryType = Literal[
    "user_preference",
    "user_fact",
    "experience",
    "relationship_fact",
    "commitment",
    "milestone_event",
    "behavior_pattern",
]
"""存储词表（`memories.type`，7 规范值）；与 DB CHECK `ck_memories_type` 同域。"""

LegacyMemoryType = Literal["important_event", "relationship_event"]
"""入站兼容名：LLM 输出 / 旧数据可能携带，经 `normalize_type` 归一后方可落库。"""

CandidateMemoryType = MemoryType | LegacyMemoryType
"""候选类型域：候选是入站值对象，容忍遗留名；存储层只认 `MemoryType`。"""

MemorySource = Literal["user_stated", "user_derived", "ai_inferred"]

MemoryAction = Literal["save", "update", "invalidate", "forget", "suppress", "none"]

MemoryRelation = Literal["refine", "replace", "negate"]

MemoryStatus = Literal[
    "active",
    "superseded",
    "invalidated",
    "decayed",
    "forgotten",
]

TARGETED_ACTIONS = ("update", "invalidate")


class UserMemory(BaseModel):
    id: str
    user_id: str
    character_id: str
    type: MemoryType
    content: str
    importance: float
    confidence: float = 0.0
    source: MemorySource = "ai_inferred"
    status: MemoryStatus = "active"
    superseded_by: str | None = None
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None


class MemoryCandidate(BaseModel):
    action: MemoryAction = "none"
    type: CandidateMemoryType
    content: str | None = None
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: MemorySource = "ai_inferred"
    target_memory_id: str | None = None
    relation: MemoryRelation | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == "none":
            if self.target_memory_id is not None:
                raise ValueError("action=none 时不应携带 target_memory_id")
            return self
        if not self.content:
            raise ValueError("action!=none 时 content 必填")
        if self.action not in TARGETED_ACTIONS and self.target_memory_id is not None:
            raise ValueError("action=save/forget/suppress 时不应携带 target_memory_id")
        return self


class MemoryExtraction(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)


class EvaluationVerdict(BaseModel):
    """评估器 LLM 兜底输出；type 仅为建议，终值由代码映射规则决定。"""

    approve: bool
    type: str | None = None
    reason: str = ""
