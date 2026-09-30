"""PLA-015 账本查询 API：只做表现，零仓储与 LLM 依赖。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.auth import require_user
from app.services.ledger import budget as budget_service
from app.services.ledger import category as category_service
from app.services.ledger import correction as correction_service
from app.services.ledger import format as format_service
from app.services.ledger import pending as pending_service
from app.services.ledger import query as query_service
from app.services.ledger import stats as stats_service
from app.services.ledger import service as ledger_service

ledger_router = APIRouter(prefix="/ledger", tags=["ledger"])

LIMIT_DEFAULT = 50
LIMIT_MAX = 200


class PeriodResponse(BaseModel):
    since: str
    until: str
    label: str


class CategoryTotalResponse(BaseModel):
    category_id: str | None
    net_minor: int
    expense_minor: int
    income_minor: int


class ComparisonResponse(BaseModel):
    expense_delta: int
    income_delta: int
    expense_ratio: float | None


class LedgerSummaryResponse(BaseModel):
    period: PeriodResponse
    expense_minor: int
    expense_text: str
    income_minor: int
    income_text: str
    net_minor: int
    net_text: str
    transfer_minor: int
    by_category: list[CategoryTotalResponse]
    entry_count: int
    reversal_count: int
    compared_to_previous: ComparisonResponse | None


class LedgerEntryResponse(BaseModel):
    id: str
    account_id: str
    category_id: str | None
    amount_minor: int
    amount_text: str
    currency: str
    direction: str
    occurred_at: str
    merchant: str | None
    note: str | None
    source: str
    source_ref: str | None
    idempotency_key: str
    reversal_of: str | None


class LedgerEntryListResponse(BaseModel):
    items: list[LedgerEntryResponse]
    total: int
    limit: int
    offset: int


class LedgerEntryCreateRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    direction: Literal["expense", "income", "transfer"]
    category_id: str | None = None
    account_id: str | None = None
    occurred_at: datetime | None = None
    merchant: str | None = None
    note: str | None = None
    idempotency_key: str | None = None


class LedgerReverseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = None


class CorrectionResponse(BaseModel):
    original_entry_id: str
    reversal_entry_id: str
    new_entry_id: str | None
    net_effect_minor: int


class LedgerCategoryResponse(BaseModel):
    id: str
    name: str
    kind: str
    parent_id: str | None
    aliases: list[str]


class BudgetUpsertRequest(BaseModel):
    scope: Literal["total", "category"] = "total"
    category_id: str | None = None
    period: Literal["month", "week"] = "month"
    limit_minor: int = Field(gt=0)
    currency: str = "CNY"


class BudgetResponse(BaseModel):
    goal_id: str
    scope: str
    category_id: str | None
    period: str
    limit_minor: int
    limit_text: str
    currency: str
    consumed_minor: int = 0
    consumed_text: str = "0.00"
    remaining_minor: int = 0
    breached: bool = False
    reason: str = "ok"


class PendingCandidateResponse(BaseModel):
    value: str
    label: str


class PendingAiGuessResponse(BaseModel):
    category_hint: str | None = None
    direction: str | None = None
    merchant_hint: str | None = None
    confidence: float = 0.0


class PendingItemResponse(BaseModel):
    pending_key: str
    reason: str
    question: str
    candidates: list[PendingCandidateResponse]
    amount_minor: int | None = None
    source_ref: str = ""
    expires_at: str
    occurred_at_hint: str | None = None
    ai_guess: PendingAiGuessResponse | None = None


class PendingListResponse(BaseModel):
    generated_at: str
    total: int
    degraded: int = 0
    items: list[PendingItemResponse]


class PendingConfirmRequest(BaseModel):
    category_name: str | None = None
    direction: Literal["expense", "income", "transfer"] | None = None
    amount_minor: int | None = Field(default=None, gt=0)
    occurred_at: datetime | None = None


class PendingConfirmResponse(BaseModel):
    entry_id: str
    created: bool
    learned_alias: str | None = None


class PendingIgnoreResponse(BaseModel):
    ok: bool
    pending_key: str


class AutoCategoryResponse(BaseModel):
    category_id: str | None
    category_name: str
    net_minor: int
    count: int


class AutoSummaryResponse(BaseModel):
    period: PeriodResponse
    auto_count: int
    pending_count: int
    by_category: list[AutoCategoryResponse]
    generated_at: str


class LearnedRuleResponse(BaseModel):
    keyword: str
    category_id: str
    category_name: str


class LearnedRulesResponse(BaseModel):
    generated_at: str
    total: int
    items: list[LearnedRuleResponse]


class ClassifyPreviewResponse(BaseModel):
    matched: bool
    category_id: str | None = None
    category_name: str
    confidence: float
    reason: str
    is_fallback: bool


def _money(minor: int) -> tuple[int, str]:
    return int(minor), format_service.format_minor(int(minor))


def _entry_out(item) -> LedgerEntryResponse:
    amount_minor, amount_text = _money(item.amount_minor)
    return LedgerEntryResponse(
        id=item.id,
        account_id=item.account_id,
        category_id=item.category_id,
        amount_minor=amount_minor,
        amount_text=amount_text,
        currency=item.currency,
        direction=item.direction,
        occurred_at=item.occurred_at.isoformat(),
        merchant=item.merchant,
        note=item.note,
        source=item.source,
        source_ref=item.source_ref,
        idempotency_key=item.idempotency_key,
        reversal_of=item.reversal_of,
    )


@ledger_router.get("/summary", response_model=LedgerSummaryResponse)
def get_summary(
    period: str = Query(default="month", pattern="^(month|week|custom)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    user_id: str = Depends(require_user),
):
    current = user_id
    now = datetime.now()
    if period == "custom":
        if since is None or until is None:
            raise HTTPException(status_code=400, detail="custom 期间需要 since 与 until")
        window = query_service.Period.custom(since, until)
    elif period == "week":
        window = query_service.Period.week(now)
    else:
        window = query_service.Period.month(now)
    data = query_service.summary(current, period=window, now=now, compare_previous=True)
    exp_minor, exp_text = _money(data.expense_minor)
    inc_minor, inc_text = _money(data.income_minor)
    net_minor, net_text = _money(data.net_minor)
    by_category = [
        CategoryTotalResponse(
            category_id=key,
            net_minor=int(value),
            expense_minor=max(0, -int(value)),
            income_minor=max(0, int(value)),
        )
        for key, value in data.by_category.items()
    ]
    compared = None
    if data.compared_to_previous is not None:
        compared = ComparisonResponse(
            expense_delta=int(data.compared_to_previous.expense_delta),
            income_delta=int(data.compared_to_previous.income_delta),
            expense_ratio=data.compared_to_previous.expense_ratio,
        )
    return LedgerSummaryResponse(
        period=PeriodResponse(
            since=data.period.since.isoformat(),
            until=data.period.until.isoformat(),
            label=data.period.label,
        ),
        expense_minor=exp_minor,
        expense_text=exp_text,
        income_minor=inc_minor,
        income_text=inc_text,
        net_minor=net_minor,
        net_text=net_text,
        transfer_minor=int(data.transfer_minor),
        by_category=by_category,
        entry_count=data.entry_count,
        reversal_count=data.reversal_count,
        compared_to_previous=compared,
    )


@ledger_router.get("/entries", response_model=LedgerEntryListResponse)
def list_entries_endpoint(
    limit: int = Query(default=LIMIT_DEFAULT, ge=1),
    offset: int = Query(default=0, ge=0),
    category_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    direction: str | None = Query(default=None, pattern="^(expense|income|transfer)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    user_id: str = Depends(require_user),
):
    if limit > LIMIT_MAX:
        raise HTTPException(status_code=400, detail=f"limit 不能超过 {LIMIT_MAX}")
    current = user_id
    window = None
    if since is not None or until is not None:
        window = query_service.Period.custom(
            since or datetime.min, until or datetime.max
        )
    items = query_service.list_entries(
        current,
        period=window,
        category_id=category_id,
        account_id=account_id,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    total = len(items) if offset == 0 and limit >= LIMIT_MAX else offset + len(items)
    return LedgerEntryListResponse(
        items=[_entry_out(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@ledger_router.post("/entries", response_model=LedgerEntryResponse)
def create_entry(
    body: LedgerEntryCreateRequest,
    user_id: str = Depends(require_user),
):
    current = user_id
    from app.models.ledger import LedgerEntryDraft

    idempotency_key = body.idempotency_key or _auto_key(current, body)
    account_id = ledger_service.resolve_account_id(current, body.account_id)
    draft = LedgerEntryDraft(
        user_id=current,
        account_id=account_id,
        category_id=body.category_id,
        amount_minor=body.amount_minor,
        direction=body.direction,
        occurred_at=body.occurred_at or datetime.now(),
        merchant=body.merchant,
        note=body.note,
        source="manual",
        idempotency_key=idempotency_key,
    )
    try:
        outcome = ledger_service.record_entry(draft, idempotency_key=idempotency_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:80]) from exc
    created = outcome.entry
    return _entry_out(created)


def _auto_key(user_id: str, body: LedgerEntryCreateRequest) -> str:
    import hashlib

    material = f"{user_id}|{body.amount_minor}|{body.direction}|{body.category_id}|{body.occurred_at}"
    return "manual-" + hashlib.sha1(material.encode()).hexdigest()[:16]


@ledger_router.post("/entries/{entry_id}/reverse", response_model=CorrectionResponse)
def reverse_entry(
    entry_id: str,
    body: LedgerReverseRequest = Body(default_factory=lambda: LedgerReverseRequest(reason="订正")),
    _user_id: str = Depends(require_user),
):
    key = body.idempotency_key or f"rev-{entry_id}"
    try:
        outcome = correction_service.cancel_entry(
            entry_id, reason=body.reason, idempotency_key=key
        )
    except Exception as exc:
        message = str(exc)
        if "不存在" in message:
            raise HTTPException(status_code=404, detail="条目不存在") from exc
        raise HTTPException(status_code=400, detail=message[:80]) from exc
    return CorrectionResponse(
        original_entry_id=outcome.original_entry_id,
        reversal_entry_id=outcome.reversal_entry_id,
        new_entry_id=outcome.new_entry_id,
        net_effect_minor=outcome.net_effect_minor,
    )


@ledger_router.get("/categories", response_model=list[LedgerCategoryResponse])
def list_categories(user_id: str = Depends(require_user)):
    rows = category_service.list_user_categories(user_id)
    return [
        LedgerCategoryResponse(
            id=row.id,
            name=row.name,
            kind=row.kind,
            parent_id=row.parent_id,
            aliases=list(row.aliases or []),
        )
        for row in rows
    ]


@ledger_router.get("/budgets", response_model=list[BudgetResponse])
def list_budgets(user_id: str = Depends(require_user)):
    checks = budget_service.check_all_budgets(user_id, now=datetime.now())
    out = []
    for check in checks:
        limit_minor, limit_text = _money(check.budget.limit_minor)
        consumed_minor, consumed_text = _money(check.consumed_minor)
        out.append(
            BudgetResponse(
                goal_id=check.budget.goal_id,
                scope=check.budget.scope,
                category_id=check.budget.category_id,
                period=check.budget.period,
                limit_minor=limit_minor,
                limit_text=limit_text,
                currency=check.budget.currency,
                consumed_minor=consumed_minor,
                consumed_text=consumed_text,
                remaining_minor=int(check.remaining_minor),
                breached=check.breached,
                reason=check.reason,
            )
        )
    return out


@ledger_router.put("/budgets", response_model=BudgetResponse)
def upsert_budget(
    body: BudgetUpsertRequest,
    user_id: str = Depends(require_user),
):
    spec = budget_service.BudgetSpec(
        user_id=user_id,
        scope=body.scope,
        category_id=body.category_id,
        period=body.period,
        limit_minor=body.limit_minor,
        goal_id="",
        currency=body.currency,
    )
    saved = budget_service.upsert_budget(spec, now=datetime.now())
    check = budget_service.check_budget(user_id, saved, now=datetime.now())
    limit_minor, limit_text = _money(saved.limit_minor)
    consumed_minor, consumed_text = _money(check.consumed_minor)
    return BudgetResponse(
        goal_id=saved.goal_id,
        scope=saved.scope,
        category_id=saved.category_id,
        period=saved.period,
        limit_minor=limit_minor,
        limit_text=limit_text,
        currency=saved.currency,
        consumed_minor=consumed_minor,
        consumed_text=consumed_text,
        remaining_minor=int(check.remaining_minor),
        breached=check.breached,
        reason=check.reason,
    )


def _pending_item_out(item) -> dict:
    payload = {
        "pending_key": item.pending_key,
        "reason": item.reason,
        "question": item.question,
        "candidates": [
            {"value": option.value, "label": option.label}
            for option in item.candidates
        ],
        "amount_minor": item.amount_minor,
        "source_ref": item.source_ref,
        "expires_at": item.expires_at.isoformat(),
        "occurred_at_hint": item.occurred_at_hint,
    }
    if item.has_ai_guess:
        payload["ai_guess"] = {
            "category_hint": item.category_hint,
            "direction": item.direction,
            "merchant_hint": item.merchant_hint,
            "confidence": item.confidence,
        }
    return payload


@ledger_router.get(
    "/pending",
    response_model=PendingListResponse,
    response_model_exclude_unset=True,
)
def list_pending_endpoint(
    limit: int = Query(default=LIMIT_DEFAULT, ge=1, le=LIMIT_MAX),
    user_id: str = Depends(require_user),
):
    data = pending_service.list_pending(user_id, limit=limit)
    return {
        "generated_at": data.generated_at.isoformat(),
        "total": data.total,
        "degraded": data.degraded,
        "items": [_pending_item_out(item) for item in data.items],
    }


@ledger_router.post(
    "/pending/{pending_key}/confirm", response_model=PendingConfirmResponse
)
def confirm_pending_endpoint(
    pending_key: str,
    body: PendingConfirmRequest | None = Body(default=None),
    user_id: str = Depends(require_user),
):
    payload = body or PendingConfirmRequest()
    try:
        outcome = pending_service.confirm_pending(
            user_id,
            pending_key,
            category_name=payload.category_name,
            direction=payload.direction,
            amount_minor=payload.amount_minor,
            occurred_at=payload.occurred_at,
        )
    except pending_service.PendingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="待确认条目不存在或已失效") from exc
    except pending_service.PendingValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:80]) from exc
    return PendingConfirmResponse(
        entry_id=outcome.entry_id,
        created=outcome.created,
        learned_alias=outcome.learned_alias,
    )


@ledger_router.post(
    "/pending/{pending_key}/ignore", response_model=PendingIgnoreResponse
)
def ignore_pending_endpoint(
    pending_key: str,
    user_id: str = Depends(require_user),
):
    try:
        key = pending_service.ignore_pending(user_id, pending_key)
    except pending_service.PendingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="待确认条目不存在或已失效") from exc
    return PendingIgnoreResponse(ok=True, pending_key=key)


@ledger_router.get("/auto-summary", response_model=AutoSummaryResponse)
def get_auto_summary(
    period: Literal["month", "week"] = Query(default="month"),
    user_id: str = Depends(require_user),
):
    now = datetime.now()
    window = (
        query_service.Period.week(now)
        if period == "week"
        else query_service.Period.month(now)
    )
    data = stats_service.auto_summary(user_id, period=window, now=now)
    return AutoSummaryResponse(
        period=PeriodResponse(
            since=data.period.since.isoformat(),
            until=data.period.until.isoformat(),
            label=data.period.label,
        ),
        auto_count=data.auto_count,
        pending_count=data.pending_count,
        by_category=[
            AutoCategoryResponse(
                category_id=item.category_id,
                category_name=item.category_name,
                net_minor=item.net_minor,
                count=item.count,
            )
            for item in data.by_category
        ],
        generated_at=data.generated_at.isoformat(),
    )


@ledger_router.get("/rules", response_model=LearnedRulesResponse)
def list_learned_rules(user_id: str = Depends(require_user)):
    items = [
        LearnedRuleResponse(
            keyword=rule.keyword,
            category_id=rule.category_id,
            category_name=rule.category_name,
        )
        for rule in category_service.list_learned_rules(user_id)
    ]
    return LearnedRulesResponse(
        generated_at=datetime.now().isoformat(),
        total=len(items),
        items=items,
    )


@ledger_router.get("/classify-preview", response_model=ClassifyPreviewResponse)
def classify_preview(
    note: str = Query(default=""),
    kind: Literal["expense", "income"] = Query(default="expense"),
    user_id: str = Depends(require_user),
):
    result = category_service.classify_preview(
        user_id, note, kind=kind, now=datetime.now()
    )
    is_fallback = result.reason in category_service.FALLBACK_REASONS
    return ClassifyPreviewResponse(
        matched=not is_fallback,
        category_id=result.category_id,
        category_name=result.category_name,
        confidence=result.confidence,
        reason=result.reason,
        is_fallback=is_fallback,
    )
