"""记忆域设置：V1 检索/回收 + V2 Memory（衰减/embedding/检索预算/后台任务）。"""

import json
import logging

from pydantic import Field, field_validator, model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings

logger = logging.getLogger(__name__)

_MEMORY_RERANK_MODES = ("off", "lite")
_MEMORY_QUERY_REWRITE_MODES = ("off", "lite")
_MAX_QUERY_REWRITE_QUERIES = 3
_MEMORY_EPISODIC_MODES = ("off", "auto")
_MAX_EPISODIC_WINDOW_HOURS = 168
_MAX_EPISODIC_PER_RUN = 200
_MIN_EPISODIC_EVENTS = 2
_MEMORY_SEMANTIC_MODES = ("off", "auto")
_MIN_SEMANTIC_SOURCES = 2
_MAX_SEMANTIC_PER_RUN = 50
_MEMORY_GRAPH_EXPAND_MODES = ("off", "one_hop")
_MEMORY_LINK_EXTRACT_MODES = ("off", "auto")


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

    memory_eval_threshold_high: float = 0.75
    memory_eval_threshold_low: float = 0.35
    memory_eval_weight_source: float = 0.35
    memory_eval_weight_novelty: float = 0.30
    memory_eval_weight_affinity: float = 0.20
    memory_eval_weight_salience: float = 0.15
    memory_llm_fallback_rate_cap: float = 0.3
    memory_decay_batch_size: int = 200
    memory_forget_retention_days: int = 30
    memory_salience_floor: float = 0.1
    memory_reinforce_boost: float = 0.1
    memory_decay_lambda_json: str = (
        '{"user_preference": 0.01, "user_fact": 0.01,'
        ' "experience": 0.03, "relationship_fact": 0.03,'
        ' "commitment": 0.04, "milestone_event": 0.01,'
        ' "behavior_pattern": 0.05}'
    )
    embedding_batch_size: int = 32
    embedding_batch_window_seconds: int = 60
    embedding_profile: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 768
    embedding_max_input_chars: int = 2000
    memory_retrieval_budget: int = 800
    job_poll_interval: int = 60
    job_max_attempts: int = 5
    job_running_timeout: int = 600
    job_retry_backoff_seconds: int = 60
    memory_weight_semantic: float = 0.45
    memory_weight_structured: float = 0.35
    memory_weight_affinity: float = 0.20
    memory_penalty_rejected: float = 0.2
    memory_penalty_contradicts: float = 0.2
    memory_rejected_cooldown_hours: float = 24.0
    memory_vector_recall_k: int = 20
    memory_temporal_recency_boost: float = 0.2
    memory_ingest_max_per_turn: int = 10
    memory_rerank_mode: str = "off"
    memory_rerank_top_k: int = 20
    memory_rerank_min_candidates: int = 3
    memory_query_rewrite_mode: str = "off"
    memory_query_rewrite_max_queries: int = 2
    memory_episodic_mode: str = "off"
    memory_episodic_window_hours: int = 12
    memory_episodic_min_events: int = 3
    memory_episodic_max_per_run: int = 20
    memory_semantic_mode: str = "off"
    memory_semantic_min_sources: int = 3
    memory_semantic_max_per_run: int = 5
    memory_layer_quota: str = ""
    memory_decay_layer_multiplier_json: str = "{}"
    memory_graph_expand_mode: str = "off"
    memory_graph_expand_seeds: int = Field(default=3, ge=1, le=10)
    memory_graph_expand_decay: float = Field(default=0.7, gt=0.0, le=1.0)
    memory_link_extract_mode: str = "off"
    memory_link_candidate_k: int = Field(default=5, ge=1, le=20)
    memory_link_max_per_run: int = Field(default=20, ge=1, le=200)
    memory_hypothetical_triggers_json: str = (
        '["假装", "如果", "假如", "要是", "扮演", "假设", "作为"]'
    )
    memory_transient_triggers_json: str = (
        '["帮我拿", "帮我递", "递给我", "放到", "放一下", "打开", "关一下", "取下"]'
    )

    def hypothetical_triggers(self) -> list[str]:
        return json.loads(self.memory_hypothetical_triggers_json)

    def transient_triggers(self) -> list[str]:
        return json.loads(self.memory_transient_triggers_json)

    def decay_lambdas(self) -> dict:
        return json.loads(self.memory_decay_lambda_json)

    @field_validator("memory_rerank_mode", mode="before")
    @classmethod
    def normalize_rerank_mode(cls, value) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _MEMORY_RERANK_MODES:
            logger.warning("MEMORY_RERANK_MODE=%r 非法，回落 off", value)
            return "off"
        return mode

    @field_validator("memory_query_rewrite_mode", mode="before")
    @classmethod
    def normalize_query_rewrite_mode(cls, value) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _MEMORY_QUERY_REWRITE_MODES:
            logger.warning("MEMORY_QUERY_REWRITE_MODE=%r 非法，回落 off", value)
            return "off"
        return mode

    @field_validator("memory_episodic_mode", mode="before")
    @classmethod
    def normalize_episodic_mode(cls, value) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _MEMORY_EPISODIC_MODES:
            logger.warning("MEMORY_EPISODIC_MODE=%r 非法，回落 off", value)
            return "off"
        return mode

    @field_validator("memory_semantic_mode", mode="before")
    @classmethod
    def normalize_semantic_mode(cls, value) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _MEMORY_SEMANTIC_MODES:
            logger.warning("MEMORY_SEMANTIC_MODE=%r 非法，回落 off", value)
            return "off"
        return mode

    @field_validator("memory_graph_expand_mode", mode="before")
    @classmethod
    def normalize_graph_expand_mode(cls, value) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _MEMORY_GRAPH_EXPAND_MODES:
            logger.warning("MEMORY_GRAPH_EXPAND_MODE=%r 非法，回落 off", value)
            return "off"
        return mode

    @field_validator("memory_link_extract_mode", mode="before")
    @classmethod
    def normalize_link_extract_mode(cls, value) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _MEMORY_LINK_EXTRACT_MODES:
            logger.warning("MEMORY_LINK_EXTRACT_MODE=%r 非法，回落 off", value)
            return "off"
        return mode

    @model_validator(mode="after")
    def normalize_episodic_limits(self):
        window = max(1, min(self.memory_episodic_window_hours, _MAX_EPISODIC_WINDOW_HOURS))
        min_events = max(_MIN_EPISODIC_EVENTS, self.memory_episodic_min_events)
        max_per_run = max(1, min(self.memory_episodic_max_per_run, _MAX_EPISODIC_PER_RUN))
        if (window, min_events, max_per_run) == (
            self.memory_episodic_window_hours,
            self.memory_episodic_min_events,
            self.memory_episodic_max_per_run,
        ):
            return self
        logger.warning(
            "情景聚合参数越界，已收敛：window %s→%s，min_events %s→%s，max_per_run %s→%s",
            self.memory_episodic_window_hours,
            window,
            self.memory_episodic_min_events,
            min_events,
            self.memory_episodic_max_per_run,
            max_per_run,
        )
        self.memory_episodic_window_hours = window
        self.memory_episodic_min_events = min_events
        self.memory_episodic_max_per_run = max_per_run
        return self

    @model_validator(mode="after")
    def normalize_semantic_limits(self):
        min_sources = max(_MIN_SEMANTIC_SOURCES, self.memory_semantic_min_sources)
        max_per_run = max(
            1, min(self.memory_semantic_max_per_run, _MAX_SEMANTIC_PER_RUN)
        )
        if (min_sources, max_per_run) == (
            self.memory_semantic_min_sources,
            self.memory_semantic_max_per_run,
        ):
            return self
        logger.warning(
            "语义抽象参数越界，已收敛：min_sources %s→%s，max_per_run %s→%s",
            self.memory_semantic_min_sources,
            min_sources,
            self.memory_semantic_max_per_run,
            max_per_run,
        )
        self.memory_semantic_min_sources = min_sources
        self.memory_semantic_max_per_run = max_per_run
        return self

    @model_validator(mode="after")
    def normalize_query_rewrite_limits(self):
        queries = max(
            1, min(self.memory_query_rewrite_max_queries, _MAX_QUERY_REWRITE_QUERIES)
        )
        if queries == self.memory_query_rewrite_max_queries:
            return self
        logger.warning(
            "记忆查询改写上限越界，已收敛：%s→%s",
            self.memory_query_rewrite_max_queries,
            queries,
        )
        self.memory_query_rewrite_max_queries = queries
        return self

    @model_validator(mode="after")
    def normalize_rerank_limits(self):
        top_k = max(1, min(self.memory_rerank_top_k, self.memory_candidate_pool_limit))
        min_candidates = max(1, self.memory_rerank_min_candidates)
        if (top_k, min_candidates) == (
            self.memory_rerank_top_k,
            self.memory_rerank_min_candidates,
        ):
            return self
        logger.warning(
            "记忆重排上限越界，已收敛：top_k %s→%s，min_candidates %s→%s",
            self.memory_rerank_top_k,
            top_k,
            self.memory_rerank_min_candidates,
            min_candidates,
        )
        self.memory_rerank_top_k = top_k
        self.memory_rerank_min_candidates = min_candidates
        return self
