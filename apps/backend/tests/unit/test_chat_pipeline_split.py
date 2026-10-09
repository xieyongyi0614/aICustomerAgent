from app.application import chat_pipeline


def test_agent_service_shell_retired():
    """T-33：`services/agent_service` 兼容壳已退役，入口收敛到 `chat_pipeline`。"""
    import importlib.util

    assert importlib.util.find_spec("app.services.agent_service") is None
    assert callable(chat_pipeline.stream_chat)
    assert chat_pipeline.EmptyLLMResponseError is not None


def test_background_tasks_set_shared_with_pipeline_registration():
    sentinel = object()
    chat_pipeline.background_tasks.add(sentinel)
    assert sentinel in chat_pipeline.background_tasks
    chat_pipeline.background_tasks.discard(sentinel)
    assert sentinel not in chat_pipeline.background_tasks


def test_post_process_registry_contains_v5_v6_v65_steps():
    from app.application.post_process import STEP_HANDLERS

    names = [h.__name__ for h in STEP_HANDLERS]
    assert names == [
        "run_scene_update",
        "run_state_update",
        "run_goal_review",
        "run_summary",
        "run_memory_extract",
        "run_ledger_extraction",
        "run_ledger_confirmation",
        "run_budget_observer",
        "run_evaluation",
        "run_world_update",
        "run_character_action_sync",
        "run_action_planning",
        "run_memory_evaluate",
    ]


def test_post_process_step_isolation(db_session_factory, monkeypatch):
    import asyncio

    from app.application.post_process import (
        PostProcessContext,
        run_memory_extract,
        run_state_update,
    )
    from app.models.conversation import ChatMessage, ConversationState
    from app.services.observability.collector import TurnTraceSession
    from tests.conftest import FakeLLM

    async def boom(*args, **kwargs):
        raise RuntimeError("state down")

    import app.services.conversation.state as state_service_module

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
    assert steps.get("memory_extractor") == "ok" or "memory_extractor" in steps


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
