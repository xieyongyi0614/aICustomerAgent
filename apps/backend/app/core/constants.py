"""V5/V2 状态引擎数值设计表。仅数据，不含逻辑；调整需同步回归测试。"""

from app.models.relationship import RelationshipDelta

STAGE_ORDER = ("stranger", "friend", "close_friend", "partner")

EMOTION_EVENTS: dict[str, dict] = {
    "praise": {"emotion": "happy", "delta": 0.3},
    "comforted": {"emotion": "happy", "delta": 0.25},
    "teased": {"emotion": "shy", "delta": 0.25},
    "warm_moment": {"emotion": "happy", "delta": 0.2},
    "funny_moment": {"emotion": "excited", "delta": 0.3},
    "criticized": {"emotion": "sad", "delta": 0.3},
    "conflict": {"emotion": "angry", "delta": 0.4},
    "worrying_news": {"emotion": "worried", "delta": 0.35},
    "reunion": {"emotion": "excited", "delta": 0.3},
}

MAGNITUDE_COEFFICIENTS: dict[str, float] = {
    "weak": 0.6,
    "normal": 1.0,
    "strong": 1.4,
}

RELATIONSHIP_EVENT_DELTAS: dict[str, RelationshipDelta] = {
    "user_care": RelationshipDelta(trust=0.04, intimacy=0.03, familiarity=0.01, tension=-0.02),
    "user_help": RelationshipDelta(trust=0.05, intimacy=0.03, familiarity=0.02),
    "long_interaction": RelationshipDelta(intimacy=0.01, familiarity=0.02),
    "intimate_moment": RelationshipDelta(trust=0.02, intimacy=0.06, familiarity=0.01, tension=-0.01),
    "praise": RelationshipDelta(trust=0.02, intimacy=0.02, familiarity=0.01, tension=-0.01),
    "warm_moment": RelationshipDelta(trust=0.02, intimacy=0.02, familiarity=0.01, tension=-0.01),
    "criticized": RelationshipDelta(trust=-0.03, tension=0.05),
    "conflict": RelationshipDelta(intimacy=-0.12, trust=-0.10, familiarity=-0.05, tension=0.20),
    "boundary_violation": RelationshipDelta(trust=-0.08, intimacy=-0.05, tension=0.15),
    "none": RelationshipDelta(),
}

EVENT_DELTAS: dict[str, RelationshipDelta] = {
    "achievement": RelationshipDelta(intimacy=0.04, familiarity=0.02),
    "setback": RelationshipDelta(intimacy=0.03),
    "share_goal": RelationshipDelta(intimacy=0.02, trust=0.06),
    "seek_help": RelationshipDelta(intimacy=0.02, trust=0.05, familiarity=0.02),
    "help_given": RelationshipDelta(intimacy=0.03, trust=0.02, familiarity=0.06),
    "complaint": RelationshipDelta(trust=-0.03),
    "conflict": RelationshipDelta(intimacy=-0.12, trust=-0.10, familiarity=-0.05),
    "daily": RelationshipDelta(familiarity=0.01),
    "farewell": RelationshipDelta(),
}

BEHAVIOR_DELTAS: dict[str, RelationshipDelta] = {
    "comfort": RelationshipDelta(intimacy=0.02),
    "celebrate": RelationshipDelta(intimacy=0.02),
    "encourage": RelationshipDelta(trust=0.01),
    "recall_memory": RelationshipDelta(trust=0.02, familiarity=0.03),
}

ENERGY_EVENT_MODIFIERS: dict[str, float] = {
    "achievement": 0.10,
    "help_given": 0.05,
    "setback": -0.05,
    "complaint": -0.05,
    "conflict": -0.10,
}

ENERGY_BEHAVIOR_MODIFIERS: dict[str, float] = {
    "comfort": -0.05,
    "show_concern": -0.03,
}

