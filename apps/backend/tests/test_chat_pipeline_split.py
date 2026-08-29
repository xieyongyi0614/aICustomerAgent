from app.application import chat_pipeline
from app.services import agent_service


def test_agent_service_reexports_pipeline_symbols():
    assert agent_service.background_tasks is chat_pipeline.background_tasks
    assert agent_service.EmptyLLMResponseError is chat_pipeline.EmptyLLMResponseError
    assert agent_service.run_chat_pipeline is chat_pipeline.run_chat_pipeline


def test_background_tasks_set_shared_with_pipeline_registration():
    sentinel = object()
    chat_pipeline.background_tasks.add(sentinel)
    assert sentinel in chat_pipeline.background_tasks
    assert sentinel in agent_service._background_tasks
    chat_pipeline.background_tasks.discard(sentinel)
    assert sentinel not in agent_service._background_tasks
