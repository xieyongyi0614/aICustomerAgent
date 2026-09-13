"""WS-009：UserSituationTracker 测试（检出/解除/过期/LLM 辅助闸/第 8 步接线）。"""

from datetime import datetime, timedelta

import pytest

from app.application import post_process
from app.core.settings import get_settings
from app.models.world_simulation import SituationDimension, SituationStatus
from app.repositories import world_repository, world_simulation_repository as repo
from app.services.world import user_situation

pytestmark = pytest.mark.xdist_group("ws009")


def _flags(monkeypatch, **extra):
    envs = {
        "V23_WORLD_SIMULATION_ENABLED": "true",
        "V23_EVENT_DETECTION_ENABLED": "true",
    }
    for key, value in extra.items():
        envs[key.upper()] = str(value).lower() if isinstance(value, bool) else str(value)
    for key, value in envs.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def detect_flags(monkeypatch):
    yield from _flags(monkeypatch)


@pytest.fixture
def assist_flags(monkeypatch):
    yield from _flags(
        monkeypatch,
        v23_world_llm_assist_enabled=True,
        v23_llm_assist_sample_rate=1.0,
    )


def _events(user_id: str):
    world = world_repository.ensure_world(user_id)
    return world_repository.list_events(world.world_id, limit=50)


def test_health_detection_with_high_importance(db_session_factory, detect_flags):
    user = "ws009-health"
    situation = user_situation.detect_from_message(
        user, "我感冒了，头好疼", evidence={"session_id": "s1", "turn": 3}
    )
    assert situation is not None
    assert situation.dimension == SituationDimension.HEALTH
    assert situation.intensity >= 4
    assert situation.evidence["quote"].startswith("我感冒了")
    assert situation.valid_until > datetime.now()
    events = [e for e in _events(user) if e.type == "user_condition"]
    assert events and events[0].importance.value == "high"
    assert events[0].payload["kind"] == "detected"


def test_work_pressure_detection_normal_importance(db_session_factory, detect_flags):
    situation = user_situation.detect_from_message("ws009-work", "这周天天加班，压力太大")
    assert situation.dimension == SituationDimension.WORK_PRESSURE
    events = [e for e in _events("ws009-work") if e.type == "user_condition"]
    assert events[0].importance.value == "normal"


def test_no_situation_no_writes(db_session_factory, detect_flags):
    user = "ws009-none"
    assert user_situation.detect_from_message(user, "今天天气不错") is None
    assert repo.list_situations(user) == []


def test_same_dimension_supersedes(db_session_factory, detect_flags):
    user = "ws009-supersede"
    first = user_situation.detect_from_message(user, "我感冒了")
    second = user_situation.detect_from_message(user, "还是不舒服，又发烧了")
    statuses = {s.id: s.status for s in repo.list_situations(user)}
    assert statuses[first.id] == SituationStatus.EXPIRED
    assert statuses[second.id] == SituationStatus.ACTIVE


def test_dismissal_emits_ended(db_session_factory, detect_flags):
    user = "ws009-dismiss"
    situation = user_situation.detect_from_message(user, "我感冒了")
    dismissed = user_situation.dismiss_matching(user, "我好了，没事了", datetime.now())
    assert situation.id in dismissed
    assert repo.get_situation(user, situation.id).status == SituationStatus.DISMISSED
    events = [e for e in _events(user) if e.type == "user_condition"]
    ended = [e for e in events if e.payload["kind"] == "ended"]
    assert ended and ended[0].importance.value == "low"


def test_expire_and_notify(db_session_factory, detect_flags):
    user = "ws009-expire"
    situation = user_situation.detect_from_message(user, "我感冒了")
    stale = user_situation.detect_from_message(user, "最近压力大")
    expired = user_situation.expire_and_notify(user, datetime.now() + timedelta(hours=72))
    assert {s.id for s in expired} == {situation.id, stale.id}
    events = [e for e in _events(user) if e.type == "user_condition"]
    assert sum(1 for e in events if e.payload["kind"] == "ended") == 2


def test_llm_assist_requires_flag(db_session_factory):
    user = "ws009-assist-off"
    assert user_situation.detect_from_message(user, "最近有点不在状态") is None
    assert repo.list_situations(user) == []


def test_llm_assist_success_path(db_session_factory, assist_flags, monkeypatch):
    user = "ws009-assist"

    class _Result:
        dimension = "emotional_context"
        summary = "用户最近有些低落"
        intensity = 2

    class _Chain:
        def invoke(self, payload):
            return _Result()

    monkeypatch.setattr(
        "app.chains.structured.build_structured_chain",
        lambda messages, schema: _Chain(),
    )
    situation = user_situation.detect_from_message(user, "最近有点不在状态")
    assert situation is not None
    assert situation.source.value == "llm_assist"
    assert situation.dimension == SituationDimension.EMOTIONAL_CONTEXT


def test_llm_assist_failure_silent(db_session_factory, assist_flags, monkeypatch):
    user = "ws009-assist-fail"

    def _explode(messages, schema):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "app.chains.structured.build_structured_chain",
        _explode,
    )
    assert user_situation.detect_from_message(user, "最近有点不在状态") is None
    assert repo.list_situations(user) == []


@pytest.mark.asyncio
async def test_post_process_step8_integration(db_session_factory, detect_flags, monkeypatch):
    monkeypatch.setattr(world_repository, "list_objects", lambda *a, **k: [])
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        session_id="s-ws009",
        user_id="ws009-step8",
        user_input="我感冒了，难受",
        ai_reply="多喝水",
        current_turn=2,
        trace=None,
    )
    await post_process.run_world_update(ctx)
    situations = repo.list_situations("ws009-step8")
    assert situations and situations[0].dimension == SituationDimension.HEALTH
