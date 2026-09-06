import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GoalType = Literal["user_care", "relationship", "conversation", "scene"]

GoalStatus = Literal["active", "completed", "expired", "cancelled"]

GoalSource = Literal["definition", "policy", "scene"]

GoalHorizon = Literal["persistent", "current"]

GoalLayer = Literal["short_term", "long_term"]

GoalDomain = Literal["personal", "relationship", "world"]

GoalPlanStatus = Literal["draft", "validated", "active", "rejected", "superseded"]

SubGoalStatus = Literal["pending", "in_progress", "done", "failed"]

LAYER_VALUES: tuple[str, ...] = ("short_term", "long_term")
DOMAIN_VALUES: tuple[str, ...] = ("personal", "relationship", "world")
PLAN_STATUS_VALUES: tuple[str, ...] = (
    "draft",
    "validated",
    "active",
    "rejected",
    "superseded",
)
SUB_GOAL_STATUS_VALUES: tuple[str, ...] = ("pending", "in_progress", "done", "failed")

CRITERION_TYPES: tuple[str, ...] = (
    "action_succeeded",
    "field_equals",
    "threshold_reached",
    "all_of",
    "any_of",
)
COMPOSITE_CRITERION_TYPES: tuple[str, ...] = ("all_of", "any_of")
CRITERION_FACT_SOURCES: tuple[str, ...] = ("world", "state", "memory")
CRITERION_METRIC_PATHS: tuple[str, ...] = (
    "tension",
    "intimacy",
    "mood",
    "salient_memory_count",
)
CRITERION_OPS: tuple[str, ...] = (">=", "<=")

HIERARCHICAL_TYPE_MAP: dict[str, GoalType] = {
    "personal": "user_care",
    "relationship": "relationship",
    "world": "conversation",
}

GOAL_TIER: dict[str, int] = {
    "scene": 0,
    "user_care": 1,
    "relationship": 2,
    "conversation": 3,
}

GOAL_DESCRIPTION_MAX_LENGTH = 40
GOAL_PRIORITY_MIN = 1
GOAL_PRIORITY_MAX = 5


class GoalSeed(BaseModel):
    type: GoalType
    description: str = Field(max_length=GOAL_DESCRIPTION_MAX_LENGTH)
    priority: int = Field(ge=GOAL_PRIORITY_MIN, le=GOAL_PRIORITY_MAX)


class GoalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    character_id: str = "asuna"
    type: GoalType
    description: str = Field(max_length=GOAL_DESCRIPTION_MAX_LENGTH)
    priority: int = Field(ge=GOAL_PRIORITY_MIN, le=GOAL_PRIORITY_MAX, default=3)
    status: GoalStatus = "active"
    horizon: GoalHorizon = "current"
    source: GoalSource = "policy"
    created_turn: int = 0
    expires_at_turn: int | None = None
    created_at: datetime
    updated_at: datetime
    parent_goal_id: str | None = None
    layer: GoalLayer | None = None
    domain: GoalDomain | None = None
    failure_reason: str | None = None


class SubGoalSpec(BaseModel):
    index: int = Field(ge=1)
    description: str = Field(max_length=GOAL_DESCRIPTION_MAX_LENGTH)
    capability: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)
    criteria: dict
    depends_on: list[int] = Field(default_factory=list)
    parent_index: int | None = Field(default=None, ge=1)
    status: SubGoalStatus = "pending"
    attempt_count: int = 0
    last_observed_at: datetime | None = None
    failure_note: str | None = None

    @staticmethod
    def validate_criteria(criteria: dict, depth: int = 0) -> None:
        if not isinstance(criteria, dict):
            raise ValueError("判据必须为对象")
        criterion_type = criteria.get("type")
        if criterion_type not in CRITERION_TYPES:
            raise ValueError(f"判据类型不在白名单：{criterion_type!r}")
        if criterion_type == "action_succeeded":
            if not criteria.get("capability"):
                raise ValueError("action_succeeded 判据缺 capability")
            within = criteria.get("within_minutes")
            if within is not None and (not isinstance(within, int) or within <= 0):
                raise ValueError("within_minutes 必须为正整数")
            return
        if criterion_type == "field_equals":
            if criteria.get("source") not in CRITERION_FACT_SOURCES:
                raise ValueError(f"事实源不在白名单：{criteria.get('source')!r}")
            path = criteria.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("field_equals 判据缺 path")
            if "value" not in criteria:
                raise ValueError("field_equals 判据缺 value")
            return
        if criterion_type == "threshold_reached":
            if criteria.get("source") not in CRITERION_FACT_SOURCES:
                raise ValueError(f"事实源不在白名单：{criteria.get('source')!r}")
            if criteria.get("path") not in CRITERION_METRIC_PATHS:
                raise ValueError(f"指标路径不在白名单：{criteria.get('path')!r}")
            if criteria.get("op") not in CRITERION_OPS:
                raise ValueError(f"比较算子不在白名单：{criteria.get('op')!r}")
            if not isinstance(criteria.get("value"), (int, float)):
                raise ValueError("threshold_reached 判据 value 必须为数值")
            return
        if depth >= 1:
            raise ValueError("组合判据只允许一层嵌套")
        children = criteria.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError("组合判据 children 必须为非空列表")
        for child in children:
            SubGoalSpec.validate_criteria(child, depth + 1)


def validate_sub_goals(sub_goals: list[dict]) -> list["SubGoalSpec"]:
    """Planning 产物形状校验：判据白名单 + 序号连续 + 依赖/父子引用合法。

    深度 ≤2（parent 的 parent 必须为顶层）与数量封顶由 AUT-002 闸门以
    settings 预算裁决，此处只拒结构性非法（引用缺失/前向/越级嵌套）。
    """
    specs: list[SubGoalSpec] = []
    top_level_indexes: set[int] = set()
    for raw in sub_goals:
        if not isinstance(raw, dict):
            raise ValueError("Sub-Goal 必须为对象")
        criteria = raw.get("criteria")
        if not isinstance(criteria, dict):
            raise ValueError(f"Sub-Goal {raw.get('index')} 缺判据")
        SubGoalSpec.validate_criteria(criteria)
        spec = SubGoalSpec.model_validate(raw)
        if spec.index != len(specs) + 1:
            raise ValueError(f"Sub-Goal 序号不连续：{spec.index}")
        for ref in spec.depends_on:
            if ref >= spec.index:
                raise ValueError(f"Sub-Goal {spec.index} 依赖前向引用 {ref}")
        if spec.parent_index is not None:
            if spec.parent_index >= spec.index:
                raise ValueError(f"Sub-Goal {spec.index} 父引用前向 {spec.parent_index}")
            if spec.parent_index in top_level_indexes:
                raise ValueError(f"Sub-Goal {spec.index} 嵌套超过两层")
        else:
            top_level_indexes.add(spec.index)
        specs.append(spec)
    return specs


class GoalPlanRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal_id: str
    version: int = Field(ge=1)
    status: GoalPlanStatus = "draft"
    sub_goals: list[SubGoalSpec] = Field(default_factory=list)
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime
