"""V7-002：proactive_actions 状态机 / 深度 1 / 幂等 / 聚合记账。"""

from datetime import datetime, timedelta

from app.models.autonomy import ProactiveAction
from app.repositories import proactive_repository as repo

NOW = datetime(2026, 8, 30, 14, 0)


def _action(**overrides) -> ProactiveAction:
    payload = {
        "id": "a1",
        "user_id": "u1",
        "session_id": "s1",
        "trigger_type": "conversation_inactivity",
        "dedupe_key": "inactivity:u1:42",
        "intention": "check_in",
        "reason": "闲置关心",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ProactiveAction(**payload)


def test_enqueue_and_get_active(db_session_factory):
    assert repo.enqueue(_action()) is True
    active = repo.get_active("u1", now=NOW)
    assert active is not None
    assert active.status == "candidate"
    assert active.attempt == 0


def test_enqueue_blocked_by_depth_one(db_session_factory):
    assert repo.enqueue(_action()) is True
    assert repo.enqueue(_action(id="a2")) is False


def test_enqueue_dedupe_key_rejected_until_discarded(db_session_factory):
    assert repo.enqueue(_action()) is True
    repo.transition("a1", "discarded", now=NOW)
    assert repo.has_non_terminal("u1") is False
    assert repo.enqueue(_action(id="a3", dedupe_key="inactivity:u1:43")) is True


def test_state_machine_legal_path(db_session_factory):
    repo.enqueue(_action())
    assert repo.transition("a1", "delivered", now=NOW) is None
    approved = repo.transition("a1", "approved", now=NOW)
    assert approved is not None and approved.status == "approved"
    delivered = repo.transition(
        "a1", "delivered", now=NOW, delivered_at=NOW, message_id="7"
    )
    assert delivered is not None and delivered.message_id == "7"
    acked = repo.transition("a1", "acked", now=NOW, acked_at=NOW)
    assert acked is not None and acked.status == "acked"
    assert repo.has_non_terminal("u1") is False


def test_state_machine_rejects_illegal_jump(db_session_factory):
    repo.enqueue(_action())
    assert repo.transition("a1", "acked", now=NOW) is None
    assert repo.transition("a1", "expired", now=NOW) is None


def test_get_active_skips_retrying_failed_until_due(db_session_factory):
    repo.enqueue(_action())
    repo.transition("a1", "approved", now=NOW)
    repo.transition(
        "a1",
        "failed",
        now=NOW,
        attempt=1,
        next_retry_at=NOW + timedelta(minutes=1),
    )
    assert repo.get_active("u1", now=NOW) is None
    due = repo.get_active("u1", now=NOW + timedelta(minutes=2))
    assert due is not None and due.status == "failed" and due.attempt == 1


def test_list_pending_and_lazy_expiry(db_session_factory):
    repo.enqueue(_action())
    repo.transition("a1", "approved", now=NOW)
    repo.transition("a1", "delivered", now=NOW, delivered_at=NOW, message_id="7")
    assert [a.id for a in repo.list_pending("u1", now=NOW)] == ["a1"]

    repo.enqueue(_action(id="a2", dedupe_key="k2"))
    repo.transition("a2", "discarded", now=NOW)
    repo.enqueue(_action(id="a3", dedupe_key="k3"))
    repo.transition("a3", "approved", now=NOW)
    repo.transition("a3", "delivered", now=NOW, delivered_at=NOW, message_id="8")
    repo.transition("a3", "acked", now=NOW, acked_at=NOW)
    assert [a.id for a in repo.list_pending("u1", now=NOW)] == ["a1"]

    late = NOW + timedelta(hours=25)
    assert repo.list_pending("u1", now=late) == []
    assert repo.get_by_id("a1").status == "expired"


def test_aggregate_episode_counts_delivered_in_window(db_session_factory):
    repo.enqueue(_action())
    repo.transition("a1", "approved", now=NOW)
    repo.transition("a1", "delivered", now=NOW, delivered_at=NOW, message_id="7")

    episode_start = NOW - timedelta(hours=1)
    last, count = repo.aggregate_episode("u1", episode_start)
    assert last == NOW
    assert count == 1

    old_start = NOW + timedelta(minutes=1)
    _, count_after = repo.aggregate_episode("u1", old_start)
    assert count_after == 0


def test_reset_on_user_message_acks_pending(db_session_factory):
    repo.enqueue(_action())
    repo.transition("a1", "approved", now=NOW)
    repo.transition("a1", "delivered", now=NOW, delivered_at=NOW, message_id="7")

    repo.reset_on_user_message("u1", now=NOW)

    assert repo.get_by_id("a1").status == "acked"
    assert repo.get_by_id("a1").acked_at == NOW
    assert repo.list_pending("u1", now=NOW) == []


def test_reset_on_user_message_discards_candidate(db_session_factory):
    repo.enqueue(_action())
    repo.reset_on_user_message("u1", now=NOW)

    assert repo.get_by_id("a1").status == "discarded"
    assert repo.has_non_terminal("u1") is False
