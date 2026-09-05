import json
import logging
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

TRACE_STEP_NAMES = (
    "role_router",
    "turn_analyzer",
    "scene_intent",
    "intention",
    "goal_selection",
    "scene_resolver",
    "scene_update",
    "memory_retrieval",
    "memory_retrieve_v2",
    "context_assemble_v2",
    "context_builder",
    "prompt_builder",
    "mode_stabilize",
    "behavior_engine",
    "llm",
    "state_update",
    "emotion_update",
    "relationship_event",
    "goal_review",
    "budget_observer",
    "memory_extractor",
    "memory_extract",
    "memory_ingest",
    "memory_evaluate",
    "memory_embed",
    "memory_command",
    "memory_policy",
    "memory_privacy",
    "memory_conflict",
    "evaluation",
    "evaluation_judge",
    "world_context",
    "world_update",
    "action_detect",
    "action_execute",
    "action_planning",
)

_BACKGROUND_STEPS = (
    "state_update",
    "emotion_update",
    "relationship_event",
    "memory_extractor",
    "scene_update",
    "goal_review",
)


def _jsonable(value) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


@dataclass
class TraceStep:
    name: str
    duration_ms: float
    status: str = "ok"
    first_token_ms: float | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class TurnTraceSession:
    role_mode: object | None = None
    analysis: object | None = None
    behavior_meta: dict | None = None
    mode_meta: dict | None = None
    turn_id: str | None = None
    steps: list[TraceStep] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)
    token_usage: dict = field(default_factory=dict)
    model_name: str | None = None
    llm_calls: list = field(default_factory=list)
    prompt_snapshots: list = field(default_factory=list)
    obs_flushed: bool = False

    def add_token_usage(self, usage: dict) -> None:
        for key, value in usage.items():
            self.token_usage[key] = self.token_usage.get(key, 0) + value

    def record(
        self,
        name: str,
        duration_ms: float,
        status: str = "ok",
        first_token_ms: float | None = None,
        error: str | None = None,
        **extra,
    ) -> None:
        try:
            self.steps.append(
                TraceStep(
                    name=name,
                    duration_ms=round(duration_ms, 2),
                    status=status,
                    first_token_ms=(
                        round(first_token_ms, 2) if first_token_ms is not None else None
                    ),
                    error=error,
                    extra=extra,
                )
            )
        except Exception:
            logger.exception("trace 记录失败，忽略")

    def mark_status(self, name: str, status: str) -> None:
        try:
            for step in reversed(self.steps):
                if step.name == name:
                    step.status = status
                    return
        except Exception:
            logger.exception("trace 状态改写失败，忽略")

    def set_meta(self, role_mode, analysis) -> None:
        try:
            self.role_mode = role_mode
            self.analysis = analysis
        except Exception:
            logger.exception("trace 元数据写入失败，忽略")

    @property
    def is_complete(self) -> bool:
        recorded = {step.name for step in self.steps}
        return all(name in recorded for name in _BACKGROUND_STEPS)

    def snapshot(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "request_id": self.request_id,
            "token_usage": dict(self.token_usage),
            "model_name": self.model_name,
            "status": "complete" if self.is_complete else "pending",
            "role_mode": self.role_mode.model_dump() if self.role_mode is not None else None,
            "analysis": self.analysis.model_dump() if self.analysis is not None else None,
            "behavior": self.behavior_meta,
            "mode": self.mode_meta,
            "total_ms": round(sum(step.duration_ms for step in self.steps), 2),
            "steps": [
                {
                    "name": step.name,
                    "status": step.status,
                    "durationMs": step.duration_ms,
                    "firstTokenMs": step.first_token_ms,
                    "error": step.error,
                    **(
                        {"extra": {k: v for k, v in step.extra.items() if _jsonable(v)}}
                        if step.extra
                        else {}
                    ),
                }
                for step in self.steps
            ],
        }


class TraceCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, TurnTraceSession] = {}
        self._finished: OrderedDict[str, TurnTraceSession] = OrderedDict()

    def begin_trace(self) -> TurnTraceSession:
        session = TurnTraceSession()
        key = uuid.uuid4().hex
        with self._lock:
            self._pending[key] = session
        session._pending_key = key
        return session

    def attach(self, session: TurnTraceSession, turn_id: str) -> None:
        capacity = get_settings().trace_capacity
        with self._lock:
            self._finished[turn_id] = session
            self._finished.move_to_end(turn_id)
            while len(self._finished) > capacity:
                self._finished.popitem(last=False)
            pending_key = getattr(session, "_pending_key", None)
            if pending_key is not None:
                self._pending.pop(pending_key, None)
            session.turn_id = turn_id

    def get(self, turn_id: str) -> TurnTraceSession | None:
        with self._lock:
            session = self._finished.get(turn_id)
            if session is not None:
                return session
            for pending in self._pending.values():
                if pending.turn_id == turn_id:
                    return pending
            return None

    def latest(self) -> TurnTraceSession | None:
        with self._lock:
            if not self._finished:
                return None
            turn_id = next(reversed(self._finished))
            return self._finished[turn_id]


_collector: TraceCollector | None = None


def get_trace_collector() -> TraceCollector:
    global _collector
    if _collector is None:
        _collector = TraceCollector()
    return _collector


def reset_trace_collector() -> None:
    global _collector
    _collector = TraceCollector()
