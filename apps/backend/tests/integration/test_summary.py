import asyncio
import time

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from app.core import llm_factory
from app.repositories import summary_repository as repo
from app.services import summary_service


def test_threshold_boundary(override_settings):
    override_settings(summary_threshold=40)
    assert summary_service.should_summarize(39) is False
    assert summary_service.should_summarize(40) is True


@pytest.mark.asyncio
async def test_empty_input_skips_llm(fake_llm):
    llm_factory.set_llm(fake_llm(response="不该被调用"))
    result = await summary_service.generate("旧摘要", [])
    assert result == "旧摘要"


@pytest.mark.asyncio
async def test_rolling_prompt_contains_old_and_new(fake_llm):
    llm = fake_llm(response="新摘要")
    llm_factory.set_llm(llm)
    result = await summary_service.generate("旧摘要内容", ["用户说了 X", "亚丝娜回答 Y"])
    assert result == "新摘要"
    prompt_text = str(llm.seen_messages[0])
    assert "旧摘要内容" in prompt_text
    assert "用户说了 X" in prompt_text


@pytest.mark.asyncio
async def test_update_upserts_single_row(db_session_factory, fake_llm):
    llm_factory.set_llm(fake_llm(response="摘要一"))
    await summary_service.update("conv1", ["第一轮"])
    llm_factory.set_llm(fake_llm(response="摘要二"))
    await summary_service.update("conv1", ["第二轮"])
    row = repo.get_summary("conv1")
    assert row.summary == "摘要二"
    assert repo.get_summary("conv1") is not None


def test_get_summary_none(db_session_factory):
    assert repo.get_summary("missing") is None


def test_upsert_refreshes_updated_at(db_session_factory, fake_llm):
    async def _run():
        llm_factory.set_llm(fake_llm(response="a"))
        await summary_service.update("conv2", ["m"])
        first = repo.get_summary("conv2").updated_at
        time.sleep(0.02)
        llm_factory.set_llm(fake_llm(response="b"))
        await summary_service.update("conv2", ["m2"])
        second = repo.get_summary("conv2").updated_at
        return first, second

    first, second = asyncio.run(_run())
    assert second >= first


@pytest.mark.asyncio
async def test_update_empty_input_no_write(db_session_factory):
    await summary_service.update("conv3", [])
    assert repo.get_summary("conv3") is None


@pytest.mark.asyncio
async def test_llm_failure_propagates(db_session_factory, fake_llm):
    class FailingLLM(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("summary llm down")

        @property
        def _llm_type(self):
            return "fake"

    llm_factory.set_llm(FailingLLM())
    with pytest.raises(RuntimeError):
        await summary_service.update("conv4", ["消息"])
