from typing import Literal

from pydantic import BaseModel

BehaviorType = Literal[
    "normal_reply",
    "comfort",
    "encourage",
    "celebrate",
    "show_concern",
    "recall_memory",
    "ask_followup",
]


class BehaviorDecision(BaseModel):
    behavior: BehaviorType = "normal_reply"
    reason: str = ""
