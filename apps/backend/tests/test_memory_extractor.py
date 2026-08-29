import pytest

from app.chains import extractor_chain
from app.core.settings import get_settings
from app.models.memory import MemoryExtraction
from tests.conftest import FakeLLM


def _extraction_response(candidates):
    return {"MemoryExtraction": {"candidates": candidates}}


class TestExtractCandidates:
    @pytest.mark.asyncio
    async def test_preference_extracted(self):
        llm = FakeLLM(
            structured_responses=_extraction_response(
                [
                    {
                        "action": "save",
                        "type": "user_preference",
                        "content": "用户喜欢西瓜",
                        "importance": 0.8,
                        "confidence": 0.95,
                        "source": "user_stated",
                    }
                ]
            )
        )
        extraction = await extractor_chain.extract_candidates(
            "我喜欢西瓜", "夏天吃西瓜最舒服了", llm=llm
        )
        assert isinstance(extraction, MemoryExtraction)
        assert len(extraction.candidates) == 1
        candidate = extraction.candidates[0]
        assert candidate.type == "user_preference"
        assert candidate.content == "用户喜欢西瓜"
        assert candidate.source == "user_stated"

    @pytest.mark.asyncio
    async def test_fact_and_event_extracted(self):
        llm = FakeLLM(
            structured_responses=_extraction_response(
                [
                    {
                        "action": "save",
                        "type": "user_fact",
                        "content": "用户在深圳工作",
                        "importance": 0.8,
                        "confidence": 0.9,
                        "source": "user_stated",
                    },
                    {
                        "action": "save",
                        "type": "important_event",
                        "content": "用户上周参加了面试",
                        "importance": 0.7,
                        "confidence": 0.85,
                        "source": "user_stated",
                    },
                ]
            )
        )
        extraction = await extractor_chain.extract_candidates(
            "我在深圳上班，上周还去面试了", "加油！", llm=llm
        )
        assert {c.type for c in extraction.candidates} == {"user_fact", "important_event"}

    @pytest.mark.asyncio
    async def test_chitchat_returns_empty(self):
        llm = FakeLLM(structured_responses=_extraction_response([]))
        extraction = await extractor_chain.extract_candidates(
            "哈哈哈哈", "是呀是呀", llm=llm
        )
        assert extraction.candidates == []

    @pytest.mark.asyncio
    async def test_ai_inferred_source_passed_through(self):
        llm = FakeLLM(
            structured_responses=_extraction_response(
                [
                    {
                        "action": "save",
                        "type": "user_preference",
                        "content": "用户期待旅行",
                        "importance": 0.6,
                        "confidence": 0.4,
                        "source": "ai_inferred",
                    }
                ]
            )
        )
        extraction = await extractor_chain.extract_candidates(
            "明天出发", "你一定很期待吧", llm=llm
        )
        assert extraction.candidates[0].source == "ai_inferred"

    @pytest.mark.asyncio
    async def test_forget_instruction_recognized(self):
        llm = FakeLLM(
            structured_responses=_extraction_response(
                [
                    {
                        "action": "forget",
                        "type": "user_preference",
                        "content": "用户喜欢咖啡",
                        "importance": 0.5,
                        "confidence": 0.9,
                        "source": "user_stated",
                    }
                ]
            )
        )
        extraction = await extractor_chain.extract_candidates(
            "之前说的喜欢咖啡的事，忘了吧", "好的", llm=llm
        )
        assert extraction.candidates[0].action == "forget"

    @pytest.mark.asyncio
    async def test_suppress_instruction_recognized(self):
        llm = FakeLLM(
            structured_responses=_extraction_response(
                [
                    {
                        "action": "suppress",
                        "type": "user_fact",
                        "content": "用户的收入信息",
                        "importance": 0.5,
                        "confidence": 0.9,
                        "source": "user_stated",
                    }
                ]
            )
        )
        extraction = await extractor_chain.extract_candidates(
            "这个别存下来", "明白", llm=llm
        )
        assert extraction.candidates[0].action == "suppress"

    @pytest.mark.asyncio
    async def test_invalidate_instruction_recognized(self):
        llm = FakeLLM(
            structured_responses=_extraction_response(
                [
                    {
                        "action": "invalidate",
                        "type": "user_preference",
                        "content": "用户喜欢咖啡",
                        "importance": 0.5,
                        "confidence": 0.95,
                        "source": "user_stated",
                        "target_memory_id": "m-old",
                    }
                ]
            )
        )
        extraction = await extractor_chain.extract_candidates(
            "我现在已经不喝咖啡了", "了解", llm=llm
        )
        assert extraction.candidates[0].action == "invalidate"

    @pytest.mark.asyncio
    async def test_candidate_cap_enforced(self):
        over_cap = [
            {
                "action": "save",
                "type": "user_fact",
                "content": f"用户事实{i}",
                "importance": 0.5,
            }
            for i in range(5)
        ]
        llm = FakeLLM(structured_responses=_extraction_response(over_cap))
        extraction = await extractor_chain.extract_candidates("x", "y", llm=llm)
        assert len(extraction.candidates) == get_settings().memory_max_candidates

    @pytest.mark.asyncio
    async def test_none_output_treated_as_empty(self):
        llm = FakeLLM(structured_responses={"MemoryExtraction": None})
        extraction = await extractor_chain.extract_candidates("x", "y", llm=llm)
        assert extraction.candidates == []

    @pytest.mark.asyncio
    async def test_recent_context_passed_to_llm(self):
        llm = FakeLLM(structured_responses=_extraction_response([]))
        await extractor_chain.extract_candidates(
            "它在那里", "好的", recent_context="用户：我买了一只猫\nAI：真可爱", llm=llm
        )
        assert any("我买了一只猫" in str(m) for m in llm.seen_messages)

    @pytest.mark.asyncio
    async def test_empty_recent_context_defaults(self):
        llm = FakeLLM(structured_responses=_extraction_response([]))
        await extractor_chain.extract_candidates("x", "y", llm=llm)
        assert any("（无）" in str(m) for m in llm.seen_messages)


class TestLegacyChainUnchanged:
    @pytest.mark.asyncio
    async def test_v1_extract_still_works(self):
        llm = FakeLLM(
            structured_responses={
                "MemoryDecision": {
                    "should_save": True,
                    "memory": "用户喜欢寿司",
                    "memory_type": "preference",
                    "importance": 0.8,
                }
            }
        )
        decision = await extractor_chain.extract("我喜欢寿司", "好呀", llm=llm)
        assert decision.should_save is True
        assert decision.memory == "用户喜欢寿司"
