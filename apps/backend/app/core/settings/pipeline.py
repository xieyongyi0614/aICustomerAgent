"""对话管线域设置：路由/场景阈值、模式切换、上下文预算、trace 容量。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class PipelineSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    summary_threshold: int = 40
    router_confidence_threshold: float = 0.5
    scene_intent_threshold: float = 0.5

    context_total_char_budget: int = 12000
    state_history_limit: int = 20
    scene_pending_max_turns: int = 5
    scene_idle_reset_enabled: bool = True
    scene_idle_reset_hours: float = 6.0

    mode_switch_min_confidence: float = 0.7
    mode_switch_min_turns: int = 2
    mode_idle_reset_seconds: int = 7200
    habit_extra_json: str = "[]"
    analysis_recent_messages: int = 6
    trace_capacity: int = 20
    log_content_preview_chars: int = 0

    conversation_max_messages: int = 20
    conversation_max_chars: int = 8000

    default_user: str = "default-user"
    auth_token_secret: str = ""
