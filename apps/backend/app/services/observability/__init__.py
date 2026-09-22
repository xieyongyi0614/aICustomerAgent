"""观测服务包（V7.8）。

RT-019 的查询面（`trace_query`）**按需加载**：它依赖 `agent_runtime` 聚合包，
而 `app.chains` → `app.services.observability.llm_capture` 是 LLM 热路径，
模块级导入会把整个运行时拉进该路径并与其构成导入环（`agent_runtime/__init__`
正在初始化时反向导入本包）。故查询面符号经 PEP 562 惰性导出。
"""

from __future__ import annotations

from typing import Any

_QUERY_EXPORTS = frozenset(
    {
        "LAYER_ACTION",
        "LAYER_DECISION",
        "LAYER_TRACE",
        "ReplayBundle",
        "RunDebugView",
        "by_correlation",
        "by_run_id",
        "by_session",
        "replay_bundle",
    }
)

__all__ = sorted(_QUERY_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _QUERY_EXPORTS:
        from app.services.observability import trace_query

        return getattr(trace_query, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
