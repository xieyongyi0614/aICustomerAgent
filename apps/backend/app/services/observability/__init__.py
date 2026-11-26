"""观测服务包（V7.8）。

RT-019 的仓储级查询面（`trace_query`）**按需加载**：`app.chains` →
`app.services.observability.llm_capture` 是 LLM 热路径，模块级导入会把它拉进该路径。
故查询面符号经 PEP 562 惰性导出。

本包**只依赖 `app.repositories`**；运行时语义派生与回放组合见
`app/application/agent_runtime/debug_view.py`（H-2 分层裁决）。
"""

from __future__ import annotations

from typing import Any

_QUERY_EXPORTS = frozenset(
    {
        "LAYER_ACTION",
        "LAYER_DECISION",
        "LAYER_TRACE",
        "RunDebugView",
        "by_correlation",
        "by_run_id",
        "by_session",
    }
)

__all__ = sorted(_QUERY_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _QUERY_EXPORTS:
        from app.services.observability import trace_query

        return getattr(trace_query, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
