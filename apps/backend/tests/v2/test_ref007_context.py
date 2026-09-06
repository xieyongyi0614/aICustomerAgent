"""REF-007：Insight→Context 注入段。

过滤与排序（阈值/scope/max_items）、预算裁定（记忆段占满/部分/为空）、statement
截断、prompt 渲染（段位置与空段逐字节一致）、invalidated 即时退出、Flag OFF golden。
"""

from datetime import datetime, timedelta

import pytest

from app.core.db import InsightRow
from app.prompts.builder import PromptBuilder
from app.services.context_builder import _load_context_insights
from app.services.reflection import lifecycle as reflection_lifecycle

USER = "u-ctx"


class StubTrace:
    def __init__(self):
        self.steps = []

    def record(self, name, duration_ms, status="ok", **extra):
        self.steps.append({"name": name, "status": status, **extra})


def _seed_insight(
    session_factory,
    insight_id,
    statement,
    *,
    confidence=0.8,
    scope="user",
    type_="pattern",
    status="active",
    user_id=USER,
    minutes_offset=0,
):
    from datetime import datetime as dt

    now = dt.now() + timedelta(minutes=minutes_offset)
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                character_id="asuna",
                statement=statement,
                type=type_,
                confidence=confidence,
                scope=scope,
                status=status,
                invalidated_reason="seed" if status == "invalidated" else None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return insight_id


def test_filter_threshold_scope_and_limit(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "i-low", "低置信", confidence=0.3)
    _seed_insight(db_session_factory, "i-world", "世界认知", confidence=0.9, scope="world")
    _seed_insight(db_session_factory, "i-rel", "关系认知", confidence=0.7, scope="relationship")
    _seed_insight(db_session_factory, "i-top", "用户最近持续处于工作压力中", confidence=0.9)

    selected, payload = _load_context_insights(USER, retrieval_used=0)
    ids = [s.insight_id for s in selected]
    assert ids == ["i-top", "i-rel"]
    assert payload["reasons"] == {"i-low": "below_confidence", "i-world": "scope_excluded",
                                  "i-rel": "in", "i-top": "in"}
    assert payload["used"] <= payload["budget"]


def test_max_items_cap_and_over_limit_reason(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True, v2_reflection_context_max_items=2)
    for i in range(4):
        _seed_insight(
            db_session_factory, f"i-{i}", f"认知条目 {i}", confidence=0.9 - i * 0.05
        )
    selected, payload = _load_context_insights(USER, retrieval_used=0)
    assert len(selected) == 2
    assert payload["reasons"]["i-2"] == "over_limit"
    assert payload["reasons"]["i-3"] == "over_limit"


def test_budget_full_memory_leaves_no_insight(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "i-top", "用户最近持续处于工作压力中", confidence=0.9)
    selected, payload = _load_context_insights(USER, retrieval_used=800)
    assert selected == []
    assert payload["reasons"]["i-top"] == "budget"
    assert payload["budget"] == 0


def test_budget_partial_takes_first_fit(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True, v2_reflection_context_max_items=5)
    _seed_insight(db_session_factory, "i-big", "很长" * 80, confidence=0.95)
    _seed_insight(db_session_factory, "i-small", "短认知", confidence=0.9)
    selected, payload = _load_context_insights(USER, retrieval_used=770)
    assert [s.insight_id for s in selected] == ["i-small"]
    assert payload["reasons"]["i-big"] == "budget"


def test_statement_truncated_with_ellipsis(db_session_factory, override_settings):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_context_statement_chars=10
    )
    _seed_insight(db_session_factory, "i-long", "这是一条远超截断长度的认知陈述句", confidence=0.9)
    selected, _payload = _load_context_insights(USER, retrieval_used=0)
    assert len(selected) == 1
    assert selected[0].statement == "这是一条远超截断长度…"
    assert len(selected[0].statement) == 11


def test_invalidated_immediately_exits(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(
        db_session_factory,
        "i-gone",
        "用户最近持续处于工作压力中",
        confidence=0.9,
        status="invalidated",
    )
    selected, _payload = _load_context_insights(USER, retrieval_used=0)
    assert selected == []
    _seed_insight(
        db_session_factory,
        "i-sup",
        "用户最近持续处于工作压力中（被替代）",
        confidence=0.9,
        status="superseded",
    )
    selected, _payload = _load_context_insights(USER, retrieval_used=0)
    assert selected == []


def test_flag_off_returns_empty(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=False)
    _seed_insight(db_session_factory, "i-top", "用户最近持续处于工作压力中", confidence=0.9)
    selected, payload = _load_context_insights(USER, retrieval_used=0)
    assert selected == []
    assert payload == {}


def test_query_failure_degrades_to_empty(db_session_factory, override_settings, monkeypatch):
    override_settings(v2_reflection_enabled=True)

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(reflection_lifecycle, "list_active_insights", _boom)
    selected, payload = _load_context_insights(USER, retrieval_used=0)
    assert selected == []
    assert payload == {}


def test_trace_records_decisions(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "i-top", "用户最近持续处于工作压力中", confidence=0.9)
    trace = StubTrace()
    _load_context_insights(USER, retrieval_used=0, trace=trace)
    assert trace.steps[0]["name"] == "context_insight"
    assert trace.steps[0]["reasons"]["i-top"] == "in"


def _make_state(session_factory, with_insights):
    from app.models.conversation import ChatMessage, ConversationState
    from app.models.reflection import InsightSummary

    insights = []
    if with_insights:
        insights = [
            InsightSummary(
                insight_id="i-top",
                statement="用户最近持续处于工作压力中",
                type="pattern",
                confidence=0.9,
            )
        ]
    return ConversationState(
        session_id="s1",
        user_id=USER,
        messages=[ChatMessage(role="human", content="在吗")],
        summary=None,
        memories=[],
        current_input="最近总觉得好累",
        insights=insights,
    )


def test_prompt_renders_insight_section_after_memory():
    from app.models.conversation import ChatMessage, ConversationState
    from app.models.memory import UserMemory
    from app.models.reflection import InsightSummary
    from datetime import datetime as dt

    now = dt.now()
    state = ConversationState(
        session_id="s1",
        user_id=USER,
        messages=[ChatMessage(role="human", content="在吗")],
        summary=None,
        memories=[
            UserMemory(
                id="m1",
                user_id=USER,
                character_id="asuna",
                type="user_fact",
                content="用户在深圳工作",
                importance=0.7,
                created_at=now,
                updated_at=now,
            )
        ],
        current_input="最近总觉得好累",
        insights=[
            InsightSummary(
                insight_id="i-top",
                statement="用户最近持续处于工作压力中",
                type="pattern",
                confidence=0.9,
            )
        ],
    )
    prompt = PromptBuilder.build("default", state)
    rendered = [m.content for m in prompt.format_messages()]
    memory_idx = next(i for i, t in enumerate(rendered) if "你记得关于用户的事" in t)
    insight_idx = next(i for i, t in enumerate(rendered) if "你确信的认知" in t)
    assert insight_idx == memory_idx + 1
    assert "- (模式) 用户最近持续处于工作压力中" in rendered[insight_idx]
    assert "仅在自然相关时体现" in rendered[insight_idx]


def test_prompt_without_insights_unchanged():
    from datetime import datetime as dt

    from app.models.conversation import ChatMessage, ConversationState

    now = dt.now()
    base = dict(
        session_id="s1",
        user_id=USER,
        messages=[ChatMessage(role="human", content="在吗")],
        summary=None,
        memories=[],
        current_input="最近总觉得好累",
    )
    prompt_off = PromptBuilder.build("default", ConversationState(**base))
    prompt_on = PromptBuilder.build(
        "default", ConversationState(**base, insights=[])
    )
    assert [m.content for m in prompt_off.format_messages()] == [
        m.content for m in prompt_on.format_messages()
    ]
