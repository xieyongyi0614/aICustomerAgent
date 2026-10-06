import asyncio
import time

import pytest

from app.application.post_process import PostProcessContext, run_evaluation
from app.models.behavior_strategy import (
    ActionBudget,
    BehaviorDirective,
    BehaviorStrategy,
)
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.evaluation import EvaluationDimension
from app.models.relationship import RelationshipState
from app.repositories import evaluation_repository
from app.services.observability.collector import TurnTraceSession

JUDGE_OK = {
    "persona": {
        "in_character": True,
        "score": 0.7,
        "codes": ["persona_ooc"],
        "evidence_quote": "微微一笑",
        "confidence": 0.8,
    },
    "emotion": {"score": 0.9, "codes": [], "evidence_quote": "", "confidence": 0.7},
    "memory": {"score": 1.0, "codes": [], "memory_ids": ["m1"], "evidence_quote": ""},
}


async def wait_report(subject_id: str = "555", timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        report = evaluation_repository.get_by_subject("turn", subject_id)
        if report is not None:
            return report
        await asyncio.sleep(0.02)
    return None


def make_ctx(llm=None) -> PostProcessContext:
    state = ConversationState(
        session_id="conv-eval",
        user_id="default-user",
        messages=[ChatMessage(role="human", content="最近怎么样？")],
        summary=None,
        memories=[],
        current_input="最近怎么样？",
        character_state=CharacterState(),
        relationship_state=RelationshipState(),
    )
    trace = TurnTraceSession()
    trace.turn_id = "555"
    return PostProcessContext(
        session_id="conv-eval",
        user_id="default-user",
        user_input="最近怎么样？",
        ai_reply="我很好呀，谢谢关心。*微微一笑*",
        state=state,
        analysis=TurnAnalysis(),
        trace=trace,
        llm=llm,
        behavior=BehaviorDirective(
            strategy=BehaviorStrategy(
                strategy="natural_continuation", base_strategy="natural_continuation"
            ),
            budget=ActionBudget(max_action_desc=1),
        ),
    )


async def test_full_turn_evaluation_with_judge(db_session_factory, fake_llm, monkeypatch):
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        llm = fake_llm(response="", structured_responses={"TurnJudgeResult": JUDGE_OK})
        ctx = make_ctx(llm=llm)

        await run_evaluation(ctx)
        report = await wait_report()
        assert report is not None
        assert report.meta.judge_used is True
        assert report.meta.judge_sampled is True
        persona = report.scores[EvaluationDimension.PERSONA]
        assert persona.judge_score == pytest.approx(0.7)
        assert persona.rule_score == pytest.approx(1.0)
        assert persona.score == pytest.approx(0.7)
        issue_codes = [issue.code for issue in report.issues]
        assert "persona_ooc" in issue_codes
        step = [s for s in ctx.trace.steps if s.name == "evaluation"][0]
        assert step.status == "ok"
    finally:
        get_settings.cache_clear()


async def test_judge_failure_degrades_to_rules_only(db_session_factory, fake_llm, monkeypatch):
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        llm = fake_llm(
            response="", structured_errors={"TurnJudgeResult": RuntimeError("boom")}
        )
        ctx = make_ctx(llm=llm)

        await run_evaluation(ctx)
        report = await wait_report()
        assert report is not None
        assert report.meta.judge_used is False
        step = [s for s in ctx.trace.steps if s.name == "evaluation"][0]
        assert step.status == "degraded"
    finally:
        get_settings.cache_clear()


def test_sample_rate_zero_saves_rules_only_inline(
    db_session_factory, fake_llm, monkeypatch
):
    monkeypatch.setenv("EVALUATION_LLM_JUDGE_SAMPLE_RATE", "0.0")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        ctx = make_ctx()
        import asyncio

        asyncio.run(run_evaluation(ctx))
        step = [s for s in ctx.trace.steps if s.name == "evaluation"][0]
        assert step.status == "ok"
        assert step.extra.get("judge") == "skipped"
        report = evaluation_repository.get_by_subject("turn", "555")
        assert report is not None
        assert report.meta.judge_used is False
    finally:
        get_settings.cache_clear()


def test_is_complete_ignores_evaluation_step():
    trace = TurnTraceSession()
    for name in (
        "state_update",
        "emotion_update",
        "relationship_event",
        "memory_extractor",
        "scene_update",
        "goal_review",
    ):
        trace.record(name, 0.0)
    assert trace.is_complete is True
    trace.record("evaluation", 0.0, "ok")
    assert trace.is_complete is True


async def test_run_post_process_includes_evaluation_step(db_session_factory, monkeypatch):
    """全链冒烟：七个步骤都执行且评估 step 存在（各步骤失败互不影响）。"""
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        from app.application.post_process import run_post_process

        ctx = make_ctx()
        await run_post_process(ctx)
        names = [s.name for s in ctx.trace.steps]
        assert "evaluation" in names
    finally:
        get_settings.cache_clear()
