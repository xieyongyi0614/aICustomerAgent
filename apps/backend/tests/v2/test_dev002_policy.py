"""DEV-002：DevPolicy 编译器。

规则表驱动编译（preference/belief/pattern × 命中/未命中）、封顶（strength 上限
× 预设幅度）、纯函数幂等（同 Insight 重复编译逐字节一致）、仲裁（高胜低/同
strength 取新 Insight/落败留痕）、创建事件 → 入队 → job 编译端到端、Flag OFF
与规则未命中零写入。
"""

from datetime import datetime, timedelta

import pytest

from app.core.db import BackgroundJobRow, DevelopmentStateRow, InsightRow
from app.models.reflection import Insight, InsightDraft, ReflectionProposal
from app.services.development import aggregate
from app.services.development import policy
from app.services.memory import job_worker as memory_job_worker
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection import reflector

pytestmark = pytest.mark.xdist_group("development")

USER = "u-dev"
CHARACTER = "asuna"


def _insight(**overrides) -> Insight:
    now = datetime(2026, 9, 1, 12, 0, 0)
    defaults = dict(
        id="ins-c1",
        user_id=USER,
        statement="用户偏好简短的回复",
        type="preference",
        confidence=0.8,
        scope="user",
        run_id=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Insight(**defaults)


def _keys(proposals):
    return [item.key for item in proposals]


def test_compile_preference_length_and_tone():
    proposals = policy.compile_insight(_insight())
    assert _keys(proposals) == [
        policy.KEY_RESPONSE_STYLE_LENGTH,
        policy.KEY_RESPONSE_STYLE_TONE,
    ]
    assert proposals[0].value == {"max_tokens_delta": -160}
    assert proposals[1].value == {"tone_hint": "更简练、直给，不绕弯子"}


def test_compile_preference_without_tone_keyword():
    proposals = policy.compile_insight(_insight(statement="用户喜欢简洁表达"))
    assert _keys(proposals) == [policy.KEY_RESPONSE_STYLE_LENGTH]


def test_compile_belief_topics_and_habits():
    proposals = policy.compile_insight(
        _insight(statement="用户最近经常加班到深夜", type="belief", confidence=0.7)
    )
    assert _keys(proposals) == [
        policy.KEY_BEHAVIOR_CARE_TOPICS,
        policy.KEY_BEHAVIOR_HABIT_CANDIDATES,
    ]
    assert proposals[0].value["topics"] == ["工作压力"]
    candidate = proposals[1].value["candidates"][0]
    assert candidate["id"] == "dev_habit_late_care"
    assert candidate["domain"] == "relate"


def test_compile_belief_no_rule_hit_is_empty():
    proposals = policy.compile_insight(
        _insight(statement="用户喜欢在海边散步", type="belief")
    )
    assert proposals == []


def test_compile_pattern_goal_and_autonomy():
    proposals = policy.compile_insight(
        _insight(statement="用户近期持续高压", type="pattern", confidence=0.9)
    )
    assert _keys(proposals) == [
        policy.KEY_GOAL_USER_CARE_WEIGHT,
        policy.KEY_AUTONOMY_TIME_PREFERENCE,
    ]
    assert proposals[0].value == {"tier_delta": 0.45}
    assert proposals[1].value == {"late_night_bias": 0.9}


def test_compile_cap_saturated_under_reinforcement():
    settings = policy.get_settings()
    saturating = [
        policy.compile_insight(
            _insight(
                id=f"ins-cap-{i}",
                type="preference",
                confidence=0.95,
                created_at=datetime(2026, 9, 1) + timedelta(days=i),
            ),
            settings,
        )
        for i in range(10)
    ]
    deltas = {item.value["max_tokens_delta"] for items in saturating for item in items
              if item.key == policy.KEY_RESPONSE_STYLE_LENGTH}
    assert deltas == {-190}
    assert all(abs(delta) <= settings.development_preference_max_token_delta
               for delta in deltas)


def test_compile_pure_and_idempotent():
    first = policy.compile_insight(_insight())
    second = policy.compile_insight(_insight())
    assert first == second


def test_arbitration_higher_strength_wins(db_session_factory):
    loser = policy.compile_insight(_insight(id="ins-low", confidence=0.5))
    winner = policy.compile_insight(_insight(id="ins-high", confidence=0.9))
    assert aggregate.upsert_modulation(
        USER, loser[0].kind, loser[0].key, loser[0].value, loser[0].strength,
        loser[0].insight_id, comparator=policy.arbitration_comparator,
    ).outcome == aggregate.OUTCOME_CREATED
    assert aggregate.upsert_modulation(
        USER, winner[0].kind, winner[0].key, winner[0].value, winner[0].strength,
        winner[0].insight_id, comparator=policy.arbitration_comparator,
    ).outcome == aggregate.OUTCOME_REPLACED
    actives = aggregate.list_active_modulations(USER)
    assert len(actives) == 1
    assert actives[0].source_insight_id == "ins-high"


def _seed_insight_row(session_factory, insight: Insight):
    with session_factory() as session:
        session.add(
            InsightRow(
                id=insight.id,
                user_id=insight.user_id,
                character_id=insight.character_id,
                statement=insight.statement,
                type=insight.type,
                confidence=insight.confidence,
                scope=insight.scope,
                status="active",
                created_at=insight.created_at,
                updated_at=insight.created_at,
            )
        )
        session.commit()


def test_arbitration_tie_prefers_newer_insight(db_session_factory):
    old = policy.compile_insight(_insight(id="ins-old", confidence=0.8))
    new = policy.compile_insight(
        _insight(id="ins-new", confidence=0.8, created_at=datetime(2026, 9, 5))
    )
    _seed_insight_row(db_session_factory, _insight(id="ins-old", confidence=0.8))
    _seed_insight_row(
        db_session_factory, _insight(id="ins-new", confidence=0.8, created_at=datetime(2026, 9, 5))
    )
    assert aggregate.upsert_modulation(
        USER, old[0].kind, old[0].key, old[0].value, old[0].strength,
        old[0].insight_id,
        source_insight_created_at=old[0].insight_created_at,
        comparator=policy.arbitration_comparator,
    ).outcome == aggregate.OUTCOME_CREATED
    assert aggregate.upsert_modulation(
        USER, new[0].kind, new[0].key, new[0].value, new[0].strength,
        new[0].insight_id,
        source_insight_created_at=new[0].insight_created_at,
        comparator=policy.arbitration_comparator,
    ).outcome == aggregate.OUTCOME_REPLACED
    actives = aggregate.list_active_modulations(USER)
    assert actives[0].source_insight_id == "ins-new"


def test_arbitration_tie_without_existing_insight_time_keeps_incumbent(
    db_session_factory,
):
    first = policy.compile_insight(_insight(id="ins-keep", confidence=0.8))
    challenger = policy.compile_insight(
        _insight(id="ins-unknown", confidence=0.8)
    )
    aggregate.upsert_modulation(
        USER, first[0].kind, first[0].key, first[0].value, first[0].strength,
        first[0].insight_id, comparator=policy.arbitration_comparator,
    )
    outcome = aggregate.upsert_modulation(
        USER, challenger[0].kind, challenger[0].key, challenger[0].value,
        challenger[0].strength, challenger[0].insight_id,
        comparator=policy.arbitration_comparator,
    )
    assert outcome.outcome == aggregate.OUTCOME_LOST


@pytest.fixture
def dev_on(override_settings):
    override_settings()


@pytest.fixture(autouse=True)
def _reset_dev_listeners():
    yield
    reflection_lifecycle.reset_insight_created_listeners()


def _seed_cluster_memory(session_factory, memory_id, *, created_at, content):
    import json

    from app.core.db import Memory

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
                salience=0.8,
                embedding=json.dumps([1.0 if i == 3 else 0.1 for i in range(8)]),
                source_ref={"table": "conversation", "id": f"conv:u:s:{memory_id}"},
                visibility="private",
                created_at=created_at,
                updated_at=now,
            )
        )
        session.commit()


def _seed_fatigue(session_factory):
    now = datetime.now()
    for i in range(5):
        _seed_cluster_memory(
            session_factory,
            f"mem-dev-{i}",
            created_at=now - timedelta(days=i * 2),
            content="用户说最近加班很累" if i == 0 else f"用户说最近加班很累（第{i + 1}次）",
        )


def _seed_run(session_factory, run_id):
    from app.core.db import ReflectionRunRow

    now = datetime.now()
    with session_factory() as session:
        session.add(
            ReflectionRunRow(
                id=run_id,
                user_id=USER,
                character_id=CHARACTER,
                trigger="scheduled",
                status="queued",
                llm_used=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


class ScriptedLLM:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        def _resolve(inputs):
            self.calls += 1
            item = self.proposal
            return item if isinstance(item, ReflectionProposal) else schema.model_validate(item)

        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(_resolve)

    def __call__(self, *args, **kwargs):
        return self


def _pressure_proposal() -> ReflectionProposal:
    draft = InsightDraft(
        statement="用户最近经常加班，处于持续高压",
        type="pattern",
        scope="user",
        evidence_ids=["E1", "E2", "E3"],
        counter_evidence="无",
        self_confidence=0.9,
    )
    return ReflectionProposal(insights=[draft])


def _dev_states(session_factory):
    with session_factory() as session:
        rows = session.query(DevelopmentStateRow).all()
        for row in rows:
            session.expunge(row)
        return rows


def test_end_to_end_creation_event_compiles(db_session_factory, dev_on, monkeypatch):
    policy.register_runtime()
    llm = ScriptedLLM(_pressure_proposal())
    monkeypatch.setattr(reflector, "_resolve_llm", lambda settings: llm)
    _seed_fatigue(db_session_factory)
    _seed_run(db_session_factory, "run-dev")
    assert reflector.run_queued_reflections() == 1
    with db_session_factory() as session:
        job = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == policy.JOB_TYPE_COMPILE)
            .one()
        )
        assert job.status == "pending"
    stats = memory_job_worker.run_job_tick()
    assert stats["done"] >= 1
    states = _dev_states(db_session_factory)
    keys = {row.key for row in states if row.status == "active"}
    assert keys == {
        policy.KEY_GOAL_USER_CARE_WEIGHT,
        policy.KEY_AUTONOMY_TIME_PREFERENCE,
    }
    with db_session_factory() as session:
        job = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.job_type == policy.JOB_TYPE_COMPILE)
            .one()
        )
        assert job.status == "done"


def test_compile_idempotent_replay_keeps_rows(db_session_factory, dev_on, monkeypatch):
    policy.register_runtime()
    llm = ScriptedLLM(_pressure_proposal())
    monkeypatch.setattr(reflector, "_resolve_llm", lambda settings: llm)
    _seed_fatigue(db_session_factory)
    _seed_run(db_session_factory, "run-dev")
    reflector.run_queued_reflections()
    memory_job_worker.run_job_tick()
    before = _dev_states(db_session_factory)
    assert policy.compile_insight_by_id(before[0].source_insight_id) is True
    after = _dev_states(db_session_factory)
    assert len(after) == len(before)
    assert {row.status for row in after} == {row.status for row in before}


def test_missing_insight_job_skips_cleanly(db_session_factory, dev_on):
    policy.register_runtime()
    policy.on_insight_created(USER, [{"insight_id": "ins-ghost"}])
    stats = memory_job_worker.run_job_tick()
    assert stats["done"] >= 1
    assert _dev_states(db_session_factory) == []


def test_flag_off_no_listener_no_compilation(
    db_session_factory, reflection_on, monkeypatch
):
    llm = ScriptedLLM(_pressure_proposal())
    monkeypatch.setattr(reflector, "_resolve_llm", lambda settings: llm)
    _seed_fatigue(db_session_factory)
    _seed_run(db_session_factory, "run-dev")
    assert reflector.run_queued_reflections() == 1
    assert _dev_states(db_session_factory) == []


@pytest.fixture
def reflection_on(override_settings):
    override_settings()


def test_runtime_registration_is_idempotent(override_settings):
    override_settings()
    policy.register_runtime()
    policy.register_runtime()
    handlers = memory_job_worker._JOB_HANDLERS
    assert handlers[policy.JOB_TYPE_COMPILE] is policy.run_compile_jobs
    assert reflection_lifecycle._insight_created_listeners.count(
        policy.on_insight_created
    ) == 2
    reflection_lifecycle.reset_insight_created_listeners()
