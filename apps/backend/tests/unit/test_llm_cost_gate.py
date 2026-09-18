"""V2.0.0 LLM 成本红线守门测试（R1 / 验收门 3）：单轮前台 LLM 调用数 ≤ v1 基线。

文档口径（phase-1 regression-checklist Golden 行为 #3 / v2.0.0 README §10.5）：
前台每轮 LLM 调用 ≤ v1 基线（5 次），V2 全闸开启不得上浮超过 1.2×。
本测试以 FakeLLM.seen_messages 计量整条前台 chat 管线的真实调用次数，
未触发的后台 post_process 不计入（与后台成本豁免口径一致）。
"""

import pytest

from app.services import agent_service


def _structured():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "TurnAnalysis": {
            "user_emotion": {"emotion": "happy", "event": "achievement"},
            "behavior": {"behavior": "celebrate", "reason": "ok"},
        },
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {"intention": "continue_topic", "confidence": 0.9, "reason": "ok"},
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "ok",
            "inner_state": "平静",
            "current_topic": "日常",
        },
    }

V1_FOREGROUND_BASELINE = 5


async def _run_turn(llm, session_id, content="今天怎么样"):
    events = []
    async for event in agent_service.stream_chat(session_id, "default-user", content, llm=llm):
        events.append(event)
    assert events[-1]["kind"] == "done"
    return len(llm.seen_messages)


@pytest.mark.asyncio
async def test_foreground_llm_calls_flag_off_within_v1_baseline(db_session_factory, fake_llm):
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    calls = await _run_turn(llm, "cost-off")
    assert calls <= V1_FOREGROUND_BASELINE, calls


@pytest.mark.asyncio
async def test_foreground_llm_calls_full_v2_flags_on_stays_within_cap(
    db_session_factory, fake_llm, override_settings
):
    override_settings(
        v2_action_outbox_enabled="true",
        action_enabled="true")
    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    calls = await _run_turn(llm, "cost-on")
    assert calls <= round(V1_FOREGROUND_BASELINE * 1.2), calls