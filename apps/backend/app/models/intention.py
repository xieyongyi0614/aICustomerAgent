from typing import Literal

from pydantic import BaseModel, Field

IntentionType = Literal[
    "comfort_user",
    "suggest_rest",
    "encourage_user",
    "celebrate_with_user",
    "express_affection",
    "tease_user",
    "maintain_distance",
    "repair_rapport",
    "continue_topic",
    "ask_followup",
    "share_own_feeling",
    "lighten_mood",
    "check_in",
]

INTENTION_REASON_MAX_LENGTH = 60

GOAL_TYPES = ("user_care", "relationship", "conversation", "scene")


class IntentionDecision(BaseModel):
    intention: IntentionType
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=INTENTION_REASON_MAX_LENGTH)


class ValidatedIntention(BaseModel):
    intention: IntentionType
    reason: str = Field(default="", max_length=INTENTION_REASON_MAX_LENGTH)
    goal_id: str | None = None
    degraded: bool = False


INTENTION_GOAL_FIT: dict[str, frozenset[str]] = {
    "comfort_user": frozenset({"user_care", "relationship"}),
    "suggest_rest": frozenset({"user_care"}),
    "encourage_user": frozenset({"user_care", "conversation"}),
    "celebrate_with_user": frozenset({"conversation", "relationship"}),
    "express_affection": frozenset({"relationship", "conversation"}),
    "tease_user": frozenset({"relationship", "conversation"}),
    "maintain_distance": frozenset({"relationship"}),
    "repair_rapport": frozenset({"relationship"}),
    "continue_topic": frozenset({"user_care", "relationship", "conversation", "scene"}),
    "ask_followup": frozenset({"conversation", "user_care", "relationship"}),
    "share_own_feeling": frozenset({"relationship", "conversation"}),
    "lighten_mood": frozenset({"user_care", "relationship", "conversation"}),
}

INTENTION_GOAL_DEFAULTS: dict[str, str] = {
    "user_care": "comfort_user",
    "relationship": "repair_rapport",
    "conversation": "continue_topic",
    "scene": "continue_topic",
}

EXPRESSION_INTENTIONS = frozenset(
    {"express_affection", "tease_user", "share_own_feeling"}
)

INTENTION_BEHAVIOR_MAP: dict[str, str] = {
    "comfort_user": "comfort",
    "suggest_rest": "show_concern",
    "encourage_user": "encourage",
    "celebrate_with_user": "celebrate",
    "ask_followup": "ask_followup",
}
