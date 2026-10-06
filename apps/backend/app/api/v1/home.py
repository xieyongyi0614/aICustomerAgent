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
    amount_label: str
    budget_label: str
    progress: float
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


def _day_start() -> datetime:
    return datetime.combine(
        timeutil.local_now().date(), time.min, tzinfo=timeutil.LOCAL_TZ
    )


def _day_end() -> datetime:
    return _day_start() + timedelta(days=1)


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
        today = ledger_query.summary(
            user_id,
            period=ledger_query.Period.custom(_day_start(), _day_end()),
            compare_previous=False,
        )
        spent_major = abs(getattr(today, "expense", 0) or 0) / 100
        budget = 200.0
        spend = SpendBlock(
            amount_label=f"¥{spent_major:.0f}",
            budget_label=f"/ 今日预算 ¥{budget:.0f}",
            progress=min(1.0, spent_major / budget) if budget else 0.0,
            conclusion="节奏健康 —— 亚丝娜" if spent_major > 0 else "今天还没有记账 —— 亚丝娜",
            week_bars=[
                value / 100
                for value in ledger_query.daily_expense_series(user_id, days=7)
            ],
        )
    except Exception:
        spend = SpendBlock(
            amount_label="¥0",
            budget_label="/ 今日预算 ¥200",
            progress=0.0,
            conclusion="今天还没有记账 —— 亚丝娜",
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
