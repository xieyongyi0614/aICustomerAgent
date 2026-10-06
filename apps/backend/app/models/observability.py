"""V7.8 Observability 域模型（runtime-trace.md §3 / decision-history.md §2 / prompt-debug.md §1 / llm-observability.md §1）。

纯数据定义：RuntimeTrace / TraceStep / TraceEvent / DecisionRecord / PromptSnapshot /
LlmCallRecord / MetricReport；不绑定 LLM、数据库与 HTTP。
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from app.core import ids, timeutil


class TraceKind(StrEnum):
    TURN = "turn"
    PROACTIVE = "proactive"
    AUTONOMY_TICK = "autonomy_tick"


class DecisionKind(StrEnum):
    PROACTIVE_AUTONOMY = "proactive_autonomy"
    TURN_GOAL = "turn_goal"
    TURN_INTENTION = "turn_intention"
    TURN_BEHAVIOR = "turn_behavior"
    GOAL_LIFECYCLE = "goal_lifecycle"


class CallSite(StrEnum):
    ANSWER = "answer"
    ROUTER = "router"
    TURN_ANALYSIS = "turn_analysis"
    SCENE_INTENT = "scene_intent"
    INTENTION = "intention"
    SCENE_UPDATE = "scene_update"
    STATE_UPDATE = "state_update"
    EXTRACTOR = "extractor"
    SUMMARY = "summary"
    PROACTIVE = "proactive"
    JUDGE = "judge"
    REFLECTION = "reflection"


SCHEMA_CALL_SITES: dict[str, CallSite] = {
    "RoleMode": CallSite.ROUTER,
    "TurnAnalysis": CallSite.TURN_ANALYSIS,
    "SceneIntentResult": CallSite.SCENE_INTENT,
    "IntentionDecision": CallSite.INTENTION,
    "SceneActionDecision": CallSite.SCENE_UPDATE,
    "StateUpdateDecision": CallSite.STATE_UPDATE,
    "MemoryExtraction": CallSite.EXTRACTOR,
    "TurnJudgeResult": CallSite.JUDGE,
    "ProactiveJudgeResult": CallSite.JUDGE,
    "ReflectionProposal": CallSite.REFLECTION,
    "ReflectionJudgeResult": CallSite.JUDGE,
}

CAPTURE_MODES = ("disabled", "sampled", "always")

LLM_CALL_OK = "ok"
LLM_CALL_ERROR = "error"


def bound_text(value: str | None, max_chars: int) -> tuple[str, bool]:
    if value is None:
        return "", False
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def bound_extra(extra: dict[str, Any] | None, max_chars: int) -> tuple[dict, bool]:
    """步骤/事件附属数据有界化：超限整体替换为截断摘要，不抛错。"""
    if not extra:
        return {}, False
    serialized = json.dumps(extra, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return extra, False
    return {"truncated_summary": serialized[:max_chars]}, True


def deterministic_sample(key: str, rate: float) -> bool:
    """request_id 确定性采样（口径同 evaluation_engine.should_sample，独立实现不共享代码）。"""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


def new_record_id() -> str:
    return ids.new_id_str()


class TraceStep(BaseModel):
    name: str
    status: str = "ok"
    duration_ms: float = 0.0
    first_token_ms: float | None = None
    error: str | None = None
    extra: dict[str, Any] = {}


class TraceEvent(BaseModel):
    kind: str
    at_ms: float = 0.0
    payload: dict[str, Any] = {}


class RuntimeTrace(BaseModel):
    trace_id: str
    kind: TraceKind = TraceKind.TURN
    user_id: str = ""
    conversation_id: str | None = None
    turn_id: str | None = None
    action_id: str | None = None
    correlation_id: str | None = None
    status: str = "complete"
    started_at: datetime | None = None
    duration_ms: float = 0.0
    steps: list[TraceStep] = []
    events: list[TraceEvent] = []
    token_usage: dict[str, float] = {}
    model_name: str | None = None
    meta: dict[str, Any] = {}

    def api_dict(self) -> dict:
        """与 TurnTraceSession.snapshot() 同构的调试视图（steps 键风格一致），附加观测扩展字段。"""
        return {
            "turn_id": self.turn_id,
            "request_id": self.trace_id,
            "kind": self.kind.value,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "action_id": self.action_id,
            "token_usage": dict(self.token_usage),
            "model_name": self.model_name,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "role_mode": self.meta.get("role_mode"),
            "analysis": self.meta.get("analysis"),
            "behavior": self.meta.get("behavior"),
            "mode": self.meta.get("mode"),
            "total_ms": round(self.duration_ms, 2),
            "steps": [
                {
                    "name": step.name,
                    "status": step.status,
                    "durationMs": step.duration_ms,
                    "firstTokenMs": step.first_token_ms,
                    "error": step.error,
                    **({"extra": step.extra} if step.extra else {}),
                }
                for step in self.steps
            ],
            "events": [event.model_dump() for event in self.events],
        }


class DecisionRecord(BaseModel):
    id: str = Field(default_factory=new_record_id)
    kind: DecisionKind
    request_id: str | None = None
    user_id: str
    conversation_id: str | None = None
    action_id: str | None = None
    trigger: str | None = None
    input_snapshot: dict[str, Any] = {}
    decision: str
    reason: str = ""
    confidence: float | None = None
    outcome: str | None = None
    candidates: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=timeutil.now)


class PromptSnapshot(BaseModel):
    id: str = Field(default_factory=new_record_id)
    request_id: str
    turn_id: str | None = None
    call_site: CallSite
    profile_id: str | None = None
    model: str | None = None
    messages: list[dict[str, Any]] = []
    section_budget: dict[str, Any] | None = None
    truncated: bool = False
    created_at: datetime = Field(default_factory=timeutil.now)


class LlmCallRecord(BaseModel):
    id: str = Field(default_factory=new_record_id)
    request_id: str | None = None
    turn_id: str | None = None
    call_site: CallSite
    profile_id: str | None = None
    model: str | None = None
    provider: str | None = None
    status: str = LLM_CALL_OK
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_estimate: float | None = None
    error_kind: str | None = None
    started_at: datetime | None = None
    created_at: datetime = Field(default_factory=timeutil.now)


def estimate_cost(
    model: str | None, input_tokens: int | None, output_tokens: int | None, cost_table: dict
) -> float | None:
    """单价表（observability_llm_cost_json）按 model 名匹配；未配置或 token 缺失一律 null，绝不估算。"""
    if not model or input_tokens is None or output_tokens is None:
        return None
    price = cost_table.get(model)
    if not isinstance(price, dict):
        return None
    try:
        input_per_mtok = float(price["input_per_mtok"])
        output_per_mtok = float(price["output_per_mtok"])
    except (KeyError, TypeError, ValueError):
        return None
    return (
        input_tokens * input_per_mtok / 1_000_000
        + output_tokens * output_per_mtok / 1_000_000
    )


class StepLatencyStats(BaseModel):
    count: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0


class PipelineMetrics(BaseModel):
    turn_count: int = 0
    e2e_p50_ms: float = 0.0
    e2e_p95_ms: float = 0.0
    steps: dict[str, StepLatencyStats] = {}


class LlmCallSiteStats(BaseModel):
    calls: int = 0
    errors: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0


class LlmMetrics(BaseModel):
    calls: int = 0
    errors: int = 0
    error_rate: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0.0
    by_call_site: dict[str, LlmCallSiteStats] = {}


class IssueCount(BaseModel):
    code: str
    count: int


class QualityMetrics(BaseModel):
    reports: int = 0
    verdict_distribution: dict[str, int] = {}
    dimension_mean: dict[str, float] = {}
    issue_top: list[IssueCount] = []


class ProactiveBusinessStats(BaseModel):
    delivered: int = 0
    acked: int = 0
    failed: int = 0
    ack_rate: float | None = None


class BusinessMetrics(BaseModel):
    conversation_count: int = 0
    message_count: int = 0
    avg_messages_per_conversation: float = 0.0
    response_success_rate: float | None = None
    proactive: ProactiveBusinessStats = ProactiveBusinessStats()


class MetricReport(BaseModel):
    window_hours: float
    generated_at: datetime = Field(default_factory=timeutil.now)
    pipeline: PipelineMetrics = PipelineMetrics()
    llm: LlmMetrics = LlmMetrics()
    quality: QualityMetrics = QualityMetrics()
    business: BusinessMetrics = BusinessMetrics()
