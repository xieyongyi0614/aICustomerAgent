"""Life Loop / Outbox 域设置（V2.0.0 LIFE）：节拍、预算熔断、outbox 重试。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class LifeLoopSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    life_loop_tick_seconds: int = 60
    life_loop_trigger_max_attempts: int = 3
    life_loop_trigger_backoff_seconds: int = 300
    life_loop_daily_llm_call_budget: int = 200
    life_loop_daily_llm_token_budget: int = 0
    life_loop_budget_cache_seconds: int = 60
    life_loop_cycle_llm_budget: int = 1
    life_loop_degraded_usage_ratio: float = 0.8
    action_outbox_enabled: bool = False
    life_loop_outbox_max_attempts: int = 5
    life_loop_outbox_backoff_seconds: int = 30
    life_loop_memory_min_salience: float = 0.8
    life_loop_memory_limit: int = 5
    life_loop_memory_digest_chars: int = 600
    life_loop_reflection_check_interval_minutes: int = 240
    life_loop_storm_daily_limit: int = 3
    worker_circuit_breaker_threshold: int = 10
