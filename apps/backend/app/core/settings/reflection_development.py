"""Reflection / Development / Relationship Evolution V2 域设置。"""

import json

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class ReflectionSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    reflection_min_confidence: float = 0.6
    reflection_min_evidence: int = 3
    reflection_window_days: int = 30
    reflection_cluster_cosine: float = 0.82
    reflection_min_span_hours: float = 24.0
    reflection_min_coherence: float = 0.5
    reflection_schedule_hour: int = 4
    reflection_event_threshold: int = 3
    reflection_event_cooldown_hours: float = 24.0
    reflection_llm_profile: str = ""
    reflection_evidence_max_members: int = 12
    reflection_evidence_content_chars: int = 200
    reflection_max_insights_per_run: int = 3
    reflection_confidence_count_curve_json: str = (
        '{"3": 0.65, "4": 0.75, "5": 0.85, "6": 0.95}'
    )
    reflection_ai_inferred_cap: float = 0.5
    reflection_run_timeout_minutes: int = 10
    reflection_statement_max_chars: int = 200
    reflection_invalidate_match_threshold: float = 0.7
    reflection_context_scopes_json: str = '["user", "relationship"]'
    reflection_context_max_items: int = 5
    reflection_context_statement_chars: int = 120


class DevelopmentSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    development_preference_max_token_delta: int = 200
    development_preference_tone_rules_json: str = '{"简短": "更简练、直给，不绕弯子"}'
    development_belief_topic_rules_json: str = (
        '{"加班": "工作压力", "压力": "工作压力", "熬夜": "睡眠", "累": "休息"}'
    )
    development_belief_habit_templates_json: str = (
        '{"加班": {"id": "dev_habit_late_care", "domain": "relate", "priority": 3,'
        ' "instruction": "深夜时段主动问一句他的休息状况"},'
        ' "熬夜": {"id": "dev_habit_late_care", "domain": "relate", "priority": 3,'
        ' "instruction": "深夜时段主动问一句他的休息状况"}}'
    )
    development_pattern_goal_tier_delta_max: float = 0.5
    development_answer_min_tokens: int = 300


class RelationshipEvolvedSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    relationship_shared_budget_chars: int = 200
    relationship_shared_limit: int = 3
    relationship_shared_min_salience: float = 0.6
    relationship_pattern_min_strength: float = 0.6
    relationship_pattern_budget_chars: int = 120
    relationship_pattern_max_items: int = 2
    relationship_narrative_min_confidence: float = 0.75
    relationship_narrative_whitelist_json: str = (
        '{"narrative:all_nighter": {"title": "第一次一起熬夜赶工",'
        ' "keywords": ["熬夜", "一起"], "all": true}}'
    )
    relationship_narrative_daily_cap: int = 1
