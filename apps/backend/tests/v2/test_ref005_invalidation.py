"""REF-005：反驳与失效通道。

匹配阈值表驱动（唯一高匹配/多匹配/低匹配/空集）、find_superseded_insights
（同 scope+type 命中、跨 type 不命中）、事件钩子成功/异常路径、反驳表述变体集
（extractor 去语境化否定描述形态，invalidated 且 reason 带 memory_id）、重复触发
幂等、模糊澄清不失效（误失效率 0）、编排层 negate 接线。

口径：observe_negation 的输入是 negate 信号记忆的 content（extractor 去语境化
产物，以「用户」开头的陈述句），不是用户口语原话。
"""

from datetime import datetime

import pytest

from app.core.db import InsightRow, Memory
from app.services.reflection import lifecycle

USER = "u-neg"
CHARACTER = "asuna"

STATEMENT = "用户最近持续处于工作压力中"

NEGATION_VARIANTS = [
    "用户最近没有持续的工作压力",
    "用户最近不处于工作压力中",
    "用户最近不处于持续的工作压力中",
    "用户最近没有持续处于工作压力中",
    "用户近期没有持续处于工作压力中",
]

FUZZY_CLARIFICATIONS = [
    "用户最近状态还行",
    "用户喜欢在周末爬山",
]


class HookRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, user_id, changed):
        self.calls.append((user_id, changed))


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
    scope="user",
    type_="pattern",
    user_id=USER,
):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight_id,
                user_id=user_id,
                character_id=CHARACTER,
                statement=statement,
                type=type_,
                confidence=0.8,
                scope=scope,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return insight_id


def _seed_negated_memory(session_factory, memory_id, content, *, relation="negate"):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=USER,
                character_id=CHARACTER,
                content=content,
                type="user_fact",
                importance=0.7,
                confidence=0.9,
                source="user_stated",
                status="active",
                source_ref={
                    "table": "conversation",
                    "id": f"conv:{memory_id}",
                    "relation": relation,
                },
                visibility="private",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return memory_id


@pytest.fixture(autouse=True)
def _clean_listeners():
    lifecycle.reset_invalidation_listeners()
    yield
    lifecycle.reset_invalidation_listeners()


def test_match_threshold_unique_high_match(db_session_factory, override_settings):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_invalidate_match_threshold=0.7
    )
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    invalidated = lifecycle.observe_negation(
        USER, "mem-x", NEGATION_VARIANTS[0], trace=StubTrace()
    )
    assert invalidated == ["ins-a"]
    insight = lifecycle.get_insight("ins-a")
    assert insight.status == "invalidated"
    assert insight.invalidated_reason.startswith("user_clarification:")
    assert "mem-x" in insight.invalidated_reason


def test_match_ambiguous_multiple_ignored(db_session_factory, override_settings):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_invalidate_match_threshold=0.5
    )
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    _seed_insight(db_session_factory, "ins-b", "用户最近持续处于工作压力中，情绪疲惫")
    invalidated = lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0])
    assert invalidated == []
    assert lifecycle.get_insight("ins-a").status == "active"
    assert lifecycle.get_insight("ins-b").status == "active"


def test_match_below_threshold_ignored(db_session_factory, override_settings):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_invalidate_match_threshold=0.7
    )
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    for fuzzy in FUZZY_CLARIFICATIONS:
        assert lifecycle.observe_negation(USER, "mem-x", fuzzy) == []
    assert lifecycle.get_insight("ins-a").status == "active"


def test_match_empty_candidate_set(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    assert lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0]) == []


def test_rebuttal_variants_invalidate_and_keep_row(db_session_factory, override_settings):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_invalidate_match_threshold=0.7
    )
    for index, variant in enumerate(NEGATION_VARIANTS):
        user = f"{USER}-{index}"
        insight_id = _seed_insight(
            db_session_factory, f"ins-v{index}", STATEMENT, user_id=user
        )
        invalidated = lifecycle.observe_negation(user, f"mem-v{index}", variant)
        assert invalidated == [insight_id], variant
        insight = lifecycle.get_insight(insight_id)
        assert insight.status == "invalidated"
        assert insight.invalidated_reason.startswith("user_clarification:")
        assert f"mem-v{index}" in insight.invalidated_reason


def test_repeat_negation_is_idempotent_and_hook_fires_once(
    db_session_factory, override_settings
):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_invalidate_match_threshold=0.7
    )
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    hook = HookRecorder()
    lifecycle.register_invalidation_listener(hook)

    first = lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0])
    second = lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0])
    assert first == ["ins-a"]
    assert second == []
    assert len(hook.calls) == 1


def test_invalidation_listener_receives_change(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    hook = HookRecorder()
    lifecycle.register_invalidation_listener(hook)
    lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0])
    assert len(hook.calls) == 1
    user_id, changed = hook.calls[0]
    assert user_id == USER
    assert changed[0]["insight_id"] == "ins-a"
    assert changed[0]["status"] == "invalidated"


def test_listener_exception_does_not_break_transition(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "ins-a", STATEMENT)

    def _boom(user_id, changed):
        raise RuntimeError("listener down")

    lifecycle.register_invalidation_listener(_boom)
    invalidated = lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0])
    assert invalidated == ["ins-a"]
    assert lifecycle.get_insight("ins-a").status == "invalidated"


def test_supersede_insight_notifies_listeners(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "ins-old", STATEMENT)
    _seed_insight(db_session_factory, "ins-new", STATEMENT + "（更强的结论）")
    hook = HookRecorder()
    lifecycle.register_invalidation_listener(hook)
    assert lifecycle.supersede_insight("ins-old", "ins-new") is True
    assert len(hook.calls) == 1
    assert hook.calls[0][1][0]["superseded_by"] == "ins-new"


def test_find_superseded_insights_scope_type_and_threshold():
    from datetime import datetime as dt

    from app.models.reflection import Insight

    def _insight(insight_id, statement, scope="user", type_="pattern"):
        return Insight(
            id=insight_id,
            user_id=USER,
            statement=statement,
            type=type_,
            confidence=0.8,
            scope=scope,
            created_at=dt.now(),
            updated_at=dt.now(),
        )

    actives = [
        _insight("ins-hit", STATEMENT),
        _insight("ins-type-miss", STATEMENT, type_="belief"),
        _insight("ins-scope-miss", STATEMENT, scope="relationship"),
        _insight("ins-far", "用户喜欢在周末爬山"),
    ]
    matched = lifecycle.find_superseded_insights(
        "用户最近持续处于工作压力中（新结论）", "user", "pattern", actives
    )
    assert matched == ["ins-hit"]


def test_noop_invalidation_does_not_fire_hook(db_session_factory, override_settings):
    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    hook = HookRecorder()
    lifecycle.register_invalidation_listener(hook)
    assert lifecycle.invalidate_insight("ins-a", "第一次", "user_clarification") is True
    assert lifecycle.invalidate_insight("ins-a", "第二次", "user_clarification") is True
    assert len(hook.calls) == 1


def test_invalidate_trace_records_matching(db_session_factory, override_settings):
    override_settings(
        v2_reflection_enabled=True, v2_reflection_invalidate_match_threshold=0.7
    )
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    trace = StubTrace()
    lifecycle.observe_negation(USER, "mem-x", NEGATION_VARIANTS[0], trace=trace)
    step = trace.steps[-1]
    assert step["name"] == "reflection_invalidate"
    assert step["decision"] == "invalidated"
    assert step["memory_id"] == "mem-x"


def _make_ctx(user_id):
    from app.application.post_process import PostProcessContext
    from app.models.conversation import ConversationState
    from app.models.emotion import TurnAnalysis

    state = ConversationState(
        session_id="s1",
        user_id=user_id,
        messages=[],
        summary=None,
        memories=[],
        current_input="x",
    )
    return PostProcessContext(
        session_id="s1",
        user_id=user_id,
        user_input="x",
        ai_reply="y",
        state=state,
        analysis=TurnAnalysis(user_id=user_id, session_id="s1"),
    )


def test_post_process_wiring_observes_negations(db_session_factory, override_settings):
    """编排层接线：approve + relation=negate 的转正记忆触发失效匹配。"""
    from app.application.post_process import _observe_negations

    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    _seed_negated_memory(db_session_factory, "mem-neg", NEGATION_VARIANTS[0])
    _seed_negated_memory(
        db_session_factory, "mem-plain", "用户养了一只猫", relation="replace"
    )

    decisions = [
        type("D", (), {"action": "approve", "memory_id": "mem-neg"})(),
        type("D", (), {"action": "approve", "memory_id": "mem-plain"})(),
        type("D", (), {"action": "approve", "memory_id": "mem-gone"})(),
    ]
    _observe_negations(_make_ctx(USER), decisions)
    assert lifecycle.get_insight("ins-a").status == "invalidated"


def test_post_process_wiring_without_negate_signal_noop(db_session_factory, override_settings):
    from app.application.post_process import _observe_negations

    override_settings(v2_reflection_enabled=True)
    _seed_insight(db_session_factory, "ins-a", STATEMENT)
    _seed_negated_memory(
        db_session_factory, "mem-plain", NEGATION_VARIANTS[0], relation="replace"
    )
    decisions = [type("D", (), {"action": "approve", "memory_id": "mem-plain"})()]
    _observe_negations(_make_ctx(USER), decisions)
    assert lifecycle.get_insight("ins-a").status == "active"
