from datetime import datetime

import pytest

from app.core import llm_factory
from app.character.asuna import BEHAVIOR_INSTRUCTIONS
from app.chains import answer_chain
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis, UserEmotion
from app.models.behavior import BehaviorDecision
from app.models.memory import UserMemory
from app.models.relationship import RelationshipState
from app.prompts.builder import PromptBuilder


def _state():
    return ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="hi",
    )


def _analysis(behavior="comfort"):
    return TurnAnalysis(
        user_emotion=UserEmotion(emotion="sad", event="setback"),
        behavior=BehaviorDecision(behavior=behavior, reason="用户需要情绪支持"),
    )


@pytest.mark.asyncio
async def test_astream_joins_chunks(fake_llm):
    llm_factory.set_llm(fake_llm(response=["你", "好", "！"]))
    chunks = []
    async for token in answer_chain.astream("default", _state()):
        chunks.append(token)
    assert "".join(chunks) == "你好！"


@pytest.mark.asyncio
async def test_build_chain_is_runnable(fake_llm):
    llm_factory.set_llm(fake_llm(response=["ok"]))
    chain = answer_chain.build_chain("default", _state())
    assert chain is not None


@pytest.mark.asyncio
async def test_prompt_includes_dynamic_sections(fake_llm):
    llm = fake_llm(response=["hi"])
    llm_factory.set_llm(llm)
    state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[ChatMessage(role="human", content="过去消息")],
        summary="旧摘要",
        memories=[UserMemory(
            id="m1", user_id="u", memory="用户喜欢寿司", memory_type="preference",
            importance=0.8, created_at=datetime.now(), updated_at=datetime.now(),
        )],
        current_input="现在输入",
    )
    async for _ in answer_chain.astream("default", state):
        pass
    prompt_text = str(llm.seen_messages[0])
    assert "用户喜欢寿司" in prompt_text
    assert "旧摘要" in prompt_text
    assert "过去消息" in prompt_text


def test_build_without_analysis_keeps_v1_layout():
    state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[ChatMessage(role="human", content="过去消息")],
        summary="旧摘要",
        memories=[],
        current_input="现在输入",
    )
    legacy = PromptBuilder.build("default", state)
    compat = PromptBuilder.build("default", state, None)
    assert [m.prompt for m in compat.messages] == [m.prompt for m in legacy.messages]


def test_build_with_analysis_injects_state_and_behavior_sections():
    state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="我今天压力很大",
        character_state=CharacterState(
            mood="worried", energy=0.5, current_topic="工作", inner_state="有点担心"
        ),
        relationship_state=RelationshipState(
            intimacy=0.4, trust=0.6, familiarity=0.45, stage="friend"
        ),
    )
    prompt = PromptBuilder.build("default", state, _analysis("comfort"))
    rendered = str([m.prompt for m in prompt.messages])

    assert "【角色当前状态】" in rendered
    assert "心情：worried" in rendered
    assert "精力：一般" in rendered
    assert "最近在聊：工作" in rendered
    assert "【与用户的关系】" in rendered
    assert "当前关系：好友" in rendered
    assert "【本轮行为指令】" in rendered
    assert "不要急着给建议" in rendered


def test_relationship_and_energy_rendered_without_floats():
    state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="在吗",
        character_state=CharacterState(energy=0.73),
        relationship_state=RelationshipState(
            intimacy=0.42, trust=0.66, familiarity=0.31
        ),
    )
    prompt = PromptBuilder.build("default", state, _analysis())
    rendered = str([m.prompt for m in prompt.messages])
    assert not any(token in rendered for token in ("0.73", "0.42", "0.66", "0.31"))
    assert "深" in rendered


def test_unknown_behavior_falls_back_to_normal_reply():
    analysis = TurnAnalysis.model_construct(
        user_emotion=UserEmotion(),
        behavior=BehaviorDecision.model_construct(
            behavior="unknown_behavior", reason="测试未知键"
        ),
    )
    prompt = PromptBuilder.build("default", _state(), analysis)
    rendered = str([m.prompt for m in prompt.messages])
    assert "【本轮行为指令】" in rendered
    assert BEHAVIOR_INSTRUCTIONS["normal_reply"] in rendered


def test_unknown_stage_falls_back_to_friend():
    state = _state()
    state.relationship_state = RelationshipState.model_construct(
        intimacy=0.5, trust=0.5, familiarity=0.5, stage="unknown_stage"
    )
    prompt = PromptBuilder.build("default", state, _analysis())
    rendered = str([m.prompt for m in prompt.messages])
    assert "当前关系：好友" in rendered


@pytest.mark.asyncio
async def test_astream_passes_analysis_to_prompt(fake_llm):
    llm = fake_llm(response=["嗯"])
    llm_factory.set_llm(llm)
    async for _ in answer_chain.astream("default", _state(), _analysis("celebrate")):
        pass
    prompt_text = str(llm.seen_messages[0])
    assert "【本轮行为指令】" in prompt_text
    assert "由衷高兴" in prompt_text
