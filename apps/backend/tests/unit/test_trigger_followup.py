"""V7-010：scheduled_followup（Memory Trigger，trigger-model.md §4 / Scenario 4）。"""

from datetime import datetime, timedelta

from app.services.autonomy import trigger as trigger_evaluator
from app.services.autonomy_policy import PolicySnapshot, evaluate

NOW = datetime(2026, 8, 30, 14, 0)
CONFIG = __import__("app.core.settings", fromlist=["get_settings"]).get_settings()


def test_find_followup_event_keywords():
    assert trigger_evaluator.find_followup_event("明天有面试") == "面试"
    assert trigger_evaluator.find_followup_event("记得今天下午的会议") == "会议"
    assert trigger_evaluator.find_followup_event("今天天气不错") is None


def test_register_and_poll_due(monkeypatch):
    trigger_evaluator._followup_registry.clear()
    due = NOW + timedelta(hours=2)
    trigger_evaluator.register_followup("u1", due, "面试近况跟进")

    assert trigger_evaluator.poll_due_followup("u1", NOW) is None
    signal = trigger_evaluator.poll_due_followup("u1", due + timedelta(minutes=1))
    assert signal is not None
    assert signal.type == "scheduled_followup"
    assert signal.dedupe_key.startswith("followup:")
    assert signal.context["summary"] == "面试近况跟进"
    assert trigger_evaluator.poll_due_followup("u1", due + timedelta(minutes=2)) is None
    trigger_evaluator._followup_registry.clear()


def test_poll_isolated_per_user():
    trigger_evaluator._followup_registry.clear()
    trigger_evaluator.register_followup("u1", NOW, "面试")
    assert trigger_evaluator.poll_due_followup("u2", NOW + timedelta(hours=1)) is None
    trigger_evaluator._followup_registry.clear()


def test_followup_signal_acts_when_policy_passes():
    trigger_evaluator._followup_registry.clear()
    due = NOW
    trigger_evaluator.register_followup("u1", due, "面试近况跟进")
    signal = trigger_evaluator.poll_due_followup("u1", due)
    verdict = evaluate(
        signal,
        PolicySnapshot(intimacy=0.62, selected_goal_type="user_care"),
        CONFIG,
        NOW,
    )
    assert verdict.decision == "act"
    assert verdict.intention == "check_in"
    trigger_evaluator._followup_registry.clear()


def test_followup_not_exempt_from_quiet_hours():
    """设计要求：MVP followup 静音不豁免（quiet-hours.md §4）。"""
    trigger_evaluator._followup_registry.clear()
    due = NOW.replace(hour=23, minute=30)
    trigger_evaluator.register_followup("u1", due, "面试近况跟进")
    signal = trigger_evaluator.poll_due_followup("u1", due)
    verdict = evaluate(
        signal,
        PolicySnapshot(intimacy=0.62, selected_goal_type="user_care"),
        CONFIG,
        due,
    )
    assert verdict.decision == "ignore"
    assert verdict.reason == "静音时段"
    trigger_evaluator._followup_registry.clear()


def test_memory_pipeline_registers_followup(db_session_factory, fake_llm):
    """V7-010 断链恢复：会话候选经 v2 摄取（run_memory_extract）登记 followup。

    原 v1 契约（extract_and_save → _register_followups）随 v1 删除断链，
    登记点现承接于 post_process._run_memory_ingest_v2 的会话候选行。
    """
    import asyncio

    from app.application.post_process import PostProcessContext, run_memory_extract
    from app.models.conversation import ChatMessage, ConversationState

    trigger_evaluator._followup_registry.clear()
    llm = fake_llm(
        response=[],
        structured_responses={
            "MemoryExtraction": {
                "candidates": [
                    {
                        "action": "save",
                        "source": "user_stated",
                        "type": "important_event",
                        "content": "用户明天有一场重要的面试",
                        "importance": 0.9,
                        "confidence": 0.9,
                    }
                ]
            }
        },
    )
    ctx = PostProcessContext(
        session_id="s-followup",
        user_id="u1",
        user_input="我明天有面试，好紧张",
        ai_reply="别紧张，你准备得很充分",
        state=ConversationState(
            session_id="s-followup",
            user_id="u1",
            messages=[ChatMessage(role="human", content="我明天有面试，好紧张")],
            summary=None,
            memories=[],
            current_input="我明天有面试，好紧张",
        ),
        analysis=None,
        llm=llm,
    )
    asyncio.run(run_memory_extract(ctx))

    summaries = [
        item["summary"] for item in trigger_evaluator._followup_registry.values()
    ]
    assert summaries == ["面试近况跟进"]
    trigger_evaluator._followup_registry.clear()


def test_memory_pipeline_without_event_keyword_registers_nothing(
    db_session_factory, fake_llm
):
    """无事件关键词的候选不登记（防噪音 followup）。"""
    import asyncio

    from app.application.post_process import PostProcessContext, run_memory_extract
    from app.models.conversation import ChatMessage, ConversationState

    trigger_evaluator._followup_registry.clear()
    llm = fake_llm(
        response=[],
        structured_responses={
            "MemoryExtraction": {
                "candidates": [
                    {
                        "action": "save",
                        "source": "user_stated",
                        "type": "user_preference",
                        "content": "用户喜欢抹茶拿铁",
                        "importance": 0.8,
                        "confidence": 0.9,
                    }
                ]
            }
        },
    )
    ctx = PostProcessContext(
        session_id="s-followup-neg",
        user_id="u1",
        user_input="我最喜欢抹茶拿铁了",
        ai_reply="抹茶拿铁确实很经典呢",
        state=ConversationState(
            session_id="s-followup-neg",
            user_id="u1",
            messages=[ChatMessage(role="human", content="我最喜欢抹茶拿铁了")],
            summary=None,
            memories=[],
            current_input="我最喜欢抹茶拿铁了",
        ),
        analysis=None,
        llm=llm,
    )
    asyncio.run(run_memory_extract(ctx))

    assert trigger_evaluator._followup_registry == {}
    trigger_evaluator._followup_registry.clear()
