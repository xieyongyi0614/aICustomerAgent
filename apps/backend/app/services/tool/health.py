"""V2.4.0 工具健康度与熔断（architecture.md §5.7 / TOOL-003 §2.3、§4.5）。

内存态（重启归零），写入面只有 `record_outcome()` 与熔断置位/解除：

```text
record_outcome(ok=True)  → consecutive_failures=0，解除熔断
record_outcome(ok=False) → consecutive_failures += 1；达阈值即置位并记 tripped_at
tripped 且 now - tripped_at >= 冷却 → 半开：解除熔断，consecutive_failures 保留
                                     （下次失败立即重熔）
```

半开评估发生在 `is_tripped()` / `record_outcome()`；冷却期内再次失败**不重置** tripped_at
（E13）。熔断消费方是 `ToolRegistry.effective_status()`（读 `health.tripped` 返回 disabled），
因此熔断工具自动从工具面消失。并发语义沿用 V9 per-user 写锁，不另加并发控制（E14）。
"""

from collections.abc import Callable
from datetime import datetime

from app.core.settings import get_settings
from app.models.tool import ToolHealth
from app.services.tool.registry import ToolRegistry


class ToolHealthTracker:
    """连续失败计数 / 熔断 / 冷却半开；计数与滑动窗复用 registry 既有写入面。"""

    def __init__(
        self,
        registry: ToolRegistry,
        settings=None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings if settings is not None else get_settings()
        self._clock = clock or datetime.now
        self._tripped_at: dict[str, datetime] = {}

    @property
    def threshold(self) -> int:
        return int(getattr(self._settings, "v24_tool_breaker_threshold", 3))

    @property
    def cooldown_seconds(self) -> float:
        return float(getattr(self._settings, "v24_tool_breaker_cooldown_seconds", 300))

    def record_outcome(
        self, tool_id: str, *, ok: bool, failure_kind: str | None = None
    ) -> None:
        """记录一次执行结果；未注册工具由 registry 静默忽略（不打断执行链）。"""
        self._registry.record_outcome(tool_id, ok=ok, failure_kind=failure_kind)
        record = self._registry.health(tool_id).get(tool_id)
        if record is None:
            return
        now = self._clock()
        if ok:
            self._registry.clear_tripped(tool_id)
            self._tripped_at.pop(tool_id, None)
            return
        if record.consecutive_failures >= self.threshold and not record.tripped:
            self._registry.mark_tripped(tool_id)
            self._tripped_at[tool_id] = now
        self._evaluate_half_open(tool_id, now)

    def is_tripped(self, tool_id: str, now: datetime | None = None) -> bool:
        """熔断判定；顺带做冷却半开评估（消费方读 `effective_status` 前应先调用）。"""
        self._evaluate_half_open(tool_id, now if now is not None else self._clock())
        record = self._registry.health(tool_id).get(tool_id)
        return bool(record is not None and record.tripped)

    def snapshot(self, tool_id: str | None = None) -> dict[str, ToolHealth]:
        """只读健康度快照（副本），不触发半开评估、不改写状态。"""
        return self._registry.health(tool_id)

    def _evaluate_half_open(self, tool_id: str, now: datetime) -> None:
        record = self._registry.health(tool_id).get(tool_id)
        if record is None or not record.tripped:
            return
        tripped_at = self._tripped_at.get(tool_id)
        if tripped_at is None:
            self._tripped_at[tool_id] = now
            return
        if (now - tripped_at).total_seconds() >= self.cooldown_seconds:
            self._registry.clear_tripped(tool_id)
