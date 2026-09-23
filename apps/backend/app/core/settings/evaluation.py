"""评估域设置（V7.5 Character Evaluation）：开关、惩罚、权重表。

维度开关命名约定：`evaluation_{EvaluationDimension.value}_enabled`。
读取点为动态拼名（静态 grep 字段名搜不到消费方）：
  evaluation_rules.rule_active / _dimension_enabled
    → getattr(settings, f"evaluation_{dimension.value}_enabled", True)
关闭某维 = 该维规则全跳过 + 不进 eligible 分数表；LLM Judge 路不受维开关控制。
"""

import json

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class EvaluationSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    evaluation_enabled: bool = True
    # 按维策略闸：一维一闸，对应 EvaluationDimension；默认 True，关闭=规则静音
    evaluation_persona_enabled: bool = True
    evaluation_emotion_enabled: bool = True
    evaluation_memory_enabled: bool = True
    evaluation_behavior_enabled: bool = True
    # 双重职责：autonomy 维规则闸 + schedule_proactive_evaluation 整段短路
    evaluation_autonomy_enabled: bool = True
    evaluation_goal_enabled: bool = True
    evaluation_llm_judge_enabled: bool = True
    evaluation_llm_judge_sample_rate: float = 1.0
    evaluation_judge_profile: str = ""
    evaluation_penalty_critical: float = 0.4
    evaluation_penalty_warning: float = 0.2
    evaluation_penalty_info: float = 0.05
    evaluation_fail_score: float = 0.6
    evaluation_warn_score: float = 0.85
    evaluation_overall_weights_json: str = (
        '{"turn": {"persona": 0.30, "emotion": 0.18, "memory": 0.18,'
        ' "behavior": 0.24, "action": 0.10},'
        ' "proactive_action": {"autonomy": 0.60, "persona": 0.40}}'
    )
    evaluation_behavior_monotony_window: int = 5
    evaluation_behavior_monotony_threshold: int = 3
    evaluation_expression_density_low: float = 0.01
    evaluation_expression_density_high: float = 0.10
    evaluation_memory_missed_min_importance: float = 0.7
    evaluation_memory_missed_min_overlap: float = 0.15
    evaluation_memory_support_min_overlap: float = 0.2
    evaluation_proactive_reply_window_hours: int = 24
    evaluation_retention_days: int = 30
    # 规则级子闸（非维度闸）：只关 WorldConsistencyRule，仍受 evaluation_memory_enabled 罩住
    evaluation_world_consistency_enabled: bool = True
    evaluation_reflection_enabled: bool = True
    evaluation_relationship_enabled: bool = True
    evaluation_action_enabled: bool = True
    # development 维闸（补齐缺口）：V2.0 Phase3 扩维时漏配，此前 getattr 兜底恒 True
    evaluation_development_enabled: bool = True
    evaluation_max_digest_chars: int = 2000

    @model_validator(mode="after")
    def validate_evaluation_config(self):
        if not 0.0 <= self.evaluation_llm_judge_sample_rate <= 1.0:
            raise SettingsError("EVALUATION_LLM_JUDGE_SAMPLE_RATE 必须在 [0, 1]")
        try:
            weights = json.loads(self.evaluation_overall_weights_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"EVALUATION_OVERALL_WEIGHTS_JSON 解析失败: {exc}") from exc
        for subject in ("turn", "proactive_action"):
            table = weights.get(subject)
            if not isinstance(table, dict) or not table:
                raise SettingsError(f"EVALUATION_OVERALL_WEIGHTS_JSON 缺少主体权重表: {subject}")
            for dimension, weight in table.items():
                if not isinstance(weight, (int, float)) or weight < 0:
                    raise SettingsError(
                        f"EVALUATION_OVERALL_WEIGHTS_JSON {subject}.{dimension} 权重非法"
                    )
            total = sum(float(w) for w in table.values())
            if abs(total - 1.0) > 0.01:
                raise SettingsError(f"EVALUATION_OVERALL_WEIGHTS_JSON {subject} 权重之和应为 1.0")
        return self

    def evaluation_overall_weights(self, subject: str) -> dict:
        weights = json.loads(self.evaluation_overall_weights_json)
        return weights.get(subject, {})
