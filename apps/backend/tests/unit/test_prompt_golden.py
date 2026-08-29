"""Golden Prompt 快照回归：Prompt 文本变化必须显式更新快照并审查 diff。

重新生成：UPDATE_GOLDEN=1 uv run pytest tests/unit/test_prompt_golden.py
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage, ConversationState
from app.models.emotion import TurnAnalysis
from app.models.memory import UserMemoryV4
from app.models.relationship import RelationshipState
from app.models.scene import SceneContext, SceneState
from app.prompts.builder import PromptBuilder

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


def _render(prompt) -> str:
    return "\n---\n".join(m.content for m in prompt.format_messages())


def _base_state() -> ConversationState:
    return ConversationState(
        session_id="golden",
        user_id="golden",
        messages=[
            ChatMessage(role="human", content="你好"),
            ChatMessage(role="ai", content="你好呀"),
            ChatMessage(role="human", content="今天做什么"),
        ],
        summary="此前聊过日常安排",
        memories=[],
        current_input="现在呢",
    )


def _full_state() -> ConversationState:
    memory = UserMemoryV4(
        id="m1",
        user_id="golden",
        character_id="asuna",
        type="user_preference",
        content="用户喜欢西瓜",
        importance=0.9,
        confidence=0.95,
        source="user_stated",
        created_at=NOW,
        updated_at=NOW,
    )
    return ConversationState(
        session_id="golden",
        user_id="golden",
        messages=[ChatMessage(role="human", content="我回来了")],
        summary="此前聊过日常安排",
        memories=[memory],
        current_input="今天好累",
        character_state=CharacterState(
            mood="worried", intensity=0.65, cause="用户看起来疲惫", energy=0.5
        ),
        relationship_state=RelationshipState(
            intimacy=0.6, trust=0.6, familiarity=0.45, tension=0.55, stage="close_friend"
        ),
    )


def _full_analysis() -> TurnAnalysis:
    return TurnAnalysis(
        user_emotion={"emotion": "tired", "event": "setback"},
        behavior={"behavior": "comfort", "reason": "用户疲惫"},
        emotion_event={
            "type": "worrying_news",
            "magnitude": "normal",
            "confidence": 0.85,
            "cause": "用户连日劳累",
        },
        relationship_event={
            "type": "user_care",
            "magnitude": "normal",
            "confidence": 0.8,
            "cause": "用户主动分享状态",
        },
    )


def _scene_ctx() -> SceneContext:
    return SceneContext(
        state=SceneState(
            session_id="golden",
            turn_id=5,
            location="客厅",
            current_activity="休息",
            current_action="倒水",
        ),
        intent="chat",
        directive=None,
    )


def _assert_golden(name: str, text: str) -> None:
    path = GOLDEN_DIR / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"golden 快照缺失：{name}，请以 UPDATE_GOLDEN=1 生成"
    expected = path.read_text(encoding="utf-8")
    assert text == expected, (
        "Prompt 文本发生变化。若为有意变更，请以 UPDATE_GOLDEN=1 重新生成快照并审查 diff。"
    )


def test_golden_v1_default_without_analysis():
    _assert_golden("prompt_v1_default.txt", _render(PromptBuilder.build("default", _base_state())))


def test_golden_v5_full_sections():
    _assert_golden(
        "prompt_v5_full.txt",
        _render(
            PromptBuilder.build(
                "immersive", _full_state(), _full_analysis(), scene_ctx=_scene_ctx()
            )
        ),
    )


@pytest.mark.parametrize("name", ["prompt_v1_default.txt", "prompt_v5_full.txt"])
def test_golden_snapshots_exist(name):
    assert (GOLDEN_DIR / name).exists()
