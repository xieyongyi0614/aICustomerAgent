"""记忆域设置：V1 检索/回收 + V2 Memory（衰减/embedding/检索预算/后台任务）。"""

import json

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class MemorySettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    memory_importance_threshold: float = 0.6
    memory_top_k: int = 5
    memory_max_candidates: int = 3
    memory_conflict_threshold: float = 0.6
    memory_min_confidence: float = 0.6
    memory_min_score: float = 0.15
    memory_reclaim_interval_seconds: int = 3600
    memory_recent_context_messages: int = 4
    memory_weight_lexical: float = 0.45
    memory_weight_importance: float = 0.25
    memory_weight_recency: float = 0.20
    memory_weight_type_affinity: float = 0.10
    memory_recency_half_life_days: float = 30.0
    memory_context_char_budget: int = 400
    memory_candidate_pool_limit: int = 200
    memory_reclaim_batch_limit: int = 500

    v2_memory_enabled: bool = False
    v2_memory_vector_enabled: bool = False
    v2_memory_eval_threshold_high: float = 0.75
    v2_memory_eval_threshold_low: float = 0.35
    v2_memory_eval_weight_source: float = 0.35
    v2_memory_eval_weight_novelty: float = 0.30
    v2_memory_eval_weight_affinity: float = 0.20
    v2_memory_eval_weight_salience: float = 0.15
    v2_memory_llm_fallback_rate_cap: float = 0.3
    v2_memory_decay_batch_size: int = 200
    v2_memory_forget_retention_days: int = 30
    v2_memory_salience_floor: float = 0.1
    v2_memory_reinforce_boost: float = 0.1
    v2_memory_decay_lambda_json: str = (
        '{"user_preference": 0.01, "user_fact": 0.01,'
        ' "experience": 0.03, "relationship_fact": 0.03,'
        ' "commitment": 0.04, "milestone_event": 0.01,'
        ' "behavior_pattern": 0.05}'
    )
    v2_embedding_batch_size: int = 32
    v2_embedding_batch_window_seconds: int = 60
    v2_embedding_profile: str = ""
    v2_embedding_model: str = ""
    v2_embedding_dimensions: int = 768
    v2_embedding_max_input_chars: int = 2000
    v2_memory_retrieval_budget: int = 800
    v2_job_poll_interval: int = 60
    v2_job_max_attempts: int = 5
    v2_job_running_timeout: int = 600
    v2_job_retry_backoff_seconds: int = 60
    v2_memory_weight_semantic: float = 0.45
    v2_memory_weight_structured: float = 0.35
    v2_memory_weight_affinity: float = 0.20
    v2_memory_penalty_rejected: float = 0.2
    v2_memory_penalty_contradicts: float = 0.2
    v2_memory_rejected_cooldown_hours: float = 24.0
    v2_memory_vector_recall_k: int = 20
    v2_memory_temporal_recency_boost: float = 0.2
    v2_memory_ingest_max_per_turn: int = 10
    v2_memory_hypothetical_triggers_json: str = (
        '["假装", "如果", "假如", "要是", "扮演", "假设", "作为"]'
    )
    v2_memory_transient_triggers_json: str = (
        '["帮我拿", "帮我递", "递给我", "放到", "放一下", "打开", "关一下", "取下"]'
    )

    def v2_memory_hypothetical_triggers(self) -> list[str]:
        return json.loads(self.v2_memory_hypothetical_triggers_json)

    def v2_memory_transient_triggers(self) -> list[str]:
        return json.loads(self.v2_memory_transient_triggers_json)

    def v2_memory_decay_lambdas(self) -> dict:
        return json.loads(self.v2_memory_decay_lambda_json)
