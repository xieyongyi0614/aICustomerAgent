"""tests/v7.8 Performance Test（testing.md §3）：观测层不改变行为、不拖慢响应。

四个守门断言：热路径无 IO / 开销预算 / 关闭即现状 / prompt 字节不变。
"""

import asyncio
import json
import time

import pytest

from app.repositories import llm_call_repository, prompt_snapshot_repository, trace_repository
from app.services import agent_service


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
            "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
        },
        "SceneIntentResult": {"intent": "chat", "confidence": 0.9, "reason": "ok"},
        "IntentionDecision": {
            "intention": "celebrate_with_user",
            "confidence": 0.9,
            "reason": "ok",
        },
        "StateUpdateDecision": {
            "mood": "happy",
            "mood_reason": "好消息",
            "inner_state": "开心",
            "current_topic": "项目上线",
        },
    }


async def _run_turn(llm, session_id, content="我今天把项目上线了", user_id="default-user"):
    events = []
    async for event in agent_service.stream_chat(session_id, user_id, content, llm=llm):
        events.append(event)
    return events


def _answer_prompt_digest(llm) -> str:
    answer_lists = [messages for messages in llm.seen_messages if len(messages) > 1]
    assert answer_lists, "未捕获 answer 链实际收到的 prompt"
    return json.dumps(
        [str(message.content) for message in answer_lists[-1]], ensure_ascii=False
    )


async def _run_many(llm, session_id, rounds=20):
    started = time.perf_counter()
    for index in range(rounds):
        await _run_turn(llm, f"{session_id}-{index}", content=f"第{index}轮消息")
    return (time.perf_counter() - started) / rounds


@pytest.mark.asyncio
async def test_hot_path_has_no_direct_io(db_session_factory, fake_llm, override_settings, monkeypatch):

    def _explode(*_args, **_kwargs):
        raise RuntimeError("观测层禁止在热路径同步写库")

    monkeypatch.setattr(trace_repository, "save", _explode)
    monkeypatch.setattr(llm_call_repository, "save", _explode)
    monkeypatch.setattr(prompt_snapshot_repository, "save", _explode)

    llm = fake_llm(response=["好耶"], structured_responses=_structured())
    events = await _run_turn(llm, "s-v78-perf-io")
    assert events[-1]["kind"] == "done"


@pytest.mark.asyncio
async def test_observability_overhead_within_budget(db_session_factory, fake_llm, override_settings):
    llm_off = fake_llm(response=["好耶"], structured_responses=_structured())
    avg_off = await _run_many(llm_off, "s-v78-perf-off")

    override_settings(
        observability_prompt_capture_mode="always",
    )
    llm_on = fake_llm(response=["好耶"], structured_responses=_structured())
    avg_on = await _run_many(llm_on, "s-v78-perf-on")

    budget_per_turn = 0.05
    assert avg_on - avg_off < budget_per_turn, (avg_off, avg_on)


@pytest.mark.asyncio
async def test_capture_does_not_change_sent_prompt_bytes(db_session_factory, fake_llm, override_settings):
    llm_off = fake_llm(response=["好耶"], structured_responses=_structured())
    await _run_turn(llm_off, "s-v78-perf-bytes-off", user_id="u-bytes-off")
    digest_off = _answer_prompt_digest(llm_off)

    override_settings(
        observability_prompt_capture_mode="always",
    )
    llm_on = fake_llm(response=["好耶"], structured_responses=_structured())
    await _run_turn(llm_on, "s-v78-perf-bytes-on", user_id="u-bytes-on")
    digest_on = _answer_prompt_digest(llm_on)

    assert digest_on == digest_off
