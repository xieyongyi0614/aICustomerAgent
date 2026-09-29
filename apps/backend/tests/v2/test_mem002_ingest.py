import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, MemoryCandidateRow
from app.models.memory import MemoryCandidate, MemoryExtraction
from app.services.memory import ingest
from app.services.memory.ingest import (
    VISIBILITY_HYPOTHETICAL,
    VISIBILITY_PRIVATE,
    classify_conversation_visibility,
)


@pytest.fixture
def ingest_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(ingest, "SessionLocal", testing_session)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _extraction(candidates):
    return MemoryExtraction(candidates=candidates)


def _cand(content, importance=0.7, type="user_preference", source="user_stated"):
    return MemoryCandidate(
        action="save", type=type, content=content,
        importance=importance, confidence=0.9, source=source,
    )


class _Step:
    def __init__(self, name, status, error, extra):
        self.name = name
        self.status = status
        self.error = error
        self.extra = extra


class _TraceSpy:
    def __init__(self):
        self.records = []

    def record(self, name, duration_ms, status="ok", error=None, **extra):
        self.records.append(_Step(name, status, error, extra))


class TestVocabPrefilter:
    @pytest.mark.parametrize(
        "text",
        [
            "假装我是国王",
            "如果我是程序员会怎样",
            "假如我们住在一起",
            "要是能去日本旅游就好了",
            "扮演一个老师跟我说话",
            "假设他是凶手",
            "作为你的朋友，你应该……",
        ],
    )
    def test_hypothetical_triggers(self, text):
        visibility, reason = classify_conversation_visibility(text)
        assert visibility == VISIBILITY_HYPOTHETICAL
        assert reason is None

    @pytest.mark.parametrize(
        "text",
        [
            "帮我拿块西瓜",
            "帮我递一下那个杯子",
            "递给我遥控器",
            "把书放到书架上",
            "放一下钥匙",
            "打开空调",
            "关一下灯",
            "取下那幅画",
        ],
    )
    def test_transient_triggers_blocked(self, text):
        visibility, reason = classify_conversation_visibility(text)
        assert visibility is None
        assert reason is not None and reason.startswith("transient_action:")

    @pytest.mark.parametrize(
        "text",
        [
            "我喜欢吃寿司",
            "我在深圳工作",
            "我们一起去过海边",
            "我养了一只猫",
            "面试通过了很开心",
        ],
    )
    def test_normal_not_blocked(self, text):
        visibility, reason = classify_conversation_visibility(text)
        assert visibility == VISIBILITY_PRIVATE
        assert reason is None


class TestCreateCandidate:
    def test_assembles_fields(self, ingest_db):
        row = ingest.create_candidate(
            user_id="u1", character_id="asuna",
            source_table="action_records", source_id="a1",
            content="记住用户生日在五月", proposed_type="user_fact",
            source_kind="user_derived", salience_init=0.8,
        )
        assert row.status == "pending"
        assert row.visibility == VISIBILITY_PRIVATE
        assert row.source_ref == {"table": "action_records", "id": "a1"}

    def test_idempotent_same_source_returns_existing(self, ingest_db):
        ingest.create_candidate(
            user_id="u1", character_id="asuna",
            source_table="action_records", source_id="a1",
            content="内容A", proposed_type="user_fact",
            source_kind="user_derived", salience_init=0.6,
        )
        second = ingest.create_candidate(
            user_id="u1", character_id="asuna",
            source_table="action_records", source_id="a1",
            content="内容B", proposed_type="user_fact",
            source_kind="user_derived", salience_init=0.9,
        )
        assert second.source_id == "a1"
        with ingest_db() as session:
            count = session.query(MemoryCandidateRow).filter_by(
                source_table="action_records", source_id="a1"
            ).count()
        assert count == 1


class TestIngestFromConversation:
    def test_normal_candidates_created(self, ingest_db):
        extraction = _extraction(
            [_cand("我喜欢寿司"), _cand("我在深圳工作", type="user_fact")]
        )
        rows = ingest.ingest_from_conversation("u1", extraction, "conv:u1:s1")
        assert len(rows) == 2
        assert {r.visibility for r in rows} == {VISIBILITY_PRIVATE}
        assert {r.proposed_type for r in rows} == {"user_preference", "user_fact"}

    def test_hypothetical_kept(self, ingest_db):
        extraction = _extraction([_cand("假装我是国王")])
        rows = ingest.ingest_from_conversation("u1", extraction, "conv:u1:s1")
        assert len(rows) == 1
        assert rows[0].visibility == VISIBILITY_HYPOTHETICAL

    def test_transient_blocked_no_candidate(self, ingest_db):
        extraction = _extraction([_cand("帮我拿块西瓜")])
        trace = _TraceSpy()
        rows = ingest.ingest_from_conversation("u1", extraction, "conv:u1:s1", trace=trace)
        assert rows == []
        assert any(
            step.name == "memory_ingest" and step.status == "blocked"
            for step in trace.records
        )

    def test_ingest_max_caps(self, ingest_db):
        extraction = _extraction([_cand(f"事实{i}") for i in range(20)])
        rows = ingest.ingest_from_conversation("u1", extraction, "conv:u1:s1")
        assert len(rows) == 10

    def test_idempotent_reingest_same_source_base(self, ingest_db):
        extraction = _extraction([_cand("我喜欢寿司")])
        ingest.ingest_from_conversation("u1", extraction, "conv:u1:s1")
        gather = ingest.ingest_from_conversation("u1", extraction, "conv:u1:s1")
        assert len(gather) == 1
        with ingest_db() as session:
            count = session.query(MemoryCandidateRow).filter_by(
                source_table="conversation", user_id="u1"
            ).count()
        assert count == 1


class TestIngestFromActionRecord:
    def test_succeeded_reminder_deposits(self, ingest_db):
        record = _action_record(
            id="a1", action_type="create_reminder",
            params={"content": "记得五月给妈妈买礼物"}, status="succeeded",
        )
        row = ingest.ingest_from_action_record(record)
        assert row is not None
        assert row.source_table == "action_records"
        assert row.source_id == "a1"
        assert "五月" in row.content

    def test_query_type_not_deposited(self, ingest_db):
        record = _action_record(id="a2", action_type="query_search", status="succeeded")
        assert ingest.ingest_from_action_record(record) is None

    def test_non_terminal_skipped(self, ingest_db):
        record = _action_record(id="a3", action_type="create_reminder", status="planned")
        assert ingest.ingest_from_action_record(record) is None

    def test_idempotent_repeat(self, ingest_db):
        record = _action_record(
            id="a1", action_type="create_reminder",
            params={"content": "记得五月买礼物"}, status="succeeded",
        )
        ingest.ingest_from_action_record(record)
        ingest.ingest_from_action_record(record)
        with ingest_db() as session:
            count = session.query(MemoryCandidateRow).filter_by(
                source_table="action_records", source_id="a1"
            ).count()
        assert count == 1


class TestIngestFromWorldEvent:
    def test_completed_deposits(self, ingest_db):
        event = _world_event(
            id="w1", status="completed", title="面试通过",
            importance="high", user_id="u1",
        )
        event.completed_at = datetime.datetime(2026, 9, 29, 12, 0)
        row = ingest.ingest_from_world_event(event, user_id="u1")
        assert row is not None
        assert row.source_table == "world_events"
        assert row.content == "用户在09月29日完成了面试通过"
        assert row.proposed_type == "important_event"
        assert row.salience == 0.8

    def test_content_matches_world_bridge_format(self, ingest_db):
        """两通道内容必须逐字一致，否则富描述会被裸标题顶掉（台账 §5.2.1）。"""

        from app.services.world import memory_bridge as world_memory_bridge

        event = _world_event(
            id="w3", status="completed", title="面试通过",
            importance="high", user_id="u1",
        )
        event.completed_at = datetime.datetime(2026, 9, 29, 12, 0)
        row = ingest.ingest_from_world_event(event, user_id="u1")
        expected = world_memory_bridge.to_memory_candidates(event)[0]["content"]
        assert row.content == expected

    def test_non_completed_skipped(self, ingest_db):
        event = _world_event(
            id="w2", status="scheduled", title="待办", importance="low", user_id="u1",
        )
        assert ingest.ingest_from_world_event(event, user_id="u1") is None


class TestIngestFromRelationshipEvent:
    def test_deposits_relationship_candidate(self, ingest_db):
        event = _relationship_event(id="r1", user_id="u1", type="user_care", cause="用户生病我照顾")
        row = ingest.ingest_from_relationship_event(event)
        assert row is not None
        assert row.source_table == "relationship_events"
        assert row.proposed_type == "relationship_event"

    def test_idempotent(self, ingest_db):
        event = _relationship_event(id="r1", user_id="u1", type="praise")
        ingest.ingest_from_relationship_event(event)
        ingest.ingest_from_relationship_event(event)
        with ingest_db() as session:
            count = session.query(MemoryCandidateRow).filter_by(
                source_table="relationship_events", source_id="r1"
            ).count()
        assert count == 1


def _action_record(id, action_type, status, params=None):
    from app.models.action import ActionRecord

    return ActionRecord(
        id=id, user_id="u1", character_id="asuna", action_type=action_type,
        params=params or {}, status=status, created_at=datetime.datetime.now(),
    )


def _world_event(id, status, title, importance, user_id):
    from app.models.world import WorldEvent

    return WorldEvent(
        id=id, world_id=f"home:{user_id}", type="reminder",
        title=title, importance=importance, status=status,
        created_at=datetime.datetime.now(), updated_at=datetime.datetime.now(),
    )


def _relationship_event(id, user_id, type, cause=""):
    from app.models.relationship import RelationshipDelta, RelationshipEvent

    return RelationshipEvent(
        id=id, user_id=user_id, character_id="asuna", session_id="s1",
        type=type, magnitude="normal",
        impact=RelationshipDelta(intimacy=0.03, trust=0.02, familiarity=0.01,
                                 tension=-0.01, respect=0.0, comfort=0.0),
        confidence=0.9, source="conversation", cause=cause,
        created_at=datetime.datetime.now(),
    )