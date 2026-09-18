"""Relationship Patterns 只读消费（REL-003）。

关系模式 ≡ active 且 kind='pattern' 且源 Insight scope='relationship' 的
development_state 行——消费侧 join insights 过滤，Development 域表结构与
编译器零改动。Relationship 只读 Development（domain-boundaries §3 合法方向）。
读取失败 fail-safe 空列表。
"""

import logging

from app.core.db import InsightRow, SessionLocal
from app.core.settings import get_settings
from app.models.development import RelationshipPattern
from app.services.development.aggregate import list_active_modulations

logger = logging.getLogger(__name__)


def read_relationship_patterns(
    user_id: str, character_id: str = "asuna"
) -> tuple[list[RelationshipPattern], dict]:
    """返回 (入选模式[strength 降序、封顶 max_items], 落选原因 payload)。"""
    settings = get_settings()
    try:
        rows = [
            row
            for row in list_active_modulations(user_id, character_id)
            if row.kind == "pattern"
        ]
        insights = _insights_by_ids(row.source_insight_id for row in rows)
        reasons: dict[str, str] = {}
        candidates: list[RelationshipPattern] = []
        for row in rows:
            insight = insights.get(row.source_insight_id)
            if insight is None:
                reasons[row.key] = "insight_missing"
                continue
            if insight.scope != "relationship":
                reasons[row.key] = "scope_excluded"
                continue
            if row.strength < settings.v2_relationship_pattern_min_strength:
                reasons[row.key] = "below_threshold"
                continue
            candidates.append(
                RelationshipPattern(
                    key=row.key,
                    value=row.value or {},
                    strength=row.strength,
                    statement=insight.statement,
                    source_insight_id=row.source_insight_id,
                )
            )
        candidates.sort(key=lambda item: item.strength, reverse=True)
        selected = candidates[: settings.v2_relationship_pattern_max_items]
        for item in candidates[settings.v2_relationship_pattern_max_items :]:
            reasons[item.key] = "over_limit"
        payload = {
            "selected": [
                {
                    "key": item.key,
                    "strength": item.strength,
                    "source_insight_id": item.source_insight_id,
                }
                for item in selected
            ],
            "reasons": reasons,
        }
        return selected, payload
    except Exception:
        logger.exception("关系模式读取失败，本轮回退无注入")
        return [], {"reasons": {}, "selected": []}


def _insights_by_ids(insight_ids) -> dict:
    ids = [insight_id for insight_id in insight_ids if insight_id]
    if not ids:
        return {}
    with SessionLocal() as session:
        rows = session.query(InsightRow).filter(InsightRow.id.in_(ids)).all()
    return {row.id: row for row in rows}
