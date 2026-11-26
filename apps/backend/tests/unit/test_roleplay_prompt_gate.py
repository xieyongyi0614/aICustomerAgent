"""演绎段注入策略位（`roleplay_prompt_mode`）的 prompt 门控单测。

full（默认）= 字节不变；off = 回答链 prompt 不再带人设/世界/演绎段，功能上下文
（记忆、目标、行动段、对话历史）照常保留。
"""

from app.models.conversation import ConversationState
from app.prompts import builder as builder_module
from app.prompts.builder import PromptBuilder

WORLD_SENTINEL = "【当前世界】冰箱：鸡蛋 × 6"


def _rendered(prompt) -> str:
    texts = []
    for message in prompt.messages:
        template = getattr(message, "prompt", None)
        texts.append(template.format() if template is not None else message.content)
    return str(texts)


def _state() -> ConversationState:
    return ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="今天花费10块钱买鸡蛋",
    )


def _fake_world(monkeypatch) -> None:
    monkeypatch.setattr(
        builder_module, "render_world_section", lambda *args, **kwargs: WORLD_SENTINEL
    )


def test_roleplay_full_keeps_persona_and_world(monkeypatch, override_settings):
    override_settings(roleplay_prompt_mode="full")
    _fake_world(monkeypatch)
    rendered = _rendered(
        PromptBuilder.build(mode="default", state=_state(), world_ctx=object())
    )
    assert "结城明日奈" in rendered
    assert WORLD_SENTINEL in rendered


def test_roleplay_off_drops_persona_and_world(monkeypatch, override_settings):
    override_settings(roleplay_prompt_mode="off")
    _fake_world(monkeypatch)
    rendered = _rendered(
        PromptBuilder.build(mode="default", state=_state(), world_ctx=object())
    )
    assert "结城明日奈" not in rendered
    assert "【当前世界】" not in rendered
    assert _state().current_input in rendered
