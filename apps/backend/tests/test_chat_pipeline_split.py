import asyncio

from app.application import chat_pipeline
from app.services import agent_service


def test_agent_service_reexports_pipeline_symbols():
    assert agent_service.background_tasks is chat_pipeline.background_tasks
    assert agent_service.EmptyLLMResponseError is chat_pipeline.EmptyLLMResponseError
    assert agent_service.run_chat_pipeline is chat_pipeline.run_chat_pipeline


def test_background_tasks_set_shared_with_pipeline_registration():
    async def _noop():
        return None

    loop = asyncio.new_event_loop()
    try:
        task = loop.run_until_complete(asyncio.ensure_future(_noop()))
    finally:
        loop.close()
    chat_pipeline.background_tasks.add(task)
    assert task in chat_pipeline.background_tasks
    chat_pipeline.background_tasks.discard(task)
    assert task not in chat_pipeline.background_tasks
