import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, Memory as MemoryRow, MemoryCandidateRow
from app.core.settings import get_settings
from app.repositories import memory_repository
from app.services.memory import commands, evaluator, lifecycle


@pytest.fixture
def cmd_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (commands, evaluator, lifecycle, memory_repository):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_state():
    lifecycle.reset_reinforce_buffer()
    yield
    lifecycle.reset_reinforce_buffer()


def _memory(id, content, type="user_preference", status="active", user_id="u1", embedding="[0.1]", salience=0.7):
    now = datetime.datetime.now()
    with memory_repository.SessionLocal() as session:
        session.add(
            MemoryRow(
                id=id,
                user_id=user_id,
                character_id="asuna",
                content=content,
                type=type,
                importance=0.7,
                status=status,
                salience=salience,
                embedding=embedding if status == "active" else None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _rows():
    with memory_repository.SessionLocal() as session:
        rows = session.query(MemoryRow).all()
        for row in rows:
            session.expunge(row)
        return rows


def _candidates():
    with commands.SessionLocal() as session:
        rows = session.query(MemoryCandidateRow).all()
        for row in rows:
            session.expunge(row)
        return rows


def _llm_guard(monkeypatch):
    async def _fail(*args, **kwargs):
        raise AssertionError("LLM 不应被调用")

    monkeypatch.setattr(evaluator, "_ask_llm", _fail)


class TestDetectCommand:
    @pytest.mark.parametrize(
        "text,action,object_hint",
        [
            ("记住我最喜欢西瓜", "remember", "我最喜欢西瓜"),
            ("帮我记住我的生日是五月", "remember", "我的生日是五月"),
            ("记一下，我周三要开会", "remember", "我周三要开会"),
            ("记着我在深圳工作", "remember", "我在深圳工作"),
            ("帮我记一下养了只猫", "remember", "养了只猫"),
            ("忘掉那件事", "forget", "那件事"),
            ("忘记我说过的话", "forget", "我说过的话"),
            ("删除记忆：用户喜欢香菜", "forget", "用户喜欢香菜"),
            ("别记了，那条不对", "forget", "那条不对"),
            ("忘了吧，那家店倒闭了", "forget", "那家店倒闭了"),
        ],
    )
    def test_variants_detected(self, text, action, object_hint):
        detected = commands.detect_command(text)
        assert detected is not None
        assert detected[0] == action
        assert object_hint in detected[1]

    @pytest.mark.parametrize(
        "text",
        [
            "今天天气不错",
            "我记得你上次说过这句话",
            "别忘了明天要带伞",
            "你要好好记住这段经历吗？",
            "记住",
            "忘掉",
            "忘记",
        ],
    )
    def test_non_commands_or_too_short(self, text):
        assert commands.detect_command(text) is None

    def test_object_punctuation_stripped(self):
        detected = commands.detect_command("记住，我最喜欢西瓜")
        assert detected == ("remember", "我最喜欢西瓜")


class TestRememberCommand:
    def test_explicit_remember_promotes_without_llm(self, cmd_db, monkeypatch):
        _llm_guard(monkeypatch)
        import asyncio

        outcome = asyncio.run(
            commands.handle("u1", "记住我最喜欢西瓜", trace=None)
        )
        assert outcome == commands.OUTCOME_REMEMBER_PROMOTED
        memories = [row for row in _rows() if row.status == "active"]
        assert len(memories) == 1
        assert memories[0].salience == 1.0
        assert memories[0].content == "我最喜欢西瓜"
        assert memories[0].type == "user_preference"
        assert len(_candidates()) == 1

    def test_replay_idempotent_single_memory(self, cmd_db, monkeypatch):
        _llm_guard(monkeypatch)
        import asyncio

        asyncio.run(commands.handle("u1", "记住我最喜欢西瓜"))
        asyncio.run(commands.handle("u1", "记住我最喜欢西瓜"))
        assert len([row for row in _rows() if row.status == "active"]) == 1
        assert len(_candidates()) == 1

    def test_existing_same_topic_reinforced_not_duplicated(self, cmd_db):
        _memory("m1", "我最喜欢西瓜", salience=0.5)
        import asyncio

        outcome = asyncio.run(
            commands.handle("u1", "记住我最喜欢西瓜", trace=None)
        )
        assert outcome == commands.OUTCOME_REMEMBER_REINFORCED
        actives = [row for row in _rows() if row.status == "active"]
        assert len(actives) == 1
        assert actives[0].id == "m1"
        assert actives[0].salience == pytest.approx(0.6)

    def test_fact_content_maps_to_user_fact(self, cmd_db, monkeypatch):
        _llm_guard(monkeypatch)
        import asyncio

        asyncio.run(commands.handle("u1", "记住我住在深圳"))
        memories = [row for row in _rows() if row.status == "active"]
        assert memories[0].type == "user_fact"


class TestForgetCommand:
    def test_unique_high_match_forgets(self, cmd_db):
        _memory("m1", "用户喜欢吃香菜", embedding="[0.1]")
        import asyncio

        outcome = asyncio.run(commands.handle("u1", "忘掉用户喜欢吃香菜"))
        assert outcome == commands.OUTCOME_FORGOT
        row = next(r for r in _rows() if r.id == "m1")
        assert row.status == "forgotten"
        assert row.embedding is None
        assert row.forgotten_at is not None
        assert memory_repository.list_active("u1", "asuna") == []
        assert memory_repository.list_pending_embedding() == []

    def test_multiple_matches_no_deletion(self, cmd_db):
        _memory("m1", "用户喜欢吃香菜")
        _memory("m2", "用户特别喜欢吃香菜")
        import asyncio

        outcome = asyncio.run(commands.handle("u1", "忘掉用户喜欢吃香菜"))
        assert outcome == commands.OUTCOME_MISS
        assert all(row.status == "active" for row in _rows())

    def test_no_match_degrades_without_deletion(self, cmd_db):
        _memory("m1", "用户喜欢吃香菜")
        import asyncio

        outcome = asyncio.run(commands.handle("u1", "忘掉那件完全无关的事"))
        assert outcome == commands.OUTCOME_MISS
        assert all(row.status == "active" for row in _rows())

    def test_repeat_forget_after_success_is_noop(self, cmd_db):
        _memory("m1", "用户喜欢吃香菜")
        import asyncio

        asyncio.run(commands.handle("u1", "忘掉用户喜欢吃香菜"))
        outcome = asyncio.run(commands.handle("u1", "忘掉用户喜欢吃香菜"))
        assert outcome == commands.OUTCOME_MISS
        assert len(_rows()) == 1


class TestPostProcessWiring:
    async def test_command_hit_skips_ingest(self, cmd_db, monkeypatch):
        from app.application.post_process import PostProcessContext, _run_memory_ingest_v2
        from app.models.conversation import ConversationState
        from app.models.emotion import TurnAnalysis

        executed = {"ingest": False}

        async def _fake_ingest(ctx):
            executed["ingest"] = True

        ctx = PostProcessContext(
            session_id="s1",
            user_id="u1",
            user_input="记住我最喜欢西瓜",
            ai_reply="好的",
            state=ConversationState(
                session_id="s1",
                user_id="u1",
                messages=[],
                summary=None,
                memories=[],
                current_input="",
            ),
            analysis=TurnAnalysis(),
        )
        await _run_memory_ingest_v2(ctx)
        assert executed["ingest"] is False
        memories = [row for row in _rows() if row.status == "active"]
        assert len(memories) == 1

    async def test_command_miss_runs_ingest(self, cmd_db, monkeypatch):
        from app.application.post_process import PostProcessContext, _run_memory_ingest_v2
        from app.models.conversation import ConversationState
        from app.models.emotion import TurnAnalysis
        from app.models.memory import MemoryExtraction

        class _FakeIngest:
            @staticmethod
            def ingest_from_conversation(user_id, extraction, source_id_base, **kwargs):
                return []

        monkeypatch.setattr(
            "app.chains.extractor_chain.extract_candidates",
            _fake_extraction,
        )
        ctx = PostProcessContext(
            session_id="s1",
            user_id="u1",
            user_input="今天天气不错",
            ai_reply="是呀",
            state=ConversationState(
                session_id="s1",
                user_id="u1",
                messages=[],
                summary=None,
                memories=[],
                current_input="",
            ),
            analysis=TurnAnalysis(),
        )
        await _run_memory_ingest_v2(ctx)
        assert _candidates() == []


async def _fake_extraction(*args, **kwargs):
    from app.models.memory import MemoryExtraction

    return MemoryExtraction(candidates=[])
