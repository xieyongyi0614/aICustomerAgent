"""V7.8 debug 决策查询端点。"""

import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.application import autonomy_engine
from app.application.post_process import reset_user_write_locks
from app.character.asuna import PERSISTENT_GOALS
from app.core import llm_factory
from app.core.db import Message
from app.main import app
from app.repositories import conversation_repository, decision_repository, goal_repository
from app.services.conversation import service as conversation_service
from tests.conftest import wait_until

NOW = datetime(2026, 8, 30, 14, 0)
USER = "default-user"


def _setup(db_session_factory, session_id="s1"):
    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧，我等你回来")
    with conversation_repository.SessionLocal() as session:
        rows = session.query(Message).all()
        for row in rows:
            row.created_at = NOW - timedelta(minutes=40)
        session.commit()
    return session_id


def test_debug_decisions_endpoint(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered_ids = asyncio.run(
            autonomy_engine.tick(user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=35))
        )
        assert len(delivered_ids) == 1
        assert wait_until(
            lambda: any(
                record.decision == "act"
                for record in decision_repository.search(user_id=USER)
            )
        )

        with TestClient(app) as client:
            listing = client.get("/api/v1/debug/decisions", params={"user_id": USER})
            assert listing.status_code == 200
            rows = listing.json()
            assert any(row["decision"] == "act" for row in rows)
            act_row = next(row for row in rows if row["decision"] == "act")
            assert act_row["kind"] == "proactive_autonomy"
            assert act_row["trigger"] == "conversation_inactivity"

            by_action = client.get(
                "/api/v1/debug/decisions", params={"action_id": act_row["action_id"]}
            )
            assert len(by_action.json()) == 1

            empty = client.get("/api/v1/debug/decisions", params={"user_id": "nobody"})
            assert empty.status_code == 200
            assert empty.json() == []
    finally:
        llm_factory.reset_llm()
        reset_user_write_locks()
