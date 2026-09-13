"""LLM Gateway（AGENT-001 §2.6）：调用权收归的唯一裁决面。

能力注册表覆盖既有全部 call_site（CallSite 枚举即能力名）；四问裁决
（是否/何时/哪档/多少预算）在 acquire 处统一执行；run 级账户 + 全局日
配额（LIFE-003 既有熔断）两级记账。未切换的调用点行为不变（§2.6 渐进迁移）。
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from app.core.settings import get_settings
from app.models.observability import CallSite
from app.services import life_loop_budget

logger = logging.getLogger(__name__)

CAPABILITY_ANSWER = CallSite.ANSWER.value
CAPABILITY_PROACTIVE = CallSite.PROACTIVE.value

_FOREGROUND_DECISION_CAPABILITIES: tuple[str, ...] = (
    CallSite.ROUTER.value,
    CallSite.TURN_ANALYSIS.value,
    CallSite.SCENE_INTENT.value,
    CallSite.INTENTION.value,
)

_CAPABILITY_DEFAULTS: dict[str, tuple[str, str, bool]] = {
    "answer": ("main", "foreground", True),
    "router": ("light", "foreground", True),
    "turn_analysis": ("light", "foreground", True),
    "scene_intent": ("light", "foreground", True),
    "intention": ("light", "foreground", True),
    "scene_update": ("light", "foreground", True),
    "state_update": ("light", "background", True),
    "extractor": ("light", "background", True),
    "summary": ("light", "background", True),
    "proactive": ("main", "background", True),
    "judge": ("light", "background", True),
    "reflection": ("light", "background", True),
}


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    tier: str
    budget_type: str
    degradable: bool


@dataclass(frozen=True)
class Grant:
    granted: bool
    degraded: bool
    reason: str


class GatewayDeniedError(RuntimeError):
    """enforced 模式下 LLM 能力被拒绝（无规则兜底路径可用）。"""


CAPABILITIES: dict[str, CapabilitySpec] = {
    name: CapabilitySpec(name=name, tier=tier, budget_type=budget, degradable=deg)
    for name, (tier, budget, deg) in _CAPABILITY_DEFAULTS.items()
}


def register(spec: CapabilitySpec) -> None:
    CAPABILITIES[spec.name] = spec


def get_capability(name: str) -> CapabilitySpec:
    try:
        return CAPABILITIES[name]
    except KeyError as exc:
        raise ValueError(f"未注册的 LLM 能力：{name}") from exc


def _run_llm_limit(run_kind: str, settings) -> int:
    if run_kind == "foreground_chat":
        return max(settings.v21_foreground_run_llm_budget, 0)
    if run_kind == "autonomous_tick":
        return max(settings.v2_life_loop_cycle_llm_budget, 0)
    return 0


def acquire(
    user_id: str | None,
    capability: str,
    run=None,
    now: datetime | None = None,
    account: bool = True,
) -> Grant:
    """四问裁决入口：全局熔断 → run 级账户 → 记账放行。

    account=False 为「只问不记账」（决策管线的风险闸预检），不消耗 run 预算。
    前台能力默认软模式（只记账标记 degraded，不拒绝用户回复），
    v21_foreground_gateway_enforced=true 时才硬拒绝。
    """
    spec = get_capability(capability)
    settings = get_settings()
    now = now or datetime.now()
    if life_loop_budget.is_degraded(now=now):
        if spec.budget_type == "foreground" and not settings.v21_foreground_gateway_enforced:
            if account:
                _account(run, degraded=True)
            return Grant(True, True, "quota_circuit_open_soft")
        return Grant(False, False, "quota_circuit_open")
    if run is not None and run.llm_calls >= _run_llm_limit(run.run_kind, settings):
        if spec.budget_type == "foreground" and not settings.v21_foreground_gateway_enforced:
            if account:
                run.degraded = True
            return Grant(True, True, "run_budget_soft")
        return Grant(False, False, "run_budget_exhausted")
    if account:
        _account(run, degraded=False)
    return Grant(True, False, "ok")


def _account(run, degraded: bool) -> None:
    if run is None:
        return
    run.llm_calls += 1
    if degraded:
        run.degraded = True


def account_turn_decisions(run) -> None:
    """前台轮内决策四链的记账入口（不拒绝，链本体自带异常降级）。"""
    if run is None:
        return
    for name in _FOREGROUND_DECISION_CAPABILITIES:
        acquire(run.user_id, name, run)


def resolve_answer_llm(run, llm, now: datetime | None = None):
    """answer 能力裁决：放行原 llm → 降档 light（配置了 profile 时）→ 拒绝。

    仅 enforced 且无降档配置时抛 GatewayDeniedError；默认软模式永不阻塞回复。
    """
    settings = get_settings()
    grant = acquire(run.user_id if run else None, CAPABILITY_ANSWER, run, now=now)
    if grant.granted and not grant.degraded:
        return llm
    light = _build_light_llm(settings)
    if light is not None:
        if run is not None:
            run.degraded = True
        logger.warning("answer 能力降档（%s）：%s", grant.reason, settings.v21_light_llm_profile)
        return light
    if not grant.granted and settings.v21_foreground_gateway_enforced:
        raise GatewayDeniedError(f"llm gateway denied: {grant.reason}")
    if run is not None:
        run.degraded = True
    return llm


def _build_light_llm(settings):
    profile_id = settings.v21_light_llm_profile
    if not profile_id:
        return None
    try:
        from app.core import llm_factory

        return llm_factory.get_llm(profile_id)
    except Exception:
        logger.exception("light profile 构建失败，降级为原 llm")
        return None
