from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

MemoryType = Literal["preference", "fact", "goal", "experience", "relationship"]


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
