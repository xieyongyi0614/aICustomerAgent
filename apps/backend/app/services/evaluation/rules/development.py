"""Phase 3 Development 维规则集（DEV-005）：归因完整 + 仲裁一致 + 封顶 + 回退滞后。

纯函数、逐条异常隔离；subjects 含 offline_batch（离线场景集复用）。
developments 切片缺席（None）时全部规则静默跳过——向后兼容既有 turn 评估。
"""

from app.models.evaluation import (
    EvaluationDimension,
    Issue,
    IssueCode,
    build_issue,
)
from app.services.evaluation.context import EvaluationContext
from app.services.evaluation.rules import EvaluationRule
from app.core.settings import get_settings


class ChangeUnattributedRule(EvaluationRule):
    """changes 行缺失或悬空 insight_id → CRITICAL（E-DEV-01 归因完整率兜底闸）。"""

    code = IssueCode.DEVELOPMENT_CHANGE_UNATTRIBUTED
    dimension = EvaluationDimension.DEVELOPMENT
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.development is None:
            return None
        for change in ctx.development.changes:
            if not change.insight_id:
                return build_issue(
                    self.code, evidence_quote=f"change={change.id} insight_id 缺失"
                )
            status = ctx.development.insight_statuses.get(change.insight_id)
            if status is None:
                return build_issue(
                    self.code,
                    evidence_quote=f"change={change.id} 悬空 insight_id={change.insight_id}",
                )
        return None


class ConcurrentActiveRule(EvaluationRule):
    """同 (user, key) 多条 active 调制 → CRITICAL（E-DEV-03 并存生效兜底闸）。"""

    code = IssueCode.DEVELOPMENT_CONCURRENT_ACTIVE
    dimension = EvaluationDimension.DEVELOPMENT
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.development is None:
            return None
        by_key: dict[str, int] = {}
        for state in ctx.development.active_states:
            by_key[state.key] = by_key.get(state.key, 0) + 1
        for key, count in sorted(by_key.items()):
            if count > 1:
                return build_issue(
                    self.code,
                    evidence_quote=f"key={key} 存在 {count} 条 active 调制",
                )
        return None


class OverCapRule(EvaluationRule):
    """调制幅度 > strength × 预设封顶 → WARNING（E-DEV-02 封顶兜底闸）。"""

    code = IssueCode.DEVELOPMENT_OVER_CAP
    dimension = EvaluationDimension.DEVELOPMENT
    subjects = ("turn", "proactive_action", "offline_batch")

    _EPSILON = 1e-6

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.development is None:
            return None

        settings = get_settings()
        for state in ctx.development.active_states:
            amplitude = self._amplitude(state)
            if amplitude is None:
                continue
            cap = self._cap(state.key, settings)
            if cap is None:
                continue
            if amplitude > state.strength * cap + self._EPSILON:
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"key={state.key} 幅度={amplitude} > "
                        f"strength={state.strength:.2f}×封顶={cap}"
                    ),
                )
        return None

    def _amplitude(self, state) -> float | None:
        value = state.value or {}
        if state.key == "response_style.length":
            delta = value.get("max_tokens_delta")
            return abs(float(delta)) if delta is not None else None
        if state.key == "goal.user_care.weight":
            delta = value.get("tier_delta")
            return abs(float(delta)) if delta is not None else None
        return None

    def _cap(self, key: str, settings):
        if key == "response_style.length":
            return settings.development_preference_max_token_delta
        if key == "goal.user_care.weight":
            return settings.development_pattern_goal_tier_delta_max
        return None


class StaleActiveRule(EvaluationRule):
    """active 调制的源 Insight 已失效/被替代 → WARNING（回退滞后信号）。"""

    code = IssueCode.DEVELOPMENT_STALE_ACTIVE
    dimension = EvaluationDimension.DEVELOPMENT
    subjects = ("turn", "proactive_action", "offline_batch")

    def evaluate(self, ctx: EvaluationContext) -> Issue | None:
        if ctx.development is None:
            return None
        for state in ctx.development.active_states:
            status = ctx.development.insight_statuses.get(state.source_insight_id)
            if status is not None and status != "active":
                return build_issue(
                    self.code,
                    evidence_quote=(
                        f"key={state.key} 源 insight={state.source_insight_id} "
                        f"status={status}"
                    ),
                )
        return None


RULES: list[EvaluationRule] = [
    ChangeUnattributedRule(),
    ConcurrentActiveRule(),
    OverCapRule(),
    StaleActiveRule(),
]
