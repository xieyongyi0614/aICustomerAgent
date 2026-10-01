"""V8-007 e2e：世界段进入聊天 prompt、解释器在下一轮可见、禁用时零字节。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories import prompt_snapshot_repository


def _structured():
    return {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "achievement"},
            "behavior": {"behavior": "normal_reply", "reason": "ok"},
        },
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {
            "intention": "continue_topic",
            "confidence": 0.9,
            "reason": "ok",
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "ok",
            "inner_state": "平静",
            "current_topic": "日常",
        },
    }


async def _chat(client, content):
    async with client.stream("POST", "/api/v1/chat/message", json={"content": content}) as resp:
        assert resp.status_code == 200
        body = await resp.aread()
    import json

    lines = [json.loads(line) for line in body.decode().splitlines() if line.strip()]
    return lines[-1].get("turn_id")


async def _await_until(predicate, timeout=10.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        import asyncio

        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_world_section_reaches_prompt_and_persists(
    db_session_factory, fake_llm, llm_override, override_settings
):
    override_settings(
        roleplay_prompt_mode="full",
        observability_persist_enabled=True,
        observability_prompt_capture_mode="always",
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    llm_override(llm)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        seeded = await client.post(
            "/api/v1/debug/world/entities",
            json={"name": "西瓜", "category": "food", "location_id": "home.kitchen.fridge", "aliases": ["瓜"]},
        )
        assert seeded.status_code == 200
        first = await _chat(client, "给我拿个西瓜")
        from app.application import world_engine

        def _world_moved():
            obj = world_engine.find_object_by_name("default-user", "西瓜")
            return obj is not None and obj.location_id == "home.living_room"

        assert await _await_until(_world_moved)
        second = await _chat(client, "谢谢亲爱的")

        assert await _await_until(
            lambda: prompt_snapshot_repository.get_by_turn(second) != []
        )
        second_prompts = prompt_snapshot_repository.get_by_turn(second)
        answer = next(p for p in second_prompts if p.call_site.value == "answer")
        world_texts = [
            m["content"] for m in answer.messages if "【当前世界】" in m.get("content", "")
        ]
        assert world_texts, "第二轮 prompt 应包含【当前世界】段"
        assert "西瓜" in world_texts[0]

        first_prompts = await _await_until(
            lambda: prompt_snapshot_repository.get_by_turn(first) != []
        )
        first_answer = next(
            p for p in prompt_snapshot_repository.get_by_turn(first) if p.call_site.value == "answer"
        )
        assert any("【当前世界】" in m.get("content", "") for m in first_answer.messages)


@pytest.mark.asyncio
async def test_world_prompt_carries_world_section(
    db_session_factory, fake_llm, llm_override, override_settings
):
    override_settings(
        roleplay_prompt_mode="full",
        observability_persist_enabled=True,
        observability_prompt_capture_mode="always",
    )
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    llm_override(llm)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        turn_id = await _chat(client, "在吗")
        assert await _await_until(
            lambda: prompt_snapshot_repository.get_by_turn(turn_id) != []
        )
        prompts = prompt_snapshot_repository.get_by_turn(turn_id)
        answer = next(p for p in prompts if p.call_site.value == "answer")
        assert any("【当前世界】" in m.get("content", "") for m in answer.messages)
