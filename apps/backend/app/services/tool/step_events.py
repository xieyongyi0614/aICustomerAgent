"""工具步骤流式事件（API-002）：独立通道，不写 Agent Loop 台账键集。"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)

# 与 contracts.EVENT_TOOL_STEP 同源的 NDJSON 字面量（wire 形态为 snake_case）
CHAT_EVENT_TOOL_STEP = "tool_step"

STATUS_TODO = "todo"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

LEDGER_RECORD_TOOL_ID = "builtin.ledger.record"

DEFAULT_STEP_PLANS: dict[str, list[dict]] = {
    LEDGER_RECORD_TOOL_ID: [
        {"step_id": "ledger.extract_amount", "label": "提取金额"},
        {"step_id": "ledger.classify", "label": "识别分类"},
        {"step_id": "ledger.resolve_time", "label": "确认时间"},
        {
            "step_id": "ledger.persist",
            "label": "保存账单",
            "target": "已同步到「生活 · 记账」",
        },
    ],
}


@dataclass(frozen=True)
class ToolStepEvent:
    step_id: str
    tool_id: str
    label: str
    status: str
    detail: str | None = None
    target: str | None = None

    def to_ndjson_dict(self) -> dict:
        payload = {
            "type": CHAT_EVENT_TOOL_STEP,
            "step_id": self.step_id,
            "tool_id": self.tool_id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "target": self.target,
        }
        return payload


class ToolStepSink(Protocol):
    def emit(self, event: ToolStepEvent) -> None: ...


@dataclass
class CollectingToolStepSink:
    """turn 局部 sink：收集事件供 chat 流排空。"""

    _events: list[ToolStepEvent] = field(default_factory=list)

    def emit(self, event: ToolStepEvent) -> None:
        self._events.append(event)

    def drain(self) -> list[ToolStepEvent]:
        pending = list(self._events)
        self._events.clear()
        return pending


_current_sink: ContextVar[ToolStepSink | None] = ContextVar(
    "tool_step_sink", default=None
)


def bind_tool_step_sink(sink: ToolStepSink | None) -> Token:
    return _current_sink.set(sink)


def reset_tool_step_sink(token: Token) -> None:
    _current_sink.reset(token)


def emit_tool_step(
    *,
    step_id: str,
    tool_id: str,
    label: str,
    status: str,
    detail: str | None = None,
    target: str | None = None,
) -> None:
    """失败只记日志，不阻断主回答流。"""
    sink = _current_sink.get()
    if sink is None:
        return
    try:
        sink.emit(
            ToolStepEvent(
                step_id=step_id,
                tool_id=tool_id,
                label=label,
                status=status,
                detail=detail,
                target=target,
            )
        )
    except Exception:
        logger.exception("tool_step sink emit failed")


def plan_for(tool_id: str) -> list[dict]:
    return list(DEFAULT_STEP_PLANS.get(tool_id, []))


def emit_todo_plan(tool_id: str) -> None:
    for step in plan_for(tool_id):
        emit_tool_step(
            step_id=step["step_id"],
            tool_id=tool_id,
            label=step["label"],
            status=STATUS_TODO,
            detail=step.get("detail"),
            target=step.get("target"),
        )


def advance_plan(
    tool_id: str,
    *,
    up_to: int,
    status: str,
    details: dict | None = None,
) -> None:
    """按段边界推进计划：≤up_to-1 done，==up_to 为 status，其余 todo。"""
    plan = plan_for(tool_id)
    if not plan:
        return
    for i, step in enumerate(plan):
        if i < up_to:
            step_status = STATUS_DONE
        elif i == up_to:
            step_status = status
        else:
            step_status = STATUS_TODO
        emit_tool_step(
            step_id=step["step_id"],
            tool_id=tool_id,
            label=step["label"],
            status=step_status,
            detail=(details or {}).get(step["step_id"], step.get("detail")),
            target=step.get("target") if step_status == STATUS_DONE else None,
        )


def complete_plan(tool_id: str, *, ok: bool, details: dict | None = None) -> None:
    plan = plan_for(tool_id)
    if not plan:
        return
    final = STATUS_DONE if ok else STATUS_FAILED
    for i, step in enumerate(plan):
        last = i == len(plan) - 1
        step_status = final if last or ok else STATUS_DONE
        if not ok and last:
            step_status = STATUS_FAILED
        elif not ok and i < len(plan) - 1:
            step_status = STATUS_DONE
        else:
            step_status = STATUS_DONE
        emit_tool_step(
            step_id=step["step_id"],
            tool_id=tool_id,
            label=step["label"],
            status=step_status,
            detail=(details or {}).get(step["step_id"], step.get("detail")),
            target=step.get("target") if step_status == STATUS_DONE else None,
        )
