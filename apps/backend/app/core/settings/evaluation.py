"""评估域设置（V7.5 Character Evaluation）：开关、惩罚、权重表。

维度开关命名约定：`evaluation_{EvaluationDimension.value}_enabled`。
读取点经 `DIMENSION_ENABLED_FIELDS` **显式白名单**映射
（`evaluation_rules.rule_active` / `_dimension_enabled`），不再动态拼名 getattr。
关闭某维 = 该维规则全跳过 + 不进 eligible 分数表；LLM Judge 路不受维开关控制。

为什么不用 `getattr(settings, f"..., True")`：字段名拼错或字段被删时，
`getattr(..., True)` 会**静默退化为「永远开启」**——规则照跑、无人知晓开关已失效。
白名单 + `attribute` 访问使缺字段直接抛错（fail-closed）。
"""

import json

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError

DIMENSION_ENABLED_FIELDS: dict[str, str] = {
    "persona": "evaluation_persona_enabled",
    "emotion": "evaluation_emotion_enabled",
    "memory": "evaluation_memory_enabled",
    "behavior": "evaluation_behavior_enabled",
    "autonomy": "evaluation_autonomy_enabled",
    "goal": "evaluation_goal_enabled",
    "reflection": "evaluation_reflection_enabled",
    "relationship": "evaluation_relationship_enabled",
    "action": "evaluation_action_enabled",
    "development": "evaluation_development_enabled",
}
"""维度值 → 开关字段名（`EvaluationDimension.value` 全覆盖）。

新增维度必须同批登记本表；缺登记即 `KeyError`（fail-closed），
不再退化为「无开关 = 永远开启」。字段集合由 `tests/v40/support.py`
的 `BASELINE_ENABLED_FLAGS` 冻结。"""



class EvaluationSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    # 按维策略闸：一维一闸，对应 EvaluationDimension；默认 True，关闭=规则静音
    evaluation_persona_enabled: bool = True
    evaluation_emotion_enabled: bool = True
    evaluation_memory_enabled: bool = True
    evaluation_behavior_enabled: bool = True
    # autonomy 维规则闸（批次 2 已移除其旧的「schedule_proactive_evaluation 整段短路」用途）
    evaluation_autonomy_enabled: bool = True
    evaluation_goal_enabled: bool = True
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
