"""Agent Runtime（V2.1.0 AGENT-001）：统一 Run 模型 / Trigger Router / LLM Gateway。

Life Loop Controller 的推广而非新 Agent：前台 chat_pipeline 与后台
自主周期经本包统一为 Run（open → stages → close），LLM 调用决策收归
Gateway。领域层零感知。
"""

from app.application.agent_runtime.contracts import (
    AgentRuntime,
    ErrorKind,
    LoopStage,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeFailure,
    RuntimeInput,
    SessionContext,
    terminal_status_for,
)
from app.application.agent_runtime.controller import (
    append_step,
    close_run,
    open_foreground_run,
    open_run,
    run_autonomous_cycle,
    run_event_pregate,
    run_stage_async,
)
from app.application.agent_runtime.llm_gateway import (
    GatewayDeniedError,
    Grant,
    acquire,
    account_turn_decisions,
    get_capability,
    register,
    resolve_answer_llm,
)
from app.application.agent_runtime.models import RunContext
from app.application.agent_runtime.profiles import get_profile, snapshot_profile
from app.application.agent_runtime.session import (
    SessionCloseSummary,
    build_session_context,
    close_session,
    open_session,
    resume_session,
)
from app.application.agent_runtime.trigger_router import (
    classify_background_trigger,
    classify_channel_message,
    evaluate_event_escalation,
)

__all__ = [
    "AgentRuntime",
    "ErrorKind",
    "GatewayDeniedError",
    "Grant",
    "LoopStage",
    "RunContext",
    "RunResult",
    "RunStatus",
    "RuntimeEvent",
    "RuntimeFailure",
    "RuntimeInput",
    "SessionCloseSummary",
    "SessionContext",
    "account_turn_decisions",
    "acquire",
    "append_step",
    "build_session_context",
    "classify_background_trigger",
    "classify_channel_message",
    "close_run",
    "close_session",
    "evaluate_event_escalation",
    "get_capability",
    "get_profile",
    "open_foreground_run",
    "open_run",
    "open_session",
    "register",
    "resolve_answer_llm",
    "resume_session",
    "run_autonomous_cycle",
    "run_event_pregate",
    "run_stage_async",
    "snapshot_profile",
    "terminal_status_for",
]
