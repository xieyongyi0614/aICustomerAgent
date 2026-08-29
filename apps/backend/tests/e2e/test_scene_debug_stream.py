import json

from httpx import ASGITransport, AsyncClient

from app.main import app


def _structured(intent="continue_scene"):
    return {
        "RoleMode": {
            "mode": "immersive",
            "intent": "roleplay",
            "confidence": 0.9,
            "reason": "rp",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "daily"},
            "behavior": {"behavior": "normal_reply", "reason": ""},
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "",
            "inner_state": "",
            "current_topic": "",
        },
        "MemoryDecision": {
            "should_save": False,
            "memory": None,
            "memory_type": "preference",
            "importance": 0.0,
        },
        "SceneIntentResult": {"intent": intent, "confidence": 0.9, "reason": "x"},
        "SceneActionDecision": {
            "location": "客厅",
            "current_activity": None,
            "current_action": None,
            "new_pending_action": "切西瓜",
            "pending_action_done": False,
            "pending_action_cancel": False,
        },
    }


async def test_turn_meta_carries_scene_intent_and_scene_state(
    db_session_factory, llm_override, fake_llm
):
    llm_override(
        fake_llm(response=["好，我去切。"], structured_responses=_structured("request_action"))
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/chat/message", json={"content": "给我切西瓜"})

    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    meta = lines[0]
    assert meta["type"] == "turn_meta"
    assert meta["scene_intent"]["intent"] == "request_action"
    assert "scene_state" in meta
    assert meta["scene_state"]["location"] is None
