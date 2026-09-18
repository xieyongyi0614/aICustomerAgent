"""LIFE-001 持久化 Trigger Registry 测试。

覆盖：状态机全迁移路径、trigger_key 幂等、kill -9 演练（E-LIFE-01）、
三类信号 Flag ON/OFF 双通道、recover_stale 对账、fail_for_retry 死信。
"""

from datetime import datetime, timedelta

import pytest

from app.repositories import trigger_registry_repository as repo
from app.services import trigger_evaluator

NOW = datetime(2026, 9, 7, 12, 0, 0)


@pytest.fixture()
def life_loop_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings()
    yield
    trigger_evaluator._followup_registry.clear()


def _make_signal_tail(last_user_message_id="m1"):
    return trigger_evaluator.SessionTail(
        last_message_at=NOW - timedelta(minutes=45),
        last_message_role="human",
        last_user_message_at=NOW - timedelta(minutes=45),
        last_user_message_id=last_user_message_id,
    )


class TestStateMachine:
    def test_register_creates_pending_and_dedupes(self):
        status = repo.register(
            "u1", "scheduled_followup", "followup:u1:面试:2026-09-07",
            due_at=NOW + timedelta(hours=2), payload={"summary": "面试"}, now=NOW,
        )
        assert status == "pending"
        row = repo.get("followup:u1:面试:2026-09-07")
        assert row is not None and row.priority == 2

        status2 = repo.register(
            "u1", "scheduled_followup", "followup:u1:面试:2026-09-07",
            due_at=NOW + timedelta(hours=2), payload={"summary": "面试"}, now=NOW,
        )
        assert status2 == "pending"
        assert len(repo.list_recent("u1")) == 1

    def test_claim_mark_fired_complete_happy_path(self):
        key = "followup:u1:考试:2026-09-07"
        repo.register("u1", "scheduled_followup", key, due_at=NOW, now=NOW)
        claimed = repo.claim_due_followups("u1", now=NOW)
        assert [r.trigger_key for r in claimed] == [key]
        assert claimed[0].status == "due"
        assert repo.mark_fired(key, now=NOW) is True
        assert repo.complete(key, now=NOW) is True
        assert repo.get(key).status == "done"

    def test_claim_not_due_returns_empty(self):
        repo.register(
            "u1", "scheduled_followup", "k1", due_at=NOW + timedelta(hours=1), now=NOW
        )
        assert repo.claim_due_followups("u1", now=NOW) == []

    def test_complete_idempotent_and_pending_untouched(self):
        repo.register("u1", "scheduled_followup", "k2", due_at=NOW, now=NOW)
        assert repo.complete("k2", now=NOW) is False
        assert repo.get("k2").status == "pending"
        repo.claim_due_followups("u1", now=NOW)
        assert repo.complete("k2", now=NOW) is True
        assert repo.complete("k2", now=NOW) is False

    def test_fail_for_retry_backoff_and_dead_letter(self):
        key = "action_due:e1"
        repo.register("u1", "action_due", key, due_at=NOW, now=NOW)
        repo.register_and_claim("u1", "action_due", key, due_at=NOW, now=NOW)
        repo.mark_fired(key, now=NOW)
        status = repo.fail_for_retry(
            key, reason="boom", now=NOW, max_attempts=3, backoff_seconds=300
        )
        assert status == "pending"
        row = repo.get(key)
        assert row.attempt_count == 1
        assert row.cooldown_until == NOW + timedelta(seconds=300)

        later = NOW + timedelta(seconds=600)
        repo.register_and_claim("u1", "action_due", key, due_at=later, now=later)
        repo.mark_fired(key, now=later)
        status = repo.fail_for_retry(
            key, reason="boom", now=later, max_attempts=3, backoff_seconds=300
        )
        assert status == "pending"

        latest = NOW + timedelta(seconds=1200)
        repo.register_and_claim(
            "u1", "action_due", key, due_at=latest, now=latest
        )
        repo.mark_fired(key, now=latest)
        status = repo.fail_for_retry(
            key, reason="boom", now=latest, max_attempts=3, backoff_seconds=300
        )
        assert status == "cancelled"
        assert repo.get(key).status == "cancelled"

    def test_cancel_only_active(self):
        repo.register("u1", "action_due", "action_due:e2", due_at=NOW, now=NOW)
        assert repo.cancel("action_due:e2", reason="stale", now=NOW) is True
        assert repo.cancel("action_due:e2", reason="again", now=NOW) is False


class TestRegisterAndClaim:
    def test_first_detection_creates_and_claims(self):
        row = repo.register_and_claim(
            "u1", "conversation_inactivity", "inactivity:u1:m1",
            due_at=NOW, payload={"idle_minutes": 45.0}, now=NOW,
        )
        assert row is not None and row.status == "due"

    def test_previous_handoff_reclaimed_single_row(self):
        key = "inactivity:u1:m1"
        repo.register_and_claim("u1", "conversation_inactivity", key, due_at=NOW, now=NOW)
        row = repo.register_and_claim(
            "u1", "conversation_inactivity", key, due_at=NOW, now=NOW
        )
        assert row is not None and row.status == "due"
        rows = [r for r in repo.list_recent("u1") if r.trigger_key == key]
        assert len(rows) == 1

    def test_terminal_row_revived(self):
        key = "action_due:e9"
        repo.register("u1", "action_due", key, due_at=NOW, now=NOW)
        repo.cancel(key, reason="stale", now=NOW)
        row = repo.register_and_claim("u1", "action_due", key, due_at=NOW, now=NOW)
        assert row is not None and row.status == "due"

    def test_cooldown_pending_not_claimable(self, db_session_factory):
        from app.core.db import TriggerRegistryRow

        key = "action_due:e10"
        repo.register("u1", "action_due", key, due_at=NOW, now=NOW)
        with db_session_factory() as session:
            session.query(TriggerRegistryRow).filter(
                TriggerRegistryRow.trigger_key == key
            ).update({"cooldown_until": NOW + timedelta(minutes=10)})
            session.commit()
        assert (
            repo.register_and_claim("u1", "action_due", key, due_at=NOW, now=NOW)
            is None
        )


class TestRecoverStale:
    def test_stuck_due_row_recovered_with_backoff(self):
        key = "action_due:e3"
        repo.register("u1", "action_due", key, due_at=NOW, now=NOW)
        repo.register_and_claim("u1", "action_due", key, due_at=NOW, now=NOW)
        stale_now = NOW + timedelta(seconds=700)
        recovered = repo.recover_stale(
            now=stale_now, timeout_seconds=600, max_attempts=3, backoff_seconds=300
        )
        assert recovered == 1
        row = repo.get(key)
        assert row.status == "pending"
        assert row.attempt_count == 1
        assert row.last_error == "stale_recovered"

    def test_fresh_due_row_untouched(self):
        repo.register("u1", "action_due", "action_due:e4", due_at=NOW, now=NOW)
        repo.register_and_claim("u1", "action_due", "action_due:e4", due_at=NOW, now=NOW)
        assert repo.recover_stale(now=NOW, timeout_seconds=600) == 0

    def test_max_attempts_dead_letter_via_recover(self):
        key = "action_due:e5"
        repo.register("u1", "action_due", key, due_at=NOW, now=NOW)
        for i in range(1, 4):
            tick = NOW + timedelta(seconds=1300 * i)
            repo.register_and_claim("u1", "action_due", key, due_at=tick, now=tick)
            repo.mark_fired(key, now=tick)
            repo.recover_stale(
                now=tick + timedelta(seconds=700),
                timeout_seconds=600, max_attempts=3, backoff_seconds=300,
            )
        assert repo.get(key).status == "cancelled"


class TestHasDue:
    def test_pending_due_visible_and_inactivity_excludable(self):
        repo.register(
            "u1", "scheduled_followup", "followup:u1:体检:2026-09-07",
            due_at=NOW, payload={"summary": "体检"}, now=NOW,
        )
        repo.register(
            "u1", "conversation_inactivity", "inactivity:u1:m1", due_at=NOW, now=NOW
        )
        assert repo.has_due(user_id="u1", now=NOW) is True
        assert (
            repo.has_due(
                user_id="u1", now=NOW,
                include_types=("scheduled_followup", "action_due"),
            )
            is True
        )
        assert repo.has_due(user_id="u2", now=NOW) is False


class TestTriggerEvaluatorFlagOn:
    def test_followup_registered_to_table_and_polled_once(self, life_loop_on):
        due = NOW - timedelta(minutes=5)
        trigger_evaluator.register_followup("u1", due, "下午面试")

        signal = trigger_evaluator.poll_due_followup("u1", NOW)
        assert signal is not None
        assert signal.type == "scheduled_followup"
        assert signal.context["summary"] == "下午面试"
        assert signal.dedupe_key.startswith("followup:u1:")

        assert trigger_evaluator.poll_due_followup("u1", NOW) is None
        assert repo.get(signal.dedupe_key).status == "done"

    def test_followup_pending_survives_restart(self, life_loop_on):
        future = NOW + timedelta(hours=3)
        trigger_evaluator.register_followup("u1", future, "明天答辩")
        key = f"followup:u1:明天答辩:{future.date().isoformat()}"
        assert repo.get(key).status == "pending"
        assert trigger_evaluator.poll_due_followup("u1", NOW) is None

        later = NOW + timedelta(hours=4)
        signal = trigger_evaluator.poll_due_followup("u1", later)
        assert signal is not None
        assert repo.get(key).status == "done"

    def test_inactivity_registered_and_claimed(self, life_loop_on):
        tail = _make_signal_tail()
        signal = trigger_evaluator.evaluate_inactivity(tail, "u1", now=NOW)
        assert signal is not None
        row = repo.get(signal.dedupe_key)
        assert row is not None and row.status == "due"

        second = trigger_evaluator.evaluate_inactivity(tail, "u1", now=NOW)
        assert second is not None
        rows = [r for r in repo.list_recent("u1") if r.trigger_key == signal.dedupe_key]
        assert len(rows) == 1

    def test_action_due_registered_and_completed_on_report(
        self, life_loop_on, override_settings
    ):
        from app.application import world_engine
        from app.models.world import EventStatus
        from app.repositories import world_repository

        override_settings(action_enabled=True, world_enabled=True)
        world_engine.ensure_world("u1")
        event = world_engine.create_event(
            "u1", "reminder", title="复查", due_at=NOW - timedelta(minutes=1),
        )
        event.status = EventStatus.ACTIVE
        world_repository.save_event(event)

        signal = trigger_evaluator.poll_due_actions("u1", NOW)
        assert signal is not None
        row = repo.get(signal.dedupe_key)
        assert row is not None and row.status == "due"

        trigger_evaluator.mark_action_reported("u1", signal.context["event_id"])
        assert repo.get(signal.dedupe_key).status == "done"
        assert trigger_evaluator.poll_due_actions("u1", NOW) is None

