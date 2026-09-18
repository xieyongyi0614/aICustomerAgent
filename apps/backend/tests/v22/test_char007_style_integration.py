"""CHAR-007：PromptBuilder 集成、Flag 灰度与调用方接线测试。"""

from types import SimpleNamespace

import pytest

from app.chains import answer_chain
from app.core import llm_factory
from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations
from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis, UserEmotion
from app.models.relationship import RelationshipState
from app.models.style_contract import (
    Addressing,
    EmotionExpression,
    StyleContract,
    TriggeredHabit,
)
from app.prompts.builder import PromptBuilder
from app.services.experience import style_context
from app.services.experience.style_context import build_style_context
from app.services.trace_collector import TurnTraceSession


FLAG_ENVS = {
    "EXPERIENCE_ENABLED": "true",
    "STYLE_CONTRACT_ENABLED": "true",
    "EMOTION_TRANSITION_ENABLED": "true",
    "RELATIONSHIP_ADDRESSING_ENABLED": "true",
    "HABIT_RUNTIME_ENABLED": "true",
}


def _set_flags(monkeypatch, **overrides):
    envs = dict(FLAG_ENVS)
    for key, value in overrides.items():
        envs[key] = value if value.startswith(("true", "false")) else "false"
    for key, value in envs.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings.cache_clear()


def _state() -> ConversationState:
    return ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="最近工作很累",
        character_state=CharacterState(mood="worried", intensity=0.55),
        relationship_state=RelationshipState(),
    )


def _analysis() -> TurnAnalysis:
    return TurnAnalysis(user_emotion=UserEmotion(emotion="tired", event="seek_help"))


def _contract() -> StyleContract:
    return StyleContract(
        addressing=Addressing(term="affectionate", tone="warm"),
        emotion_constraint=EmotionExpression(tone_directive="语气放柔"),
        habits=[
            TriggeredHabit(
                rule_id="habit_comfort_companion_first",
                priority=1,
                instruction="安慰人先陪着，不第一时间给建议",
            )
        ],
        forbidden=["不为了讨好用户而无条件赞同"],
        principles=["面对困难时冷静果断"],
    )


def _rendered(prompt) -> str:
    texts = []
    for message in prompt.messages:
        template = getattr(message, "prompt", None)
        texts.append(template.format() if template is not None else message.content)
    return "\n".join(str(text) for text in texts)


def test_build_style_context_returns_none_when_flags_off():
    assert build_style_context(_state(), _analysis()) is None


def test_build_style_context_requires_style_contract_gate(monkeypatch):
    _set_flags(monkeypatch, STYLE_CONTRACT_ENABLED="false")
    try:
        assert build_style_context(_state(), _analysis()) is None
    finally:
        get_settings.cache_clear()


def test_build_style_context_with_only_total_and_style_gates(monkeypatch):
    _set_flags(
        monkeypatch,
        EMOTION_TRANSITION_ENABLED="false",
        RELATIONSHIP_ADDRESSING_ENABLED="false",
        HABIT_RUNTIME_ENABLED="false",
    )
    try:
        contract = build_style_context(_state(), _analysis())
        assert contract is not None
        assert contract.addressing == Addressing()
        assert contract.emotion_constraint == EmotionExpression()
        assert contract.habits == []
        assert contract.forbidden
        assert contract.principles
        assert contract.style_hint
    finally:
        get_settings.cache_clear()


def test_build_style_context_all_gates_on(monkeypatch):
    _set_flags(monkeypatch)
    try:
        contract = build_style_context(_state(), _analysis())
        assert contract is not None
        assert contract.addressing.term == "name"
        assert contract.emotion_constraint.tone_directive != ""
        assert contract.habits
        assert contract.style_hint
    finally:
        get_settings.cache_clear()


def test_build_style_context_relationship_gate_controls_boost(monkeypatch):
    partner_state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="在吗",
        character_state=CharacterState(mood="calm", intensity=0.45),
        relationship_state=RelationshipState(stage="partner"),
    )
    _set_flags(monkeypatch, RELATIONSHIP_ADDRESSING_ENABLED="false")
    try:
        without_boost = build_style_context(partner_state, _analysis())
        assert without_boost.emotion_constraint.expression_intensity == "natural"
    finally:
        get_settings.cache_clear()
    _set_flags(monkeypatch)
    try:
        with_boost = build_style_context(partner_state, _analysis())
        assert with_boost.emotion_constraint.expression_intensity == "rich"
        assert with_boost.addressing.term == "intimate"
    finally:
        get_settings.cache_clear()


def test_build_style_context_emotion_off_keeps_relationship_expressiveness(monkeypatch):
    partner_state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="在吗",
        character_state=CharacterState(mood="calm", intensity=0.2),
        relationship_state=RelationshipState(stage="partner"),
    )
    _set_flags(monkeypatch, EMOTION_TRANSITION_ENABLED="false")
    try:
        contract = build_style_context(partner_state, _analysis())
        assert contract.addressing.emotion_expressiveness == "open"
        assert contract.emotion_constraint == EmotionExpression()
    finally:
        get_settings.cache_clear()


def test_build_style_context_degrades_to_none_on_failure(monkeypatch):
    _set_flags(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(style_context, "assemble_style_contract", _boom)
    try:
        assert build_style_context(_state(), _analysis()) is None
    finally:
        get_settings.cache_clear()


def test_build_style_section_none_and_empty_contract():
    assert PromptBuilder.build_style_section(None) is None
    assert PromptBuilder.build_style_section(StyleContract()) is None


def test_build_style_section_compact_text():
    section = PromptBuilder.build_style_section(_contract())
    assert section.startswith("【本轮表达风格】")
    assert "称呼：昵称" in section
    assert "习惯：安慰人先陪着，不第一时间给建议" in section
    assert "禁止：不为了讨好用户而无条件赞同" in section
    assert "{" not in section and "}" not in section


def test_build_style_section_respects_char_budget():
    contract = StyleContract(
        forbidden=[f"禁止项{i}" + "x" * 40 for i in range(30)],
    )
    section = PromptBuilder.build_style_section(contract)
    assert section is not None
    assert len(section) <= 300


def test_prompt_build_without_style_ctx_is_byte_identical():
    base = PromptBuilder.build("default", _state(), _analysis())
    explicit = PromptBuilder.build("default", _state(), _analysis(), style_ctx=None)
    assert _rendered(base) == _rendered(explicit)


def test_prompt_build_injects_style_section_when_contract_given():
    without = _rendered(PromptBuilder.build("default", _state(), _analysis()))
    with_style = _rendered(
        PromptBuilder.build("default", _state(), _analysis(), style_ctx=_contract())
    )
    assert "【本轮表达风格】" not in without
    assert "【本轮表达风格】" in with_style
    assert with_style.index("【角色当前情绪】") < with_style.index("【本轮表达风格】")
    assert "称呼：昵称" in with_style
    assert "禁止：不为了讨好用户而无条件赞同" in with_style


@pytest.mark.asyncio
async def test_astream_threads_style_ctx_to_builder(monkeypatch, fake_llm):
    captured = {}
    real_build = PromptBuilder.build

    def _capturing_build(*args, **kwargs):
        captured["style_ctx"] = (
            kwargs.get("style_ctx") if "style_ctx" in kwargs else args[8]
        )
        return real_build(*args, **kwargs)

    monkeypatch.setattr(answer_chain.PromptBuilder, "build", _capturing_build)
    llm_factory.set_llm(fake_llm(response=["好"]))
    chunks = []
    async for token in answer_chain.astream(
        "default", _state(), _analysis(), style_ctx=_contract()
    ):
        chunks.append(token)
    assert "".join(chunks) == "好"
    assert isinstance(captured["style_ctx"], StyleContract)

    captured.clear()
    async for _ in answer_chain.astream("default", _state(), _analysis()):
        pass
    assert captured["style_ctx"] is None


def test_pipeline_style_context_records_trace_when_enabled(monkeypatch):
    from app.application import chat_pipeline

    _set_flags(monkeypatch)
    try:
        trace = TurnTraceSession()
        style_ctx = chat_pipeline._build_style_context(_state(), _analysis(), trace)
        assert style_ctx is not None
        steps = [step for step in trace.steps if step.name == "style_contract"]
        assert len(steps) == 1
        assert steps[0].status == "ok"
        assert steps[0].extra.get("style_hint")
    finally:
        get_settings.cache_clear()


def test_pipeline_style_context_skipped_when_total_off(monkeypatch):
    from app.application import chat_pipeline

    trace = TurnTraceSession()
    style_ctx = chat_pipeline._build_style_context(_state(), _analysis(), trace)
    assert style_ctx is None
    assert all(step.name != "style_contract" for step in trace.steps)


def test_enablement_chain_requires_total_gate_for_sub_flags():
    base_flags = {
        "action_enabled": False,
        "action_outbox_enabled": False,
        "unified_run_enabled": False,
        "agent_runtime_enabled": False,
        "personality_evolution_enabled": False,
        "agent_metrics_enabled": False,
        "goal_stack_enabled": False,
        "experience_enabled": False,
        "emotion_transition_enabled": False,
        "relationship_addressing_enabled": False,
        "habit_runtime_enabled": False,
        "style_contract_enabled": False,
    }
    settings = SimpleNamespace(**base_flags)
    assert enablement_violations(settings) == []

    settings.style_contract_enabled = True
    violations = enablement_violations(settings)
    assert len(violations) == 1
    assert "experience_enabled" in violations[0]

    settings.experience_enabled = True
    assert enablement_violations(settings) == []
