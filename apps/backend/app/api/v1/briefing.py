"""API-008 简报端点：请求校验、响应映射与偏好落库；内容合成在 `services/briefing/compose`。

响应契约字段（APP-018 §4.4）：`{type, greeting, title, orb_note, cards[], cta, generated_at}`。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.api.v1.auth import require_user
from app.core.settings import get_settings
from app.repositories import briefing_preference_repository
from app.services.briefing import weather
from app.services.briefing import compose

briefing_router = APIRouter(prefix="/briefing", tags=["briefing"])

_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

_LAT_RANGE = (-90.0, 90.0)

_LON_RANGE = (-180.0, 180.0)


class BriefCard(BaseModel):
    title: str
    body: str
    note: str | None = None


class BriefingContent(BaseModel):
    type: Literal["morning", "evening"]
    greeting: str
    title: str
    orb_note: str
    cards: list[BriefCard]
    cta: str
    generated_at: str


class BriefPrefs(BaseModel):
    morning_at: str | None = None
    evening_at: str | None = None
    city: str | None = None

    @field_validator("morning_at", "evening_at")
    @classmethod
    def _check_hhmm(cls, value: str | None) -> str | None:
        if value is None or _HHMM.fullmatch(value):
            return value
        raise ValueError("时刻格式须为 HH:MM")


def _default_prefs() -> BriefPrefs:
    settings = get_settings()
    return BriefPrefs(
        morning_at=getattr(settings, "briefing_morning_time", "") or None,
        evening_at=getattr(settings, "briefing_evening_time", "") or None,
    )


@briefing_router.get("", response_model=BriefingContent)
async def get_briefing(
    type: Literal["morning", "evening"] = Query(default="morning"),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    user_id: str = Depends(require_user),
):
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=422, detail="lat 与 lon 必须成对提供")
    if lat is not None and not _LAT_RANGE[0] <= lat <= _LAT_RANGE[1]:
        raise HTTPException(status_code=422, detail="lat 超出合法范围")
    if lon is not None and not _LON_RANGE[0] <= lon <= _LON_RANGE[1]:
        raise HTTPException(status_code=422, detail="lon 超出合法范围")
    draft = await compose.compose_brief(type, user_id, latitude=lat, longitude=lon)
    return BriefingContent(
        type=draft.type,
        greeting=draft.greeting,
        title=draft.title,
        orb_note=draft.orb_note,
        cards=[
            BriefCard(title=card.title, body=card.body, note=card.note)
            for card in draft.cards
        ],
        cta=draft.cta,
        generated_at=draft.generated_at or datetime.now().isoformat(timespec="seconds"),
    )


@briefing_router.get("/preferences", response_model=BriefPrefs)
async def get_prefs(user_id: str = Depends(require_user)):
    row = await asyncio.to_thread(briefing_preference_repository.get, user_id)
    if row is None:
        return _default_prefs()
    return BriefPrefs(
        morning_at=row.morning_at,
        evening_at=row.evening_at,
        city=row.city,
    )


@briefing_router.put("/preferences", response_model=BriefPrefs)
async def put_prefs(body: BriefPrefs, user_id: str = Depends(require_user)):
    """整体替换语义：`city` 为空即清除已存城市与坐标；非空则先地理编码再落库。"""
    city = body.city.strip() if body.city else None
    latitude = longitude = None
    if city:
        location = await weather.geocode_city(city)
        if location is None:
            raise HTTPException(status_code=422, detail="城市无法识别")
        latitude, longitude = location.latitude, location.longitude
    row = await asyncio.to_thread(
        briefing_preference_repository.upsert,
        user_id,
        morning_at=body.morning_at,
        evening_at=body.evening_at,
        city=city,
        latitude=latitude,
        longitude=longitude,
    )
    return BriefPrefs(
        morning_at=row.morning_at,
        evening_at=row.evening_at,
        city=row.city,
    )
