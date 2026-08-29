from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MemoryType = Literal["preference", "fact", "goal", "experience", "relationship"]

MemoryTypeV4 = Literal["user_preference", "user_fact", "important_event", "relationship_event"]

MemorySource = Literal["user_stated", "user_derived", "ai_inferred"]

MemoryAction = Literal["save", "update", "invalidate", "forget", "suppress", "none"]

MemoryStatus = Literal["active", "superseded", "invalidated"]

LEGACY_MEMORY_TYPE_MAP = {
    "preference": "user_preference",
    "fact": "user_fact",
    "goal": "user_fact",
    "experience": "important_event",
    "relationship": "relationship_event",
}

TARGETED_ACTIONS = ("update", "invalidate")


class MemoryDecision(BaseModel):
    should_save: bool
    memory: str | None
    memory_type: MemoryType
    importance: float

    @model_validator(mode="after")
    def validate_memory(self):
        if self.should_save and not self.memory:
            raise ValueError("should_save=True 时 memory 必填")
        return self


class UserMemory(BaseModel):
    id: str
    user_id: str
    memory: str
    memory_type: MemoryType
    importance: float
    created_at: datetime
    updated_at: datetime


class MemoryCandidate(BaseModel):
    action: MemoryAction = "none"
    type: MemoryTypeV4
    content: str | None = None
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: MemorySource = "ai_inferred"
    target_memory_id: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == "none":
            if self.target_memory_id is not None:
                raise ValueError("action=none 时不应携带 target_memory_id")
            return self
        if not self.content:
            raise ValueError("action!=none 时 content 必填")
        if self.action in TARGETED_ACTIONS and not self.target_memory_id:
            raise ValueError("action=update/invalidate 时 target_memory_id 必填")
        if self.action not in TARGETED_ACTIONS and self.target_memory_id is not None:
            raise ValueError("action=save/forget/suppress 时不应携带 target_memory_id")
        return self


class MemoryExtraction(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)


class UserMemoryV4(BaseModel):
    id: str
    user_id: str
    character_id: str
    type: MemoryTypeV4
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
