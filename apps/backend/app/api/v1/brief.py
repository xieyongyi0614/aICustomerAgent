"""API-008 简报预生成与偏好（参数类时刻，非开关）。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.v1.auth import require_user
from app.core.settings import get_settings
from app.services.tasks import task_service

brief_router = APIRouter(prefix="/brief", tags=["brief"])


class BriefCard(BaseModel):
    title: str
    body: str
    note: str | None = None


class BriefContent(BaseModel):
    form: Literal["morning", "evening"]
    eyebrow: str
    headline: str
    orb_line: str
    cards: list[BriefCard]
    footer: str


class BriefPrefs(BaseModel):
    morning_at: str | None = None
    evening_at: str | None = None


_PREFS: dict[str, BriefPrefs] = {}


def _default_prefs() -> BriefPrefs:
    settings = get_settings()
    return BriefPrefs(
        morning_at=getattr(settings, "briefing_morning_time", "") or None,
        evening_at=getattr(settings, "briefing_evening_time", "") or None,
    )


@brief_router.get("/{form}", response_model=BriefContent)
def get_brief(
    form: Literal["morning", "evening"],
    user_id: str = Depends(require_user),
):
    try:
        tasks = task_service.list_open(user_id)
    except Exception:
        tasks = []
    if form == "morning":
        return BriefContent(
            form="morning",
            eyebrow="早间简报",
            headline="早上好，今天交给我吧",
            orb_line="天气转凉，记得加件外套",
            cards=[
                BriefCard(title="天气", body="18° 多云", note="傍晚有风"),
                BriefCard(title="日程", body="15:00 产品方案对齐", note="14:30 我会提醒你"),
                BriefCard(
                    title="任务",
                    body=f"{len(tasks)} 项 · 已按你的节奏排好",
                    note="先回导师邮件，压力小一点" if tasks else "今天还很轻松",
                ),
                BriefCard(title="生活节奏", body="昨晚睡了 7h12m", note="上午适合专注"),
            ],
            footer="开始今天",
        )
    return BriefContent(
        form="evening",
        eyebrow="晚间总结",
        headline="今天辛苦了",
        orb_line="明天的节奏我已经帮你排好了",
        cards=[
            BriefCard(title="今天完成", body="节奏挺稳的", note="继续保持"),
            BriefCard(
                title="未完成",
                body=f"{len(tasks)} 项已重新排期",
                note="不用赶，明天接着来",
            ),
            BriefCard(title="生活节奏", body="今天走了 6,234 步", note="比昨天多一点"),
            BriefCard(title="记住的你", body="咖啡不加糖 · 十一想去海边", note="都记下了"),
        ],
        footer="安顿明天",
    )


@brief_router.get("/prefs/me", response_model=BriefPrefs)
def get_prefs(user_id: str = Depends(require_user)):
    return _PREFS.get(user_id, _default_prefs())


@brief_router.put("/prefs/me", response_model=BriefPrefs)
def put_prefs(body: BriefPrefs, user_id: str = Depends(require_user)):
    _PREFS[user_id] = body
    return body
