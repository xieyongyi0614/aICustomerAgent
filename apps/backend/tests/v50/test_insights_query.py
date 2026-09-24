"""API-006 产品洞察读面测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.db import EvidenceLinkRow, InsightRow, Memory
from app.services.insights import query as insights_query
from app.services.insights.query import headline_of, list_insights

pytestmark = pytest.mark.unit


def test_headline_truncates_first_sentence():
    assert headline_of("消费集中在餐饮。夜间偏高。") == "消费集中在餐饮"
    assert headline_of("短") == "短"


def test_list_insights_empty_is_ok(db_session_factory):
    assert list_insights("u-none", domain="home") == []
    assert list_insights("u-none", domain="health") == []


def test_list_insights_home_maps_user_scope(db_session_factory):
    now = datetime.now()
    with insights_query.SessionLocal() as session:
        session.add(
            InsightRow(
                id="ins-1",
                user_id="u1",
                statement="你最近更偏好在家做饭",
                type="preference",
                confidence=0.8,
                scope="user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    items = list_insights("u1", domain="home")
    assert len(items) == 1
    assert items[0].headline == "你最近更偏好在家做饭"
    assert items[0].domain == "home"


def test_list_insights_ledger_requires_behavior_pattern_evidence(db_session_factory):
    now = datetime.now()
    with insights_query.SessionLocal() as session:
        session.add(
            Memory(
                id="m1",
                user_id="u1",
                type="behavior_pattern",
                content="消费高度集中在餐饮",
                status="active",
                importance=0.5,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            InsightRow(
                id="ins-2",
                user_id="u1",
                statement="消费高度集中在餐饮",
                type="pattern",
                confidence=0.7,
                scope="user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            EvidenceLinkRow(
                id="ev-1",
                insight_id="ins-2",
                memory_id="m1",
                weight=1.0,
                created_at=now,
            )
        )
        session.commit()
    ledger = list_insights("u1", domain="ledger")
    assert len(ledger) == 1
    assert ledger[0].domain == "ledger"
    home = list_insights("u1", domain="home")
    assert all(i.id != "ins-2" for i in home)
