"""briefing_preferences 单表数据访问（API-008）：简报时刻偏好与定位城市。

`user_id` 主键，一行一人；`city` 与 `(latitude, longitude)` 由地理编码在写入侧
一起落库，读取侧只消费坐标。
"""

from datetime import datetime

from app.core import timeutil
from app.core.db import BriefingPreferenceRow, SessionLocal


def get(user_id: str) -> BriefingPreferenceRow | None:
    with SessionLocal() as session:
        return session.get(BriefingPreferenceRow, user_id)


def upsert(
    user_id: str,
    *,
    morning_at: str | None,
    evening_at: str | None,
    city: str | None,
    latitude: float | None,
    longitude: float | None,
) -> BriefingPreferenceRow:
    with SessionLocal() as session:
        row = session.get(BriefingPreferenceRow, user_id)
        if row is None:
            row = BriefingPreferenceRow(user_id=user_id)
            session.add(row)
        row.morning_at = morning_at
        row.evening_at = evening_at
        row.city = city
        row.latitude = latitude
        row.longitude = longitude
        row.updated_at = timeutil.now()
        session.commit()
        return row
