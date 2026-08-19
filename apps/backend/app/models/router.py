from typing import Literal

from pydantic import BaseModel


class RoleMode(BaseModel):
    mode: Literal["professional", "default", "immersive"]
    intent: Literal["technical", "casual", "emotional", "roleplay", "sao_lore"]
    confidence: float
    reason: str
