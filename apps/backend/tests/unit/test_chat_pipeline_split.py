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


def test_post_process_registry_contains_v5_v6_v65_steps():
    from app.application.post_process import STEP_HANDLERS

    names = [h.__name__ for h in STEP_HANDLERS]
    assert names == [
        "run_scene_update",
        "run_state_update",
        "run_goal_review",
        "run_summary",
        "run_memory_extract",
        "run_budget_observer",
        "run_evaluation",
    ]


def test_post_process_step_isolation(db_session_factory, monkeypatch):
    import asyncio

    from app.application.post_process import (
        PostProcessContext,
        run_memory_extract,
        run_state_update,
    )
    from app.models.conversation import ChatMessage, ConversationState
    from app.services.trace_collector import TurnTraceSession
    from tests.conftest import FakeLLM

    async def boom(*args, **kwargs):
        raise RuntimeError("state down")

    import app.services.state_service as state_service_module

    monkeypatch.setattr(state_service_module.state_update_chain, "update", boom)
    ctx = PostProcessContext(
        session_id="s-iso",
        user_id="u-iso",
        user_input="x",
        ai_reply="y",
        state=ConversationState(
            session_id="s-iso",
            user_id="u-iso",
            messages=[ChatMessage(role="human", content="x")],
            summary=None,
            memories=[],
            current_input="x",
        ),
        analysis=None,
        llm=FakeLLM(structured_responses={"MemoryExtraction": {"candidates": []}}),
        trace=TurnTraceSession(),
    )
    asyncio.run(run_state_update(ctx))
    asyncio.run(run_memory_extract(ctx))
    steps = {s.name: s.status for s in ctx.trace.steps}
    assert steps.get("state_update") == "error"
    assert steps.get("memory_extract") == "ok" or "memory_extract" in steps


def test_user_write_lock_serializes_post_process(monkeypatch):
    import asyncio

    from app.application import post_process

    order = []

    def make_handler(name, delay):
        async def handler(ctx):
            order.append(f"{name}-start")
            await asyncio.sleep(delay)
            order.append(f"{name}-end")

        return handler

    async def scenario():
        monkeypatch.setattr(
            post_process,
            "STEP_HANDLERS",
            (make_handler("a", 0.02), make_handler("b", 0.0)),
        )
        contexts = [
            post_process.PostProcessContext(
                session_id=f"s{i}",
                user_id="same-user",
                user_input="x",
                ai_reply="y",
                state=None,
                analysis=None,
            )
            for i in range(2)
        ]
        await asyncio.gather(*(post_process.run_post_process(ctx) for ctx in contexts))

    asyncio.run(scenario())
    assert order.index("a-end") < order.index("b-start") or order.index(
        "b-end"
    ) < order.index("a-start")
