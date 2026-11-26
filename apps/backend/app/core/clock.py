"""周期内逻辑时钟（tick 级）。

`run_life_loop_tick` / `run_autonomous_cycle` 接受显式 `now`（可注入、可回放），但行动域
此前一律读真实时间，导致同一周期内"组装计划用的时间"与"执行校验用的时间"不是同一口径。
本模块把周期的 `now` 作为上下文变量下发：周期内 `logical_now()` 即周期时间，周期外
（前台对话等无周期场景）回落真实本地时间——与 `observability.current_trace` /
`agent_state_context` 同款手法。
"""

import contextvars
from datetime import datetime
from app.core import timeutil

_logical_now: contextvars.ContextVar[datetime | None] = contextvars.ContextVar(
    "logical_now", default=None
)


def bind(now: datetime | None) -> contextvars.Token:
    """绑定周期时间；返回 token，供 `unbind` 精确还原（支持嵌套）。"""
    return _logical_now.set(now)


def unbind(token: contextvars.Token) -> None:
    _logical_now.reset(token)


def logical_now() -> datetime:
    """当前逻辑时间：已绑定周期则为其 `now`，否则为真实本地时间。"""
    bound = _logical_now.get()
    return timeutil.now() if bound is None else bound
