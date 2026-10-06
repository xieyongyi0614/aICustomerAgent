import asyncio
from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.models.autonomy import ProactiveAction
from app.models.evaluation_judge import ProactiveJudgeResult
from app.repositories import evaluation_repository, proactive_repository
from app.services.evaluation.engine import schedule_proactive_evaluation

ACTION_ID = "act-eval-1"

JUDGE_OK = {
    "autonomy": {"score": 0.9, "codes": [], "evidence_quote": "", "confidence": 0.7},
    "persona": {"in_character": True, "score": 0.9, "codes": [], "evidence_quote": "", "confidence": 0.8},
}


def make_judge_llm(fake_llm):
    return fake_llm(response="", structured_responses={"ProactiveJudgeResult": JUDGE_OK})


def make_action(delivered_at: datetime | None = None) -> ProactiveAction:
    now = timeutil.now()
    return ProactiveAction(
        id=ACTION_ID,
        user_id="default-user",
        session_id="conv-pro-eval",
        trigger_type="conversation_inactivity",
        dedupe_key=f"inactivity:default-user:{ACTION_ID}",
        intention="check_in",
        reason="闲置关怀",
        payload_text="最近还好吗？*轻轻敲了敲你的门*",
        status="delivered",
        created_at=now,
        updated_at=now,
        delivered_at=delivered_at or now,
    )


async def wait_report(timeout: float = 2.0):
    deadline = timeutil.now() + timedelta(seconds=timeout)
    while timeutil.now() < deadline:
        report = evaluation_repository.get_by_subject("proactive_action", ACTION_ID)
        if report is not None:
            return report
        await asyncio.sleep(0.02)
    return None


@pytest.fixture
def enable_evaluation(monkeypatch):
    monkeypatch.setenv("EVALUATION_ENABLED", "true")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_proactive_evaluation_saves_report(db_session_factory, fake_llm, enable_evaluation):
    action = make_action()
    proactive_repository.enqueue(
        action.model_copy(update={"status": "candidate", "payload_text": None})
    )
    proactive_repository.transition(ACTION_ID, "approved")
    delivered = proactive_repository.transition(
        ACTION_ID,
        "delivered",
        delivered_at=action.delivered_at,
        payload_text=action.payload_text,
    )
    schedule_proactive_evaluation(delivered, make_judge_llm(fake_llm))
    report = await wait_report()
    assert report is not None
    assert report.subject == "proactive_action"
    assert report.verdict in ("pass", "warn", "fail")
    assert report.overall_score is not None
    dimensions = set(report.scores.keys())
    assert "autonomy" in dimensions or "persona" in dimensions


async def test_proactive_evaluation_quiet_hours_issue(
    db_session_factory, fake_llm, enable_evaluation
):
    late_evening = timeutil.now().replace(hour=23, minute=30, second=0)
    action = make_action(delivered_at=late_evening)
    proactive_repository.enqueue(
        action.model_copy(update={"status": "candidate", "payload_text": None})
    )
    proactive_repository.transition(ACTION_ID, "approved")
    delivered = proactive_repository.transition(
        ACTION_ID,
        "delivered",
        delivered_at=late_evening,
        payload_text=action.payload_text,
    )
    schedule_proactive_evaluation(delivered, make_judge_llm(fake_llm))
    report = await wait_report()
    assert report is not None
    assert "autonomy_timing_violation" in [
        issue.code for issue in report.issues
    ]


async def test_evaluation_failure_does_not_break_send_path(
    db_session_factory, fake_llm, enable_evaluation, monkeypatch
):
    from app.services.evaluation import engine as evaluation_engine

    def boom(*args, **kwargs):
        raise RuntimeError("merge failed")

    monkeypatch.setattr(evaluation_engine, "finalize_report", boom)
    action = make_action()
    proactive_repository.enqueue(
        action.model_copy(update={"status": "candidate", "payload_text": None})
    )
    proactive_repository.transition(ACTION_ID, "approved")
    delivered = proactive_repository.transition(
        ACTION_ID,
        "delivered",
        delivered_at=action.delivered_at,
        payload_text=action.payload_text,
    )
    schedule_proactive_evaluation(delivered, make_judge_llm(fake_llm))
    await asyncio.sleep(0.05)
    assert delivered is not None
    assert delivered.status == "delivered"


async def test_disabled_skips_evaluation(db_session_factory, fake_llm):
    action = make_action()
    proactive_repository.enqueue(
        action.model_copy(update={"status": "candidate", "payload_text": None})
    )
    proactive_repository.transition(ACTION_ID, "approved")
    delivered = proactive_repository.transition(
        ACTION_ID,
        "delivered",
        delivered_at=action.delivered_at,
        payload_text=action.payload_text,
    )
    schedule_proactive_evaluation(delivered, make_judge_llm(fake_llm))
    assert await wait_report(timeout=0.4) is None
