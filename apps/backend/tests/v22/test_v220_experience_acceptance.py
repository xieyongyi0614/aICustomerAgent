"""V2.2.0 Character Experience System 验收测试（场景矩阵 + 链路集成）。

覆盖：情绪变化/衰减/影响回复、人格一致性与风格稳定、关系阶段差异、
习惯触发、风格段控制，以及 Chat → Experience → 回复 的管线集成。
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.character.asuna.emotion_expression import EMOTION_TONES
from app.character.asuna.personality_profile import PERSONA_PROFILE
from app.core import llm_factory
from app.main import app
from app.models.agent_state import PersonalityAxisState
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import EmotionEvent, TurnAnalysis, UserEmotion
from app.models.relationship import RelationshipState
from app.models.style_contract import StyleContract
from app.prompts.builder import PromptBuilder
from app.services import state_engine
from app.services.experience.emotion_expression import (
    build_emotion_expression,
    describe_transition,
)
from app.services.experience.style_assembler import assemble_style_contract


def _state(
    message: str = "最近工作很累",
    mood: str = "worried",
    intensity: float = 0.55,
    relationship: RelationshipState | None = None,
) -> ConversationState:
    return ConversationState(
        session_id="s-accept",
        user_id="u-accept",
        messages=[],
        summary=None,
        memories=[],
        current_input=message,
        character_state=CharacterState(mood=mood, intensity=intensity),
        relationship_state=relationship or RelationshipState(),
    )


def _analysis(emotion: str = "tired", event: str = "seek_help") -> TurnAnalysis:
    return TurnAnalysis(user_emotion=UserEmotion(emotion=emotion, event=event))


def _section(state, analysis) -> str:
    return PromptBuilder.build_style_section(assemble_style_contract(state, analysis))


def test_emotion_change_produces_transition_and_expression_shift():
    now = datetime(2026, 9, 14, 10, 0, 0)
    before = CharacterState(mood="calm", intensity=0.3)
    event = EmotionEvent(
        type="worrying_news", magnitude="normal", confidence=0.9, cause="工作很累"
    )
    after = state_engine.update_emotion(before, event, now)
    assert after.mood == "worried"
    assert after.intensity > before.intensity
    assert describe_transition(before, after).startswith("calm → worried")
    expression_before = build_emotion_expression(before)
    expression_after = build_emotion_expression(after)
    assert expression_before.expression_intensity == "subtle"
    assert expression_after.expression_intensity == "natural"
    assert expression_after.tone_directive == EMOTION_TONES.tones["worried"].tone_directive
    assert expression_after.tone_directive != expression_before.tone_directive


def test_emotion_decay_downgrades_expression_tier_stepwise():
    t0 = datetime(2026, 9, 14, 10, 0, 0)
    state = CharacterState(mood="worried", intensity=0.9, last_event_at=t0)
    tiers = []
    final = state
    for hour in (1, 2, 3, 4, 5):
        final = state_engine.apply_emotion_decay(
            state, t0 + timedelta(hours=hour)
        )
        tiers.append(build_emotion_expression(final).expression_intensity)
    assert tiers == ["rich", "natural", "subtle", "subtle", "subtle"]
    assert final.mood == "calm"
    assert final.intensity == 0.3


def test_emotion_tone_directive_shapes_style_section():
    worried_section = _section(_state(mood="worried"), _analysis())
    happy_section = _section(
        _state(mood="happy"), _analysis(emotion="happy", event="daily")
    )
    assert EMOTION_TONES.tones["worried"].tone_directive in worried_section
    assert EMOTION_TONES.tones["happy"].tone_directive in happy_section
    assert (
        EMOTION_TONES.tones["worried"].tone_directive
        != EMOTION_TONES.tones["happy"].tone_directive
    )


def test_personality_hard_constraints_invariant_across_scenarios():
    scenarios = [
        (
            _state(mood="angry", intensity=0.6, relationship=RelationshipState(conflict_status="conflict")),
            _analysis(emotion="angry", event="conflict"),
        ),
        (
            _state(mood="happy", intensity=0.7, relationship=RelationshipState(stage="partner")),
            _analysis(emotion="happy", event="daily"),
        ),
        (_state(mood="sad", intensity=0.4), _analysis(emotion="sad", event="setback")),
    ]
    for state, analysis in scenarios:
        contract = assemble_style_contract(state, analysis)
        assert contract.forbidden == list(PERSONA_PROFILE.forbidden_behaviors)
        assert contract.principles == list(PERSONA_PROFILE.principles)
        assert contract.forbidden
        assert contract.principles


def test_style_assembly_is_deterministic_and_pure_over_state():
    state = _state()
    analysis = _analysis()
    first = assemble_style_contract(state, analysis)
    second = assemble_style_contract(state, analysis)
    assert first.model_dump() == second.model_dump()
    assert state.character_state == CharacterState(mood="worried", intensity=0.55)
    assert state.relationship_state == RelationshipState()


def test_evolution_axis_drift_surfaces_personality_line():
    axes = [
        PersonalityAxisState(
            axis="curiosity", baseline=0.6, current=0.85, bound_min=0.4, bound_max=0.8
        )
    ]
    contract = assemble_style_contract(_state(), _analysis(), axes)
    lines = contract.personality_modulation.prompt_lines()
    assert lines and "好奇，会追问" in lines[0]
    baseline_contract = assemble_style_contract(_state(), _analysis())
    assert baseline_contract.personality_modulation.prompt_lines() == []


def test_stage_differences_visible_in_style_section():
    sections = {}
    for stage in ("stranger", "friend", "close_friend", "partner"):
        state = _state(
            message="在吗", relationship=RelationshipState(stage=stage)
        )
        sections[stage] = _section(state, _analysis(emotion="neutral", event="daily"))
    assert "称呼：敬称" in sections["stranger"]
    assert "语气：客气体贴" in sections["stranger"]
    assert "主动程度：被动，只接话" in sections["stranger"]
    assert "称呼" not in sections["friend"]
    assert "称呼：昵称" in sections["close_friend"]
    assert "语气：亲昵" in sections["close_friend"]
    assert "称呼：专属称呼" in sections["partner"]
    assert "语气：带撒娇" in sections["partner"]
    assert "主动程度：主动惦记" in sections["partner"]
    assert sections["stranger"] != sections["partner"]


def test_conflict_overrides_lower_warmth_in_style_section():
    calm_section = _section(
        _state(message="在吗"), _analysis(emotion="neutral", event="daily")
    )
    conflict_section = _section(
        _state(message="在吗", relationship=RelationshipState(conflict_status="conflict")),
        _analysis(emotion="neutral", event="daily"),
    )
    assert "语气：客气体贴" in conflict_section
    assert "主动程度：被动，只接话" in conflict_section
    assert "语气：客气体贴" not in calm_section


def test_habit_instructions_rendered_and_capped():
    state = _state(message="我好难过，压力好大，好累，怎么办？")
    contract = assemble_style_contract(state, _analysis(emotion="sad"))
    assert 1 <= len(contract.habits) <= 2
    section = PromptBuilder.build_style_section(contract)
    for habit in contract.habits:
        assert f"习惯：{habit.instruction}" in section
    assert "习惯：一次最多问一个问题" not in section


def test_style_section_within_budget_and_brace_free():
    section = _section(_state(), _analysis())
    assert section
    assert len(section) <= 300
    assert "{" not in section and "}" not in section
    assert "禁止：不为了讨好用户而无条件赞同" in section
    assert "原则：面对困难时冷静果断" in section


@pytest.fixture
def client_fixture():
    with TestClient(app) as test_client:
        yield test_client


def _structured_responses():
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "ok",
        },
    }


def test_pipeline_flags_off_keeps_v210_prompt(
    client_fixture, db_session_factory, fake_llm
):
    llm = fake_llm(response=["好"], structured_responses=_structured_responses())
    llm_factory.set_llm(llm)
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "最近工作很累"})
    assert resp.status_code == 200
    prompt_texts = [str(m) for m in llm.seen_messages]
    assert prompt_texts
    assert all("【本轮表达风格】" not in text for text in prompt_texts)


def test_pipeline_flags_on_injects_style_contract(
    client_fixture, db_session_factory, fake_llm, override_settings, monkeypatch
):
    override_settings(
        experience_enabled=True,
        style_contract_enabled=True,
        emotion_transition_enabled=True,
        relationship_addressing_enabled=True,
        habit_runtime_enabled=True,
    )
    captured = {}
    real_build = PromptBuilder.build

    def _capturing_build(*args, **kwargs):
        captured["style_ctx"] = (
            kwargs.get("style_ctx") if "style_ctx" in kwargs else args[8]
        )
        return real_build(*args, **kwargs)

    monkeypatch.setattr(PromptBuilder, "build", staticmethod(_capturing_build))
    llm = fake_llm(response=["好"], structured_responses=_structured_responses())
    llm_factory.set_llm(llm)
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "最近工作很累"})
    assert resp.status_code == 200
    style_ctx = captured.get("style_ctx")
    assert isinstance(style_ctx, StyleContract)
    assert style_ctx.forbidden == list(PERSONA_PROFILE.forbidden_behaviors)
    assert "habit_care_action_first" in [habit.rule_id for habit in style_ctx.habits]
    assert style_ctx.style_hint
    prompt_texts = [str(m) for m in llm.seen_messages]
    assert any("【本轮表达风格】" in text for text in prompt_texts)
    assert any("禁止：不为了讨好用户而无条件赞同" in text for text in prompt_texts)
    assert any("习惯：" in text for text in prompt_texts)
