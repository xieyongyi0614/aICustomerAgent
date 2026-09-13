"""Agent State 值对象（V2.1.0 AGENT-002）：统一意识状态投影，Run 内不可变。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InterestTopic(BaseModel):
    model_config = ConfigDict(frozen=True)

    topic: str = Field(max_length=40)
    score: float = Field(ge=0.0)


class CurrentFocus(BaseModel):
    model_config = ConfigDict(frozen=True)

    topic: str = ""
    goal_id: str | None = None
    goal_description: str = ""
    action: str = ""
    attention: str = "user"


class PersonalityAxisState(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    baseline: float
    current: float
    bound_min: float
    bound_max: float


class AgentStateSnapshot(BaseModel):
    """七组件统一快照：各组件 SoT 仍在原域，本对象为只读投影。"""

    model_config = ConfigDict(frozen=True)

    mood: str = "calm"
    energy: float = 0.9
    intensity: float = 0.3
    inner_state: str = ""
    emotion_cause: str = ""
    relationship: dict[str, Any] = Field(default_factory=dict)
    interest_focus: list[InterestTopic] = Field(default_factory=list)
    current_focus: CurrentFocus | None = None
    personality: list[PersonalityAxisState] = Field(default_factory=list)
    snapshot_version: int = 1

    def digest_lines(self) -> str:
        """完整三行摘要（台账/调试用）：状态 / 兴趣 / 焦点。"""
        head = (
            f"【当前状态】心情:{self.mood} 能量:{self.energy:.1f} "
            f"强度:{self.intensity:.1f}"
        )
        return "\n".join([head, *self.prompt_lines()])

    def prompt_lines(self) -> list[str]:
        """上下文只读段（净新增：兴趣 / 焦点；mood 等由既有状态段承载）。"""
        lines = []
        if self.interest_focus:
            topics = "、".join(t.topic for t in self.interest_focus)
            lines.append(f"【当前感兴趣】{topics}")
        focus = self.current_focus
        if focus is not None and (focus.goal_description or focus.action or focus.topic):
            parts = []
            if focus.goal_description:
                parts.append(f"目标:{focus.goal_description}")
            if focus.action:
                parts.append(f"在做:{focus.action}")
            if focus.topic:
                parts.append(f"话题:{focus.topic}")
            lines.append("【当前关注】" + " ".join(parts))
        return lines
