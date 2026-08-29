from datetime import datetime, timedelta

from app.core.db import Memory
from app.repositories import memory_repository as repo
from app.services import memory_service


def _insert_row(
    session_factory,
    content: str,
    memory_type: str = "user_preference",
    importance: float = 0.7,
    character_id: str = "asuna",
    status: str = "active",
    created_at: datetime | None = None,
    last_accessed_at: datetime | None = None,
    expires_at: datetime | None = None,
    memory_id: str | None = None,
    user_id: str = "u1",
) -> str:
    now = datetime.now()
    row_id = memory_id or content
    with session_factory() as session:
        session.add(
            Memory(
                id=row_id,
                user_id=user_id,
                memory=content,
                memory_type=memory_type,
                importance=importance,
                character_id=character_id,
                status=status,
                created_at=created_at or now,
                updated_at=now,
                last_accessed_at=last_accessed_at,
                expires_at=expires_at,
            )
        )
        session.commit()
    return row_id


def retrieve_contents(*args, **kwargs):
    return [m.content for m in memory_service.retrieve_v4(*args, **kwargs)]


class TestWeightedRecall:
    def test_lexical_relevant_ranks_first(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", importance=0.7)
        _insert_row(db_session_factory, "用户在深圳工作", memory_type="user_fact")
        results = retrieve_contents("u1", "我爱吃西瓜", character_id="asuna")
        assert results[0] == "用户喜欢西瓜"

    def test_importance_boosts_ranking(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢吃西瓜", importance=0.5)
        _insert_row(db_session_factory, "用户喜欢吃西瓜吗", importance=0.95, memory_id="m2")
        results = retrieve_contents("u1", "我喜欢吃西瓜", character_id="asuna")
        assert results[0] == "用户喜欢吃西瓜吗"

    def test_top_k_respected(self, db_session_factory):
        for i in range(7):
            _insert_row(db_session_factory, f"用户喜欢水果{i}", memory_id=f"m{i}")
        results = retrieve_contents("u1", "我喜欢水果", character_id="asuna", top_k=3)
        assert len(results) == 3

    def test_type_affinity_boosts_preference(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", importance=0.7)
        _insert_row(
            db_session_factory,
            "用户养西瓜形抱枕",
            memory_type="user_fact",
            importance=0.7,
            memory_id="m2",
        )
        results = retrieve_contents("u1", "你喜欢什么", character_id="asuna")
        assert results[0] == "用户喜欢西瓜"


class TestFilters:
    def test_invalidated_memory_not_recalled(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", status="invalidated")
        assert retrieve_contents("u1", "我喜欢西瓜", character_id="asuna") == []

    def test_superseded_memory_not_recalled(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", status="superseded")
        assert retrieve_contents("u1", "我喜欢西瓜", character_id="asuna") == []

    def test_expired_memory_not_recalled(self, db_session_factory):
        _insert_row(
            db_session_factory,
            "用户喜欢西瓜",
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert retrieve_contents("u1", "我喜欢西瓜", character_id="asuna") == []

    def test_other_character_excluded_wildcard_included(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", character_id="kirito")
        _insert_row(db_session_factory, "用户在深圳工作", memory_type="user_fact", memory_id="m2")
        _insert_row(
            db_session_factory,
            "用户养了一只猫",
            memory_type="user_fact",
            character_id="asuna",
            memory_id="m3",
        )
        results = retrieve_contents("u1", "我的情况", character_id="asuna")
        assert "用户喜欢西瓜" not in results
        assert "用户在深圳工作" in results
        assert "用户养了一只猫" in results

    def test_scoped_by_user(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", user_id="other")
        assert retrieve_contents("u1", "我喜欢西瓜", character_id="asuna") == []


class TestRecency:
    def test_recent_accessed_ranks_higher(self, db_session_factory):
        old = datetime.now() - timedelta(days=120)
        _insert_row(db_session_factory, "用户喜欢吃甜西瓜", importance=0.7, memory_id="m1")
        _insert_row(
            db_session_factory,
            "用户喜欢吃酸西瓜",
            importance=0.7,
            memory_id="m2",
            last_accessed_at=old,
        )
        results = retrieve_contents("u1", "我喜欢吃西瓜", character_id="asuna")
        assert results[0] == "用户喜欢吃甜西瓜"


class TestFallbackAndDegradation:
    def test_at_least_one_highest_importance_fallback(self, db_session_factory, monkeypatch):
        _insert_row(db_session_factory, "用户喜欢西瓜", importance=0.6)
        _insert_row(
            db_session_factory,
            "用户在深圳工作",
            memory_type="user_fact",
            importance=0.95,
            memory_id="m2",
        )
        original = memory_service.get_settings
        monkeypatch.setattr(
            memory_service,
            "get_settings",
            lambda: type("S", (), {**original().model_dump(), "memory_min_score": 0.99})(),
        )
        results = retrieve_contents("u1", "随便聊聊", character_id="asuna")
        assert results == ["用户在深圳工作"]

    def test_repo_failure_degrades_to_empty(self, db_session_factory, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(memory_service.repo, "list_active_v4", boom)
        assert retrieve_contents("u1", "我喜欢西瓜", character_id="asuna") == []


class TestWriteback:
    def test_last_accessed_written_after_recall(self, db_session_factory):
        _insert_row(db_session_factory, "用户喜欢西瓜", memory_id="m1")
        retrieve_contents("u1", "我喜欢西瓜", character_id="asuna")
        assert repo.get_memory_v4("m1").last_accessed_at is not None

    def test_writeback_failure_tolerated(self, db_session_factory, monkeypatch):
        _insert_row(db_session_factory, "用户喜欢西瓜", memory_id="m1")

        def boom(*args, **kwargs):
            raise RuntimeError("write fail")

        monkeypatch.setattr(memory_service.repo, "touch_last_accessed", boom)
        results = retrieve_contents("u1", "我喜欢西瓜", character_id="asuna")
        assert results == ["用户喜欢西瓜"]


class TestV1RetrieveUnchanged:
    def test_v1_retrieve_still_works(self, db_session_factory):
        repo.create_memory("u1", "用户喜欢寿司", "preference", 0.8)
        results = memory_service.retrieve("u1", "寿司好吃吗")
        assert len(results) == 1
        assert results[0].memory == "用户喜欢寿司"
