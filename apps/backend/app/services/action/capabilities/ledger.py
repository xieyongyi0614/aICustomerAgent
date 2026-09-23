"""PLA-009 ledger 能力：记账 / 查账 / 冲正（ADR-10 能力是手脚不是逻辑）。

只做结构化执行：校验必填 → 调 PLA-005 写面 / PLA-006 聚合 → 返回 CapabilityResult。
拒绝自由文本入参；金额必须为整数分；幂等键必填；失败返回 ok=False 语义（status=failed），
不抛裸异常、不做决策 / 重试 / 回复生成。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.action import ActionSchema, CapabilityResult
from app.models.ledger import LedgerEntryDraft
from app.services.action.registry import ExecutionContext

FREE_TEXT_PARAM_KEYS: frozenset[str] = frozenset(
    {"message", "text", "raw", "content", "utterance", "query_text", "sentence"}
)

LEDGER_DIRECTIONS: tuple[str, ...] = ("expense", "income", "transfer")
LEDGER_SOURCES: tuple[str, ...] = ("conversation", "action", "manual", "import")
LEDGER_PERIODS: tuple[str, ...] = ("month", "week")


def _reject_free_text(params: dict) -> list[str]:
    return [f"拒绝自由文本入参: {key}" for key in FREE_TEXT_PARAM_KEYS if key in params]


def _validate_amount_minor(_name: str, value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return "amount_minor 必须为整数分"
    if value <= 0:
        return "amount_minor 必须为正"
    return None


def _validate_direction(_name: str, value: Any) -> str | None:
    if value not in LEDGER_DIRECTIONS:
        return "非法 direction"
    return None


def _validate_source(_name: str, value: Any) -> str | None:
    if value not in LEDGER_SOURCES:
        return "非法 source"
    return None


def _validate_idempotency_key(_name: str, value: Any) -> str | None:
    if not isinstance(value, str) or len(value.strip()) < 8:
        return "idempotency_key 至少 8 位"
    return None


def _validate_occurred_at(_name: str, value: Any) -> str | None:
    if isinstance(value, datetime):
        return None
    try:
        datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "occurred_at 无法解析"
    return None


def _parse_occurred_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _failed(error: str, *, failure_kind: str = "permanent") -> CapabilityResult:
    return CapabilityResult(
        status="failed", error=error, payload={"failure_kind": failure_kind}
    )


def _account_id_for(ctx: ExecutionContext, params: dict) -> str:
    from app.repositories import ledger_repository
    from app.services.ledger import ensure_user_bootstrap

    ensure_user_bootstrap(ctx.user_id, now=ctx.now)
    account_id = params.get("account_id")
    if account_id:
        return str(account_id)
    account, _created = ledger_repository.ensure_default_account(ctx.user_id, now=ctx.now)
    return account.id


class LedgerCapability:
    name = "ledger"
    description = "账本记账/查账/冲正：结构化事实入账，append-only 可对账"
    actions = {
        "record": ActionSchema(
            required=["amount_minor", "direction", "source", "idempotency_key"],
            optional={
                "currency": "ISO-4217",
                "category_id": "类目 id",
                "account_id": "账户 id",
                "occurred_at": "ISO 时间",
                "merchant": "商户",
                "note": "备注",
                "source_ref": "来源引用",
            },
            validators={
                "amount_minor": _validate_amount_minor,
                "direction": _validate_direction,
                "source": _validate_source,
                "idempotency_key": _validate_idempotency_key,
                "occurred_at": _validate_occurred_at,
            },
        ),
        "query": ActionSchema(
            required=["period"],
            optional={
                "group_by": "category/account/direction",
                "category_id": "类目 id",
                "account_id": "账户 id",
                "limit": "条目上限",
            },
        ),
        "revise": ActionSchema(
            required=["entry_id", "reason", "idempotency_key"],
            validators={"idempotency_key": _validate_idempotency_key},
        ),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        errors = _reject_free_text(params)
        schema = self.actions.get(action)
        if schema is None:
            return errors + [f"未知动作: {action}"]
        return errors + schema.validate(params)

    async def execute(
        self, action: str, params: dict, ctx: ExecutionContext
    ) -> CapabilityResult:
        try:
            if action == "record":
                return self._record(params, ctx)
            if action == "query":
                return self._query(params, ctx)
            if action == "revise":
                return self._revise(params, ctx)
            return _failed(f"未知动作: {action}")
        except Exception as exc:  # noqa: BLE001 — 能力失败一律归一，不抛裸异常
            return _failed(f"{exc.__class__.__name__}: {exc}"[:80], failure_kind="transient")

    def _record(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        from app.services.ledger import record_entry

        errors = self.validate("record", params)
        if errors:
            return _failed("; ".join(errors)[:80])
        settings = ctx.settings
        currency = str(params.get("currency") or getattr(settings, "ledger_default_currency", "CNY"))
        occurred_at = _parse_occurred_at(params.get("occurred_at") or (ctx.now or datetime.now()))
        draft = LedgerEntryDraft(
            user_id=ctx.user_id,
            account_id=_account_id_for(ctx, params),
            category_id=params.get("category_id"),
            amount_minor=int(params["amount_minor"]),
            currency=currency,
            direction=str(params["direction"]),
            occurred_at=occurred_at,
            merchant=params.get("merchant"),
            note=params.get("note"),
            source=str(params["source"]),
            source_ref=params.get("source_ref"),
            idempotency_key=str(params["idempotency_key"]),
        )
        outcome = record_entry(draft, idempotency_key=str(params["idempotency_key"]), now=ctx.now)
        return CapabilityResult(
            status="succeeded",
            payload={
                "entry_id": outcome.entry.id,
                "created": outcome.created,
                "reason": outcome.reason,
                "amount_minor": int(outcome.entry.amount_minor),
                "direction": outcome.entry.direction,
                "failure_kind": None,
            },
        )

    def _query(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        from app.services.ledger.query import Period, summary

        errors = self.validate("query", params)
        if errors:
            return _failed("; ".join(errors)[:80])
        period_name = str(params.get("period") or "month")
        if period_name not in LEDGER_PERIODS:
            return _failed("非法 period")
        anchor = ctx.now or datetime.now()
        period = Period.month(anchor) if period_name == "month" else Period.week(anchor)
        data = summary(ctx.user_id, period=period, now=ctx.now)
        return CapabilityResult(
            status="succeeded",
            payload={
                "period": period.label,
                "expense_minor": data.expense_minor,
                "income_minor": data.income_minor,
                "net_minor": data.net_minor,
                "entry_count": data.entry_count,
                "reversal_count": data.reversal_count,
                "failure_kind": None,
            },
        )

    def _revise(self, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        from app.services.ledger import reverse_entry

        errors = self.validate("revise", params)
        if errors:
            return _failed("; ".join(errors)[:80])
        outcome = reverse_entry(
            str(params["entry_id"]),
            reason=str(params["reason"]),
            idempotency_key=str(params["idempotency_key"]),
            now=ctx.now,
        )
        return CapabilityResult(
            status="succeeded",
            payload={
                "entry_id": outcome.entry.id,
                "reversal_of": outcome.entry.reversal_of,
                "created": outcome.created,
                "reason": outcome.reason,
                "failure_kind": None,
            },
        )


__all__ = [
    "FREE_TEXT_PARAM_KEYS",
    "LEDGER_DIRECTIONS",
    "LEDGER_PERIODS",
    "LEDGER_SOURCES",
    "LedgerCapability",
]
