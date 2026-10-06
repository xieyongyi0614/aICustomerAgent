"""V7.8 主动 correlation bundle：决策 + trace + 评估 + LLM 调用齐备。"""

import asyncio
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import timeutil
from app.application import autonomy_engine
from app.application.post_process import reset_user_write_locks
from app.character.asuna import PERSISTENT_GOALS
from app.core import llm_factory
from app.core.db import Message
from app.main import app
from app.repositories import conversation_repository, goal_repository, trace_repository
from app.services.conversation import service as conversation_service
from tests.conftest import wait_until

NOW = timeutil.ensure_aware(datetime(2026, 8, 30, 14, 0))
USER = "default-user"


def _setup(db_session_factory, session_id="s1"):
    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧，我等你回来")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=40)
        session.commit()
    return session_id


def test_debug_proactive_correlation_bundle(
    db_session_factory, fake_llm, override_settings, monkeypatch
):
    from app.repositories import proactive_repository

    class _SimClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(minutes=40)

    monkeypatch.setattr(proactive_repository, "datetime", _SimClock)
    override_settings(
        observability_prompt_capture_mode="always",
        evaluation_llm_judge_sample_rate=0,
    )
    _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered_ids = asyncio.run(
            autonomy_engine.tick(user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=35))
        )
        assert len(delivered_ids) == 1
        message_id = delivered_ids[0]
        assert wait_until(lambda: trace_repository.get_by_turn(message_id) is not None)

        with TestClient(app) as client:
            pending = client.get("/api/v1/proactive/pending").json()["actions"]
            assert len(pending) == 1
            action_id = pending[0]["id"]

            bundle = client.get(f"/api/v1/debug/proactive/{action_id}/correlation")
            assert bundle.status_code == 200
            body = bundle.json()
            assert body["action_id"] == action_id
            assert body["turn_id"] == message_id
            assert body["trace"] is not None
            assert "proactive_deliver" in {s["name"] for s in body["trace"]["steps"]}
            assert body["evaluation"] is not None
            assert body["evaluation"]["subject"] == "proactive_action"
            assert any(d["decision"] == "act" for d in body["decisions"])

            missing = client.get("/api/v1/debug/proactive/no-such/correlation")
            assert missing.status_code == 404
    finally:
        llm_factory.reset_llm()
        reset_user_write_locks()
