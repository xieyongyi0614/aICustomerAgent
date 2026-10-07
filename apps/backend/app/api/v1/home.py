"""API-004 首页聚合：单请求全区块，区块级降级，零 repositories。"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core import timeutil
from app.api.v1.auth import require_user
from app.services.conversation import history as history_service
from app.services.observability.analytics import track_event
from app.services.insights import query as insights_query
from app.services.ledger import query as ledger_query
from app.services.life import tasks as task_service

home_router = APIRouter(prefix="/home", tags=["home"])


class GreetingBlock(BaseModel):
    date_label: str
    greeting: str


class HeroBlock(BaseModel):
    headline: str
    sub: str
    mode_chip: str


class InsightBlock(BaseModel):
    title: str
    narrative: str
    action_label: str | None = None


class TaskItem(BaseModel):
    id: str
    title: str
    tag: str | None = None
    done: bool = False
    order_reason: str | None = None


class SpendBlock(BaseModel):
    """首页消费速览（A7）：**近 7 天**口径。

    按日聚合太细（一天没记账就只剩空卡），且日预算没有数据源
    （`ledger/budget.py` 的 `BudgetSpec.period` 只有 month/week）——旧实现的
    「/ 今日预算 ¥200」是硬编码，已删除；`progress` 只在有真实预算时才有值。
    """

    amount_label: str
    note_label: str
    progress: float | None = None
    conclusion: str

    # 近 7 天每日消费序列（元，旧→新；DA-25 周柱状图数据源）。
    week_bars: list[float] = []


class HomeSummary(BaseModel):
    greeting: GreetingBlock
    hero: HeroBlock
    insight: InsightBlock
    tasks: list[TaskItem]
    tasks_hint: str
    spend: SpendBlock | None = None
    proactive_todo: list[str] = []


SPEND_WINDOW_DAYS = 7


def _spend_window() -> tuple[datetime, datetime]:
    """近 7 天（含今天，本地日边界）——与 `daily_expense_series` 同口径。"""
    today = timeutil.local_now().date()
    since = datetime.combine(
        today - timedelta(days=SPEND_WINDOW_DAYS - 1), time.min, tzinfo=timeutil.LOCAL_TZ
    )
    return since, since + timedelta(days=SPEND_WINDOW_DAYS)


def _spend_conclusion(summary) -> str:
    """结论只用结构化字段说话（日均 + 环比），不编造判断。"""
    if not summary.entry_count:
        return "最近还没有记账 —— 亚丝娜"
    daily = abs(summary.expense_minor) / 100 / SPEND_WINDOW_DAYS
    compared = summary.compared_to_previous
    ratio = compared.expense_ratio if compared is not None else None
    head = f"近 7 天日均 ¥{daily:.0f}"
    if ratio is None:
        return f"{head} —— 亚丝娜"
    if ratio < 0:
        return f"{head}，比上周少 {abs(ratio) * 100:.0f}% —— 亚丝娜"
    return f"{head}，比上周多 {ratio * 100:.0f}% —— 亚丝娜"


_MODE_LABELS = {
    "professional": "Professional 模式",
    "default": "Default 模式",
    "immersive": "Immersive 模式",
}


def greeting_for(moment: datetime) -> str:
    hour = timeutil.local(moment).hour
    if hour < 5:
        return "夜深了"
    if hour < 11:
        return "早上好"
    if hour < 14:
        return "中午好"
    if hour < 18:
        return "下午好"
    return "晚上好"


def mode_chip_for(user_id: str) -> str:
    try:
        conversation = history_service.find_latest_conversation(user_id)
    except Exception:
        return ""
    return _MODE_LABELS.get(getattr(conversation, "mode", None), "")


def insight_block_for(user_id: str) -> InsightBlock:
    """只映射已产出的洞察；无洞察时叙事留空，由客户端出空态，不补默认文案。"""
    try:
        items = insights_query.list_insights(user_id, domain="home", limit=1)
    except Exception:
        items = []
    if not items:
        return InsightBlock(title="今日 AI 总结", narrative="")
    top = items[0]
    return InsightBlock(
        title=top.headline or "今日 AI 总结",
        narrative=top.narrative,
        action_label="查看完整早间简报 →",
    )


@home_router.get("/summary", response_model=HomeSummary)
def home_summary(user_id: str = Depends(require_user)):
    track_event("home_summary")
    try:
        task_rows = task_service.list_open(user_id)
    except Exception:
        task_rows = []
    tasks = [
        TaskItem(
            id=t["id"],
            title=t["title"],
            tag=t.get("tag"),
            order_reason=t.get("order_reason"),
        )
        for t in task_rows[:5]
    ]
    try:
        since, until = _spend_window()
        week = ledger_query.summary(
            user_id,
            period=ledger_query.Period.custom(since, until, label="week"),
            compare_previous=True,
        )
        spent_major = abs(week.expense_minor) / 100
        spend = SpendBlock(
            amount_label=f"¥{spent_major:.0f}",
            note_label=(
                f"近 {SPEND_WINDOW_DAYS} 天 · {week.entry_count} 笔"
                if week.entry_count
                else f"近 {SPEND_WINDOW_DAYS} 天"
            ),
            progress=None,
            conclusion=_spend_conclusion(week),
            week_bars=[
                value / 100
                for value in ledger_query.daily_expense_series(
                    user_id, days=SPEND_WINDOW_DAYS
                )
            ],
        )
    except Exception:
        spend = SpendBlock(
            amount_label="¥0",
            note_label=f"近 {SPEND_WINDOW_DAYS} 天",
            progress=None,
            conclusion="最近还没有记账 —— 亚丝娜",
        )
    return HomeSummary(
        greeting=GreetingBlock(date_label="今天", greeting=greeting_for(timeutil.now())),
        hero=HeroBlock(
            headline="今天也交给我吧",
            sub="亚丝娜已为你整理好今天的一切",
            mode_chip=mode_chip_for(user_id),
        ),
        insight=insight_block_for(user_id),
        tasks=tasks,
        tasks_hint=f"{len(tasks)} 项 · AI 已排序" if tasks else "",
        spend=spend,
    )
