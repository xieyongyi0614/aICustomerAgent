from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.services.observability.prompt_capture import (
    _bounded_messages,
    _redact,
    section_budget_from_messages,
)


def _answer_like_messages():
    return [
        SystemMessage(content="人设一段" * 3),
        SystemMessage(content="【角色当前情绪】\n心情：happy"),
        SystemMessage(content="【你记得关于用户的事】\n- 用户喜欢咖啡"),
        SystemMessage(content="【对话摘要】\n之前聊了工作…"),
        HumanMessage(content="早上好"),
        AIMessage(content="早呀"),
        SystemMessage(content="【本轮指令】\n保持轻快"),
        HumanMessage(content="今天穿什么好看"),
    ]


def test_section_budget_classifies_known_sections():
    budget = section_budget_from_messages(_answer_like_messages())
    assert budget["identity"] == 12
    assert budget["emotion"] == len("【角色当前情绪】\n心情：happy")
    assert budget["memory"] == len("【你记得关于用户的事】\n- 用户喜欢咖啡")
    assert budget["summary"] == len("【对话摘要】\n之前聊了工作…")
    assert budget["history"] == len("早上好") + len("早呀")
    assert budget["scene"] == len("【本轮指令】\n保持轻快")
    assert budget["user_message"] == len("今天穿什么好看")
    assert budget["total"] == sum(
        value for key, value in budget.items() if key not in ("total", "budget")
    )
    assert budget["budget"] > 0


def test_bounded_messages_truncates_total_and_flags():
    messages = [SystemMessage(content="x" * 30), HumanMessage(content="y" * 30)]
    payload, truncated = _bounded_messages(messages, 40)
    assert truncated is True
    total = sum(len(item["content"]) for item in payload)
    assert total <= 40
    assert [item["role"] for item in payload] == ["system", "human"]


def test_bounded_messages_passthrough_when_small():
    messages = [SystemMessage(content="小"), HumanMessage(content="你好")]
    payload, truncated = _bounded_messages(messages, 1000)
    assert truncated is False
    assert payload[0]["content"] == "小"


def test_redact_placeholder_without_preview_chars(monkeypatch):
    assert _redact("秘密内容") == "秘密内容"
    monkeypatch.setenv("OBSERVABILITY_PROMPT_REDACT", "true")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    redacted = _redact("秘密内容")
    assert "秘密" not in redacted
    get_settings.cache_clear()
