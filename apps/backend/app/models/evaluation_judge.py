"""V7.5 LLM Judge 判定模型（llm-judge.md §3）。

受限枚举 + 数值边界约束；evidence 子串校验与 memory_ids 受限引用在链与引擎侧执行。
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class PersonaIssueCode(StrEnum):
    PERSONA_OOC = "persona_ooc"
    PERSONA_KNOWLEDGE_LEAK = "persona_knowledge_leak"


class EmotionIssueCode(StrEnum):
    EMOTION_OVERSHIFT = "emotion_overshift"
    EMOTION_TEXT_STATE_CONFLICT = "emotion_text_state_conflict"


class MemoryIssueCode(StrEnum):
    MEMORY_FABRICATION = "memory_fabrication"
    MEMORY_CONTRADICTION = "memory_contradiction"
    MEMORY_MISSED = "memory_missed"


class AutonomyIssueCode(StrEnum):
    AUTONOMY_UNNECESSARY = "autonomy_unnecessary"
    AUTONOMY_REDUNDANT = "autonomy_redundant"


class PersonaJudgement(BaseModel):
    in_character: bool = True
    score: float = Field(ge=0.0, le=1.0)
    codes: list[PersonaIssueCode] = []
    evidence_quote: str = Field(default="", max_length=80)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class EmotionJudgement(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    codes: list[EmotionIssueCode] = []
    evidence_quote: str = Field(default="", max_length=80)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class MemoryJudgement(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    codes: list[MemoryIssueCode] = []
    memory_ids: list[str] = []
    evidence_quote: str = Field(default="", max_length=80)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AutonomyJudgement(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    codes: list[AutonomyIssueCode] = []
    evidence_quote: str = Field(default="", max_length=80)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class TurnJudgeResult(BaseModel):
    persona: PersonaJudgement | None = None
    emotion: EmotionJudgement | None = None
    memory: MemoryJudgement | None = None


class ProactiveJudgeResult(BaseModel):
    autonomy: AutonomyJudgement
    persona: PersonaJudgement


class ReflectionJudgeResult(BaseModel):
    """Reflection Judge（REF-006）：结论不超证据范围 / 引用真实支撑结论。"""

    passed: bool = True
    codes: list[str] = []
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


JUDGE_SOURCE: Literal["llm"] = "llm"
