"""LLM 预算闸只读/裁决门面（R-6）。

`services` 不得 import `application.agent_runtime`；Gateway 能力注册仍在
`application/agent_runtime/llm_gateway.py`，预算预检走本模块（零应用依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core import timeutil
from app.core.settings import get_settings
from app.services.life import budget as life_loop_budget


@dataclass(frozen=True, slots=True)
class BudgetGrant:
    granted: bool
    degraded: bool
    reason: str


def _run_llm_limit(run_kind: str, settings) -> int:
    if run_kind == "foreground_chat":
        return max(settings.foreground_run_llm_budget, 0)
    if run_kind == "autonomous_tick":
        return max(settings.life_loop_cycle_llm_budget, 0)
    return 0


def preview_budget(
    user_id: str | None,
    run=None,
    now: datetime | None = None,
    *,
    budget_type: str = "background",
) -> BudgetGrant:
    """四问中的「是否/多少预算」预检（account=False 语义）：只问不记账。"""
    settings = get_settings()
    now = timeutil.ensure_aware(now) or timeutil.now()
    if life_loop_budget.is_degraded(now=now):
        if budget_type == "foreground" and not settings.foreground_gateway_enforced:
            return BudgetGrant(True, True, "quota_circuit_open_soft")
        return BudgetGrant(False, False, "quota_circuit_open")
    if run is not None and run.llm_calls >= _run_llm_limit(run.run_kind, settings):
        if budget_type == "foreground" and not settings.foreground_gateway_enforced:
            return BudgetGrant(True, True, "run_budget_soft")
        return BudgetGrant(False, False, "run_budget_exhausted")
    return BudgetGrant(True, False, "ok")
