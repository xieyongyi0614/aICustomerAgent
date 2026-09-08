"""角色状态域设置：情绪 / 能量 / 阶段阈值。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class CharacterSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    emotion_max_turn_delta: float = 0.4
    emotion_strong_threshold: float = 0.6
    emotion_switch_min_confidence: float = 0.8
    emotion_inertia: float = 0.2
    emotion_decay_strong: float = 0.20
    emotion_decay_mild: float = 0.10
    emotion_decay_floor: float = 0.15
    emotion_rest_intensity: float = 0.3
    emotion_strong_boundary: float = 0.5

    energy_turn_decay: float = 0.05
    energy_min: float = 0.1
    energy_reset_hours: int = 12
    energy_reset_value: float = 0.85

    stage_friend_familiarity: float = 0.35
    stage_close_intimacy: float = 0.55
    stage_close_trust: float = 0.55
    stage_partner_intimacy: float = 0.75
    stage_partner_trust: float = 0.75
    stage_hysteresis: float = 0.10
