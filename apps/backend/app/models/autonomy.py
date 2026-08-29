"""V7 Autonomy 域模型（autonomy-model.md / action-model.md）。

纯数据定义：TriggerSignal / AutonomyVerdict / ProactiveAction；
不绑定 LLM、数据库与队列。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.intention import INTENTION_REASON_MAX_LENGTH

TriggerType = Literal["conversation_inactivity", "scheduled_followup"]

ProactiveActionType = Literal["send_message"]

ActionStatus = Literal[
    "candidate",
    "approved",
    "delivered",
    "acked",
    "discarded",
    "failed",
    "expired",
]

VERDICT_REASON_MAX_LENGTH = 60

PROACTIVE_INTENTION_MAP: dict[str, str] = {
    "user_care": "check_in",
    "relationship": "repair_rapport",
}


class TriggerSignal(BaseModel):
    type: TriggerType
    user_id: str
    detected_at: datetime
    context: dict = {}
    dedupe_key: str


class AutonomyVerdict(BaseModel):
    decision: Literal["act", "wait", "ignore"]
    reason: str = Field(default="", max_length=VERDICT_REASON_MAX_LENGTH)
    trigger: TriggerSignal | None = None
    goal_id: str | None = None
    intention: str | None = None


class ProactiveAction(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    session_id: str
    type: ProactiveActionType = "send_message"
    trigger_type: TriggerType
    dedupe_key: str
    goal_id: str | None = None
    intention: str
    reason: str = Field(default="", max_length=INTENTION_REASON_MAX_LENGTH)
    payload_text: str | None = None
    status: ActionStatus = "candidate"
    attempt: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None = None
    message_id: str | None = None
    acked_at: datetime | None = None


TERMINAL_STATUSES = frozenset({"acked", "discarded", "failed", "expired"})
