import pytest

from app.core import llm_factory
from app.chains import extractor_chain
from app.models.memory import MemoryDecision


@pytest.mark.asyncio
async def test_extract_save_branch(fake_llm):
    llm_factory.set_llm(fake_llm(structured_responses={
        "MemoryDecision": {
            "should_save": True,
            "memory": "用户喜欢寿司",
            "memory_type": "preference",
            "importance": 0.8,
        },
    }))
    decision = await extractor_chain.extract("我喜欢寿司", "好的")
    assert isinstance(decision, MemoryDecision)
    assert decision.should_save is True
    assert decision.memory == "用户喜欢寿司"
    assert decision.memory_type == "preference"


@pytest.mark.asyncio
async def test_extract_no_save_branch(fake_llm):
    llm_factory.set_llm(fake_llm(structured_responses={
        "MemoryDecision": {
            "should_save": False,
            "memory": None,
            "memory_type": "preference",
            "importance": 0.0,
        },
    }))
    decision = await extractor_chain.extract("今天吃了拉面", "嗯")
    assert decision.should_save is False
    assert decision.memory is None


@pytest.mark.asyncio
async def test_extract_invalid_type_rejected(fake_llm):
    llm_factory.set_llm(fake_llm(structured_responses={
        "MemoryDecision": {
            "should_save": True,
            "memory": "x",
            "memory_type": "invalid",
            "importance": 0.8,
        },
    }))
    with pytest.raises(Exception):
        await extractor_chain.extract("x", "y")
