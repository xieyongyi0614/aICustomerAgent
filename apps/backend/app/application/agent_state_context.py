"""Agent State 上下文通道（AGENT-002）：Run 内组装的 Snapshot 经 contextvar 传递。

前台 chat 与后台 proactive 的 prompt 装配读取同一变量（共用通道）；
Run 结束时调用方负责 reset。Flag 关闭时变量恒为空 → 段不渲染。
"""

from contextvars import ContextVar

from app.models.agent_state import AgentStateSnapshot

_agent_state_snapshot_var: ContextVar[AgentStateSnapshot | None] = ContextVar(
    "agent_state_snapshot", default=None
)


def set_snapshot(snapshot: AgentStateSnapshot) -> None:
    """在当前上下文激活快照；必须在主协程上下文调用（勿在 to_thread 内）。"""
    _agent_state_snapshot_var.set(snapshot)


def clear() -> None:
    _agent_state_snapshot_var.set(None)


def get_snapshot() -> AgentStateSnapshot | None:
    return _agent_state_snapshot_var.get()
