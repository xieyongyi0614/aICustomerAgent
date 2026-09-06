"""Development 域模型（DEV-001）。

DevelopmentState / DevelopmentChange 服务层投影；状态与枚举是生命周期状态机的
事实源（active→superseded|retired，终态不复活）。ModulationTarget 是调制槽位
key 命名空间的类型化表达（response_style/behavior/goal/autonomy）。
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

DevelopmentStatus = Literal["active", "superseded", "retired"]

DevelopmentKind = Literal["belief", "preference", "pattern"]

ModulationTarget = Literal["response_style", "behavior", "goal", "autonomy"]

ChangeReason = Literal[
    "compiled", "arbitrated", "arbitrated_lost", "rolled_back", "retired", "replayed"
]


class DevelopmentStatusEnum(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class DevelopmentKindEnum(StrEnum):
    BELIEF = "belief"
    PREFERENCE = "preference"
    PATTERN = "pattern"


class ModulationTargetEnum(StrEnum):
    RESPONSE_STYLE = "response_style"
    BEHAVIOR = "behavior"
    GOAL = "goal"
    AUTONOMY = "autonomy"


class DevelopmentState(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    kind: DevelopmentKind
    key: str
    value: dict
    strength: float
    source_insight_id: str
    status: DevelopmentStatus = "active"
    created_at: datetime
    updated_at: datetime


class DevelopmentChange(BaseModel):
    id: str
    development_state_id: str
    before: dict | None = None
    after: dict | None = None
    insight_id: str
    reason: ChangeReason = "compiled"
    created_at: datetime


class ModulationProposal(BaseModel):
    """DevPolicy 编译输出单元（DEV-002）：一个调制槽位的提案，仲裁前非真相。"""

    kind: DevelopmentKind
    key: str
    value: dict
    strength: float
    insight_id: str
    insight_created_at: datetime | None = None
