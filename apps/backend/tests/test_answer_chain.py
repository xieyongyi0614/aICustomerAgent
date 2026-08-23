from datetime import datetime

import pytest

from app.core import llm_factory
from app.chains import answer_chain
from app.models.conversation import ChatMessage, ConversationState
from app.models.memory import UserMemory


def _state():
    return ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="hi",
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
