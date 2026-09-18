"""Agent Evolution Worker（V2.1.0 AGENT-005/006 慢时钟接线）。

架构 §1.2 的慢时钟（评估 → 演化）必须由周期任务驱动，否则 Evolution Engine
与 Agent Evaluation 只是「存在但从不运行」的代码。本模块是二者的唯一调度入口：
日级指标快照（幂等窗口）+ 人格编译 / Goal Rebalance（建议生成，周级限速兜底）。

全部行为置于 v21 子闸之后：两闸皆关时不注册（lifespan 层判定），
Flag 关闭时零写入、零 LLM。
"""

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.repositories import agent_metric_repository, conversation_repository
from app.services import agent_evaluation, evolution
from app.application.worker_loop import run_worker_loop

logger = logging.getLogger(__name__)

def metrics_enabled() -> bool:
    return get_settings().agent_metrics_enabled

def evolution_enabled() -> bool:
    return get_settings().personality_evolution_enabled


def enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.agent_runtime_enabled
        and (settings.agent_metrics_enabled or settings.personality_evolution_enabled)
    )


def run_evolution_tick(now: datetime | None = None) -> dict:
    """一次慢时钟 tick：逐用户评估快照 + 演化编译。

    指标快照按窗口幂等（同一窗口已落行则跳过，避免覆盖当日趋势基线）；
    人格编译与 Goal Rebalance 由引擎自身的周级限速兜底，可安全高频调用。
    """
    if not enabled():
        return {"status": "skipped", "skip_reason": "flag_disabled"}
    now = now or datetime.now()
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {"users": 0, "snapshots": 0, "personality": 0, "rebalance": 0}
    for user_id in conversation_repository.list_user_ids():
        stats["users"] += 1
        if metrics_enabled() and agent_metric_repository.get_window(user_id, window_start) is None:
            try:
                agent_evaluation.run_daily_snapshot(user_id, now)
                stats["snapshots"] += 1
            except Exception:
                logger.exception("指标快照失败：%s", user_id)
        if evolution_enabled():
            try:
                stats["personality"] += len(evolution.compile_personality(user_id, now))
            except Exception:
                logger.exception("人格编译失败：%s", user_id)
            try:
                stats["rebalance"] += len(evolution.rebalance_goals(user_id, now))
            except Exception:
                logger.exception("goal rebalance 失败：%s", user_id)
    return {"status": "ok", **stats}


async def run_agent_evolution_worker(interval: float | None = None) -> None:
    """常驻循环（lifespan 内注册）；异常退避由 worker_loop 统一承担。"""
    seconds = interval or get_settings().agent_evolution_interval_seconds
    await run_worker_loop(
        "agent evolution worker",
        run_evolution_tick,
        max(float(seconds), 1.0),
        offload=True,
    )
