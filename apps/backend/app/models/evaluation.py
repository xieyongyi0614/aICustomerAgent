"""V7.5 Evaluation 域模型（evaluation-model.md）。

纯数据定义：EvaluationReport / DimensionScore / Issue / IssueCode；
不绑定 LLM、数据库与 HTTP。IssueCode 是全系统唯一事实源（编码表见 evaluation-model.md §3）。
"""

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

EvaluationVerdict = Literal["pass", "warn", "fail"]

ISSUE_SOURCE = Literal["rule", "llm"]

CONTEXT_FIDELITY = Literal["live", "reconstructed"]

EVIDENCE_MAX_LENGTH = 80


class EvaluationDimension(StrEnum):
    PERSONA = "persona"
    EMOTION = "emotion"
    MEMORY = "memory"
    BEHAVIOR = "behavior"
    AUTONOMY = "autonomy"
    RELATIONSHIP = "relationship"


class EvaluationSubjectKind(StrEnum):
    TURN = "turn"
    PROACTIVE_ACTION = "proactive_action"
    OFFLINE_BATCH = "offline_batch"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class IssueCode(StrEnum):
    PERSONA_ABUSIVE_LANGUAGE = "persona_abusive_language"
    PERSONA_CONTRADICTION_PATTERN = "persona_contradiction_pattern"
    PERSONA_OOC = "persona_ooc"
    PERSONA_KNOWLEDGE_LEAK = "persona_knowledge_leak"
    EMOTION_UNTRIGGERED_SHIFT = "emotion_untriggered_shift"
    EMOTION_TEXT_STATE_CONFLICT = "emotion_text_state_conflict"
    EMOTION_OVERSHIFT = "emotion_overshift"
    MEMORY_FABRICATION_CANDIDATE = "memory_fabrication_candidate"
    MEMORY_FABRICATION = "memory_fabrication"
    MEMORY_CONTRADICTION = "memory_contradiction"
    MEMORY_MISSED = "memory_missed"
    MEMORY_WORLD_INCONSISTENCY = "memory_world_inconsistency"
    BEHAVIOR_BUDGET_EXCEEDED = "behavior_budget_exceeded"
    BEHAVIOR_CONTACT_VIOLATION = "behavior_contact_violation"
    BEHAVIOR_ACTION_MONOTONY = "behavior_action_monotony"
    BEHAVIOR_EXPRESSION_MISMATCH = "behavior_expression_mismatch"
    AUTONOMY_TIMING_VIOLATION = "autonomy_timing_violation"
    AUTONOMY_REDUNDANT = "autonomy_redundant"
    AUTONOMY_UNNECESSARY = "autonomy_unnecessary"
    AUTONOMY_LOW_OUTCOME = "autonomy_low_outcome"
    RELATIONSHIP_JUMP = "relationship_jump"
    RELATIONSHIP_UNCAUSED_CHANGE = "relationship_uncaused_change"
    RELATIONSHIP_RATE_VIOLATION = "relationship_rate_violation"
    CONFLICT_STATE_INVALID = "conflict_state_invalid"


DEFAULT_SEVERITY: dict[IssueCode, IssueSeverity] = {
    IssueCode.PERSONA_ABUSIVE_LANGUAGE: IssueSeverity.CRITICAL,
    IssueCode.PERSONA_CONTRADICTION_PATTERN: IssueSeverity.WARNING,
    IssueCode.PERSONA_OOC: IssueSeverity.WARNING,
    IssueCode.PERSONA_KNOWLEDGE_LEAK: IssueSeverity.WARNING,
    IssueCode.EMOTION_UNTRIGGERED_SHIFT: IssueSeverity.WARNING,
    IssueCode.EMOTION_TEXT_STATE_CONFLICT: IssueSeverity.WARNING,
    IssueCode.EMOTION_OVERSHIFT: IssueSeverity.WARNING,
    IssueCode.MEMORY_FABRICATION_CANDIDATE: IssueSeverity.WARNING,
    IssueCode.MEMORY_FABRICATION: IssueSeverity.CRITICAL,
    IssueCode.MEMORY_CONTRADICTION: IssueSeverity.WARNING,
    IssueCode.MEMORY_MISSED: IssueSeverity.INFO,
    IssueCode.MEMORY_WORLD_INCONSISTENCY: IssueSeverity.INFO,
    IssueCode.BEHAVIOR_BUDGET_EXCEEDED: IssueSeverity.WARNING,
    IssueCode.BEHAVIOR_CONTACT_VIOLATION: IssueSeverity.WARNING,
    IssueCode.BEHAVIOR_ACTION_MONOTONY: IssueSeverity.WARNING,
    IssueCode.BEHAVIOR_EXPRESSION_MISMATCH: IssueSeverity.INFO,
    IssueCode.AUTONOMY_TIMING_VIOLATION: IssueSeverity.WARNING,
    IssueCode.AUTONOMY_REDUNDANT: IssueSeverity.WARNING,
    IssueCode.AUTONOMY_UNNECESSARY: IssueSeverity.WARNING,
    IssueCode.AUTONOMY_LOW_OUTCOME: IssueSeverity.INFO,
    IssueCode.RELATIONSHIP_JUMP: IssueSeverity.CRITICAL,
    IssueCode.RELATIONSHIP_UNCAUSED_CHANGE: IssueSeverity.CRITICAL,
    IssueCode.RELATIONSHIP_RATE_VIOLATION: IssueSeverity.WARNING,
    IssueCode.CONFLICT_STATE_INVALID: IssueSeverity.CRITICAL,
}

ISSUE_MESSAGES: dict[IssueCode, str] = {
    IssueCode.PERSONA_ABUSIVE_LANGUAGE: "回复命中辱骂/攻击性表达，严重偏离角色设定",
    IssueCode.PERSONA_CONTRADICTION_PATTERN: "回复命中角色人设矛盾表达模式",
    IssueCode.PERSONA_OOC: "语气/价值观偏离角色人格",
    IssueCode.PERSONA_KNOWLEDGE_LEAK: "说出角色世界观之外的知识",
    IssueCode.EMOTION_UNTRIGGERED_SHIFT: "无足够触发事件的情绪切换",
    IssueCode.EMOTION_TEXT_STATE_CONFLICT: "回复文本情绪信号与当前状态冲突",
    IssueCode.EMOTION_OVERSHIFT: "相对触发事件情绪强度或转向过度",
    IssueCode.MEMORY_FABRICATION_CANDIDATE: "引述用户信息缺少记忆与近期对话支撑（候选）",
    IssueCode.MEMORY_FABRICATION: "虚构了用户从未提供过的信息",
    IssueCode.MEMORY_CONTRADICTION: "回复与既有记忆矛盾",
    IssueCode.MEMORY_MISSED: "高相关高重要度记忆未被使用",
    IssueCode.MEMORY_WORLD_INCONSISTENCY: "回复宣称的世界物品状态与 World 事实矛盾",
    IssueCode.BEHAVIOR_BUDGET_EXCEEDED: "动作描写数量超出预算",
    IssueCode.BEHAVIOR_CONTACT_VIOLATION: "身体接触等级超出预算",
    IssueCode.BEHAVIOR_ACTION_MONOTONY: "近期窗口内同类动作连续堆砌",
    IssueCode.BEHAVIOR_EXPRESSION_MISMATCH: "情绪表达浓度与指令档位偏差",
    IssueCode.AUTONOMY_TIMING_VIOLATION: "主动消息发送时点违反时机约束",
    IssueCode.AUTONOMY_REDUNDANT: "主动消息与近期对话重复，无信息增量",
    IssueCode.AUTONOMY_UNNECESSARY: "触发理由不足以支撑主动打扰",
    IssueCode.AUTONOMY_LOW_OUTCOME: "观察窗内无 ack 且无用户回复",
    IssueCode.RELATIONSHIP_JUMP: "关系维度单轮变化量超出单轮上限",
    IssueCode.RELATIONSHIP_UNCAUSED_CHANGE: "关系状态变化无法对账到账本/里程碑/结算",
    IssueCode.RELATIONSHIP_RATE_VIOLATION: "关系维度当日累计超出日上限",
    IssueCode.CONFLICT_STATE_INVALID: "冲突状态机出现非法迁移或状态行不一致",
}


class Issue(BaseModel):
    code: IssueCode
    severity: IssueSeverity
    dimension: EvaluationDimension
    message: str = Field(default="", max_length=200)
    evidence_quote: str = Field(default="", max_length=EVIDENCE_MAX_LENGTH)
    source: ISSUE_SOURCE = "rule"


class DimensionScore(BaseModel):
    dimension: EvaluationDimension
    score: float = Field(ge=0.0, le=1.0)
    rule_score: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_score: float | None = Field(default=None, ge=0.0, le=1.0)
    issue_codes: list[IssueCode] = []


class EvaluationMeta(BaseModel):
    model_name: str | None = None
    judge_used: bool = False
    judge_sampled: bool = False
    context_fidelity: CONTEXT_FIDELITY = "live"
    rule_codes_fired: list[IssueCode] = []
    duration_ms: float = 0.0
    request_id: str | None = None


class EvaluationReport(BaseModel):
    id: str
    subject: EvaluationSubjectKind
    subject_id: str
    session_id: str | None = None
    user_id: str
    character_id: str = "asuna"
    scores: dict[EvaluationDimension, DimensionScore] = {}
    overall_score: float | None = Field(default=None, ge=0.0, le=1.0)
    verdict: EvaluationVerdict
    issues: list[Issue] = []
    context_digest: dict = {}
    meta: EvaluationMeta = Field(default_factory=EvaluationMeta)
    created_at: datetime


def compute_verdict(
    issues: list[Issue],
    overall_score: float | None,
    fail_score: float,
    warn_score: float,
) -> EvaluationVerdict:
    """verdict 判定（evaluation-model.md §2）：critical 短路 fail；offline_batch 无 overall 时按 issues 映射。"""
    if any(issue.severity == IssueSeverity.CRITICAL for issue in issues):
        return "fail"
    if overall_score is None:
        if any(issue.severity == IssueSeverity.WARNING for issue in issues):
            return "warn"
        return "pass"
    if overall_score < fail_score:
        return "fail"
    if overall_score < warn_score:
        return "warn"
    return "pass"


def overall_score_from(scores: dict[EvaluationDimension, DimensionScore], weights: dict) -> float | None:
    """按主体权重表加权；分母只含有分维度，缺席维度不参与归一化。"""
    if not scores:
        return None
    total_weight = 0.0
    weighted = 0.0
    for dimension, score in scores.items():
        weight = float(weights.get(dimension.value, 0.0))
        weighted += score.score * weight
        total_weight += weight
    if total_weight <= 0.0:
        return None
    return max(0.0, min(1.0, weighted / total_weight))


def build_issue(code: IssueCode, evidence_quote: str = "", source: ISSUE_SOURCE = "rule") -> Issue:
    return Issue(
        code=code,
        severity=DEFAULT_SEVERITY[code],
        dimension=dimension_of(code),
        message=ISSUE_MESSAGES[code],
        evidence_quote=evidence_quote[:EVIDENCE_MAX_LENGTH],
        source=source,
    )


_DIMENSION_BY_CODE: dict[IssueCode, EvaluationDimension] = {}
for _code in IssueCode:
    try:
        _DIMENSION_BY_CODE[_code] = EvaluationDimension(_code.value.split("_", 1)[0])
    except ValueError:
        _DIMENSION_BY_CODE[_code] = EvaluationDimension.RELATIONSHIP
_DIMENSION_BY_CODE[IssueCode.CONFLICT_STATE_INVALID] = EvaluationDimension.RELATIONSHIP


def dimension_of(code: IssueCode) -> EvaluationDimension:
    return _DIMENSION_BY_CODE[code]


def clamp_score(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(1.0, value))
