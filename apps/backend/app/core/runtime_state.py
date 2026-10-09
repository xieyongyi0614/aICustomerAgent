"""跨层共享运行态：per-user 写锁、生成中登记、Life Loop 记忆摘要上下文。

由 application 层下沉（反向依赖清理，2026-09-30）：services 经 `core` 合法
读写同一份状态，application 各模块亦从本模块导入，消除 services → application
反向依赖。

**单实例约束**：本模块全部状态为进程内内存，多实例（横向扩容 / 多 worker）
下互斥与「生成中」判定不会跨进程生效 → 静默的数据正确性问题。
`assert_single_instance_runtime()` 在启动期 fail-closed 拦住这种部署形态，
直到状态外置为共享存储（Redis）为止。
"""

import asyncio
import contextvars

from app.core.settings import get_settings

_user_write_locks: dict[str, asyncio.Lock] = {}


def get_user_write_lock(user_id: str) -> asyncio.Lock:
    """per-user 写锁公共入口（REF-010）；V7 Executor 复用同一把锁。"""
    return _user_write_locks.setdefault(user_id, asyncio.Lock())


def reset_user_write_locks() -> None:
    _user_write_locks.clear()


active_generations: dict[str, bool] = {}


def assert_single_instance_runtime() -> None:
    """启动期守卫：多实例部署下拒绝启动。

    本模块的写锁与生成态为进程内内存，多实例时：
    - 同一用户可被两台实例并发写（账本 / 关系 / 角色状态竞态）；
    - 实例 A 生成中，实例 B 仍判定该用户「空闲」→ 主动消息打断。

    这类问题**静默发生**（不崩溃、只产生重复或丢失），故按 fail-closed 处理：
    配置了多实例就拒绝启动，直到本状态外置为共享存储（见架构审查 P0 / T-31）。
    单实例（默认 `FEISHU_INSTANCE_COUNT=1`）不受影响。
    """
    instance_count = get_settings().feishu_instance_count
    if instance_count > 1:
        raise RuntimeError(
            f"检测到多实例部署配置（FEISHU_INSTANCE_COUNT={instance_count}），"
            "但运行时写锁与生成态仍为进程内内存（app/core/runtime_state.py），"
            "多实例下会产生静默的并发写竞态与主动消息打断。"
            "请先完成运行时状态外置（Redis）或改回单实例部署。"
        )


memory_digest_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "life_loop_memory_digest", default=None
)
