"""全局日 LLM 配额检查器（LIFE-003）。

BudgetState 现算带缓存（不持久化，跨零点日界自动滚动恢复）；用量查询失败
进入保守模式（used 按 limit 记 → 直接 degraded，宁紧勿松）。执行面仅限
Life Loop 周期步骤——前台路径永不熔断（本模块不得被 chat/answer 链引用）。
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from app.core.settings import Settings, get_settings
from app.repositories import llm_call_repository

logger = logging.getLogger(__name__)

_STATUS_OK = "ok"
_STATUS_DEGRADED = "degraded"

_CACHE: dict = {}


@dataclass
class BudgetState:
    status: str
    used_calls: int
    token_total: int
    call_limit: int
    token_limit: int
    reason: str
    checked_at: datetime

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "used_calls": self.used_calls,
            "token_total": self.token_total,
            "call_limit": self.call_limit,
            "token_limit": self.token_limit,
            "reason": self.reason,
        }


def reset_cache() -> None:
    _CACHE.clear()


def check_daily_budget(
    now: datetime | None = None, settings: Settings | None = None
) -> BudgetState:
    """当日用量聚合 → ok|degraded；结果按日缓存 v2_life_loop_budget_cache_seconds。"""
    settings = settings or get_settings()
    now = now or datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cached = _CACHE.get(day_start.date())
    if (
        cached is not None
        and (now - cached.checked_at).total_seconds()
        < settings.v2_life_loop_budget_cache_seconds
    ):
        return cached

    conservative = False
    try:
        usage = llm_call_repository.aggregate_usage_since(day_start)
        used_calls = usage["calls"]
        token_total = usage["tokens"]
    except Exception:
        logger.exception("日 LLM 用量聚合失败，进入保守模式（宁紧勿松）")
        conservative = True
        used_calls = settings.v2_life_loop_daily_llm_call_budget
        token_total = settings.v2_life_loop_daily_llm_token_budget

    call_limit = settings.v2_life_loop_daily_llm_call_budget
    token_limit = settings.v2_life_loop_daily_llm_token_budget
    if conservative:
        # used 未知按 limit 记 → 必然降级；限额按 80% 收紧留痕（宁紧勿松）
        call_limit = int(call_limit * settings.v2_life_loop_degraded_usage_ratio)
        status, reason = _STATUS_DEGRADED, "usage_query_failed_conservative"
    elif call_limit > 0 and used_calls >= call_limit:
        status, reason = _STATUS_DEGRADED, "over_call_limit"
    elif token_limit > 0 and token_total >= token_limit:
        status, reason = _STATUS_DEGRADED, "over_token_limit"
    else:
        status, reason = _STATUS_OK, "within_budget"

    state = BudgetState(
        status=status,
        used_calls=used_calls,
        token_total=token_total,
        call_limit=call_limit,
        token_limit=token_limit,
        reason=reason,
        checked_at=now,
    )
    _CACHE[day_start.date()] = state
    return state


def is_degraded(now: datetime | None = None, settings: Settings | None = None) -> bool:
    return check_daily_budget(now=now, settings=settings).status == _STATUS_DEGRADED
