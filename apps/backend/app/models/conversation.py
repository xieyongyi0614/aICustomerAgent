from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.character_state import CharacterState
from app.models.development import DevelopmentOverlay, RelationshipPattern
from app.models.goal import GoalRecord
from app.models.memory import UserMemory
from app.models.reflection import InsightSummary
from app.models.relationship import RelationshipState, SharedExperience


class ChatMessage(BaseModel):
    role: Literal["human", "ai"]
    content: str


class ConversationState(BaseModel):
    session_id: str
    user_id: str
    messages: list[ChatMessage]
    summary: str | None
    memories: list[UserMemory]
    current_input: str
    character_state: CharacterState = CharacterState()
    relationship_state: RelationshipState = RelationshipState()
    goals: list[GoalRecord] = []
    layered_goals: list[GoalRecord] = []
    insights: list[InsightSummary] = []
    development_overlay: DevelopmentOverlay | None = None
    shared_experiences: list[SharedExperience] = []
    relationship_patterns: list[RelationshipPattern] = []
    mode: str = "default"
    mode_entered_at: datetime | None = None
    memory_rank: list[dict] = []
    """本轮检索名次快照（MEV-004）：`[{id, score, rank, rank_pre, reranked}]`。

    仅进程内传递（检索处 → turn_meta 装配），供 `services/memory/refs.py` 派生引用观测量；
    不落库、不参与 prompt 装配。
    """
