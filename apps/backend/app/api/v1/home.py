"""API-004 首页聚合：单请求全区块，区块级降级，零 repositories。"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.settings import get_settings
from app.services.ledger import query as ledger_query
from app.services.tasks import task_service

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


class MetricCell(BaseModel):
    label: str
    value: str
    unit: str | None = None
    note: str | None = None


class HealthGrid(BaseModel):
    authorized: bool
    cells: list[MetricCell] = []
    source: str | None = None
    empty_hint: str | None = None


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


class HomeSummary(BaseModel):
    greeting: GreetingBlock
    hero: HeroBlock
    insight: InsightBlock
    health: HealthGrid
    tasks: list[TaskItem]
    tasks_hint: str
    spend: SpendBlock | None = None
    proactive_todo: list[str] = []


def _day_start() -> datetime:
    return datetime.combine(datetime.now().date(), time.min)


def _day_end() -> datetime:
    return _day_start() + timedelta(days=1)


@home_router.get("/summary", response_model=HomeSummary)
def home_summary():
    user_id = get_settings().default_user
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
        )
    except Exception:
        spend = SpendBlock(
            amount_label="¥0",
            budget_label="/ 今日预算 ¥200",
            progress=0.0,
            conclusion="今天还没有记账 —— 亚丝娜",
        )
    return HomeSummary(
        greeting=GreetingBlock(date_label="今天", greeting="早上好"),
        hero=HeroBlock(
            headline="今天也交给我吧",
            sub="亚丝娜已为你整理好今天的一切",
            mode_chip="Default 模式 · 长期记忆运行中",
        ),
        insight=InsightBlock(
            title="今日 AI 总结",
            narrative="昨晚睡得不错，上午适合处理需要专注的事。",
            action_label="查看完整早间简报 →",
        ),
        health=HealthGrid(
            authorized=False,
            empty_hint="连接手环后，这里会显示睡眠、心率和步数",
        ),
        tasks=tasks,
        tasks_hint=f"{len(tasks)} 项 · AI 已排序",
        spend=spend,
    )
