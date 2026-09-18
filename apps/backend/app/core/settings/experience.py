"""Experience 域设置（V2.2.0 CHAR-007）：体验层总闸与四路子闸。

总闸 + 子闸双开才生效；关闭后行为与 V2.1.0 逐字节一致。
"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class ExperienceSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    experience_enabled: bool = False
    emotion_transition_enabled: bool = False
    relationship_addressing_enabled: bool = False
    habit_runtime_enabled: bool = False
    style_contract_enabled: bool = False
