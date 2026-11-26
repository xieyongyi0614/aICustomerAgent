import json

import pytest

from app.models.memory import UserMemory
from app.repositories import (
    conversation_repository,
    evaluation_repository,
    memory_repository,
)
from app.services.evaluation.offline import evaluate_session

SESSION_ID = "conv-offline"


def _turn(user_text: str, ai_text: str):
    return (user_text, ai_text)


TURNS = [
    _turn("我今天项目上线了，超开心！", "恭喜呀，为你高兴。"),
    _turn("你最喜欢的寿司店是哪一家？", "记得你说过你喜欢三文鱼寿司。"),
]


def seed(db_session_factory):
    conversation_repository.get_or_create_conversation(SESSION_ID, "default-user")
    for user_text, ai_text in TURNS:
        conversation_repository.save_message(SESSION_ID, "human", user_text)
        conversation_repository.save_message(SESSION_ID, "ai", ai_text)
    memory_repository.create_memory(
        user_id="default-user",
        character_id="asuna",
        content="用户最喜欢吃三文鱼寿司",
        memory_type="user_preference",
        importance=0.85,
        confidence=0.9,
        source="user_stated",
    )


def test_offline_evaluator_builds_reports_and_persists_run(db_session_factory):
    seed(db_session_factory)

    import asyncio

    result = asyncio.run(evaluate_session(SESSION_ID))
    assert result["turns_evaluated"] == 2
    assert result["context_fidelity"] == "reconstructed"
    assert result["run_id"]
    assert set(result["verdict_distribution"]) <= {"pass", "warn", "fail"}
    assert isinstance(result["issue_histogram"], dict)
    assert "proactive_stats" in result

    run_row = evaluation_repository.get_by_subject("offline_batch", result["run_id"])
    assert run_row is not None
    assert run_row.subject == "offline_batch"
    assert run_row.overall_score is None
    assert run_row.meta.context_fidelity == "reconstructed"
    assert json.dumps(run_row.context_digest, ensure_ascii=False)


def test_offline_evaluator_skips_proactive_messages(db_session_factory):
    conversation_repository.get_or_create_conversation(SESSION_ID + "-p", "default-user")
    conversation_repository.save_message(SESSION_ID + "-p", "human", "在吗？")
    conversation_repository.save_message(SESSION_ID + "-p", "ai", "在的呀。")
    conversation_repository.save_message(SESSION_ID + "-p", "ai", "主动关心：最近还好吗？", is_proactive=True)

    import asyncio

    result = asyncio.run(evaluate_session(SESSION_ID + "-p"))
    assert result["turns_evaluated"] == 1


def test_offline_evaluator_missing_conversation(db_session_factory):
    import asyncio

    result = asyncio.run(evaluate_session("conv-not-exist"))
    assert result == {
        "error": "conversation_not_found",
        "session_id": "conv-not-exist",
    }
