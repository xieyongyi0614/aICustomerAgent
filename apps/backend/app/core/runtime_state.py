"""跨层共享运行态：per-user 写锁、生成中登记、Life Loop 记忆摘要上下文。

由 application 层下沉（反向依赖清理，2026-09-30）：services 经 `core` 合法
读写同一份状态，application 各模块亦从本模块导入，消除 services → application
反向依赖。
"""

import asyncio
import contextvars

_user_write_locks: dict[str, asyncio.Lock] = {}


def get_user_write_lock(user_id: str) -> asyncio.Lock:
    """per-user 写锁公共入口（REF-010）；V7 Executor 复用同一把锁。"""
    return _user_write_locks.setdefault(user_id, asyncio.Lock())


def reset_user_write_locks() -> None:
    _user_write_locks.clear()


active_generations: dict[str, bool] = {}

memory_digest_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "life_loop_memory_digest", default=None
)
