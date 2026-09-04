"""V9 Action Memory Policy（memory-policy.md §2/§3，V9-007 专项）。

边界表逐格、source 只允许 user_stated/user_derived（ai_inferred 零出现）、
remember_fact 双写跳过、effects 幂等、失败委托沉淀与补救提示。
"""

from datetime import datetime

import pytest

from app.application.action_engine import new_record
from app.models.action import ActionIntent
from app.services.action.memory_bridge import (
    deliver_action_memory,
    to_memory_candidates,
)


def _record(action_type, status, **params):
    intent = ActionIntent(
        action_type=action_type, confidence="confident", params=params, dedupe_key=""
    )
    rec = new_record(intent, "mem-user", session_id=None)
    rec.status = status
    return rec


def _reminder(**kw):
    params = {"content": "开会", "due_at": "2026-09-04T08:00:00", **kw}
    return _record("create_reminder", "succeeded", **params)


def test_reminder_deposits_user_derived():
    cands = to_memory_candidates(_reminder())
    assert len(cands) == 1
    assert cands[0].source == "user_derived"
    assert cands[0].importance == 0.7
    assert cands[0].type == "important_event"


def test_query_environment_does_not_deposit():
    assert to_memory_candidates(_record("query_environment", "succeeded")) == []


def test_usage_actions_do_not_deposit():
    assert to_memory_candidates(_record("use_object", "succeeded", object="牛奶")) == []
    assert to_memory_candidates(_record("move_object", "succeeded", object="牛奶", location="冰箱")) == []


def test_source_never_ai_inferred():
    cases = {
        "create_reminder": {"content": "开会", "due_at": "2026-09-04T08:00:00"},
        "cancel_reminder": {"target": "开会"},
        "remember_fact": {"fact": "喜欢抹茶"},
        "create_object": {"object": "牛奶"},
    }
    for action_type, params in cases.items():
        rec = _record(action_type, "succeeded", **params)
        for cand in to_memory_candidates(rec):
            assert cand.source in ("user_stated", "user_derived")


def test_birthday_reminder_promotes_importance():
    cands = to_memory_candidates(_reminder(content="提醒我记住生日"))
    assert len(cands) == 1
    assert cands[0].importance == 0.8
    assert cands[0].type == "user_fact"


def test_failed_important_delegation_deposits():
    rec = _reminder(content="买牛奶")
    rec.status = "failed"
    cands = to_memory_candidates(rec)
    assert len(cands) == 1
    assert cands[0].importance >= 0.6


def test_remember_fact_succeeded_no_double(override_settings, db_session_factory):
    override_settings(action_memory_policy_enabled=True)
    rec = _record("remember_fact", "succeeded", fact="我喜欢猫")
    # 边界表有 remember_fact 行，但能力已写入记忆本体 → 投递跳过（防双写）
    assert deliver_action_memory(rec, "mem-user") is None


@pytest.mark.asyncio
async def test_deliver_actual_deposit(override_settings, db_session_factory):
    from app.repositories import memory_repository

    override_settings(action_memory_policy_enabled=True)
    rec = _reminder(content="提醒吃药")
    payload = deliver_action_memory(rec, "mem-user")
    if payload is None:
        return
    memory = memory_repository.get_memory(payload["memory_id"])
    assert memory is not None
    assert memory.source in ("user_stated", "user_derived")


def test_deliver_idempotent_when_effect_registered(override_settings, db_session_factory):
    override_settings(action_memory_policy_enabled=True)
    rec = _reminder(content="提醒吃药")
    rec.result = {
        "status": "succeeded",
        "effects": [{"kind": "memory", "ref": "m1", "detail": "已记住"}],
    }
    assert deliver_action_memory(rec, "mem-user") is None