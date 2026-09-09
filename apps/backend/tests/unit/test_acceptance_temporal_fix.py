"""Acceptance Fix（时间上下文与场景生命周期）单元测试。

覆盖：记忆时间锚点标注、过期事件记忆沉淀、场景段时间锚点。
"""

from datetime import datetime, timedelta

from app.models.memory import UserMemory
from app.models.world import EventImportance, EventSource, EventStatus, WorldEvent
from app.prompts.scene import build_scene_section
from app.services.context_builder import _relative_time_label, _with_time_anchor
from app.services.world.memory_bridge import to_memory_candidates


def _memory(content, created_at, last_accessed_at=None):
    return UserMemory(
        id="m1",
        user_id="u1",
        character_id="asuna",
        type="important_event",
        content=content,
        importance=0.6,
        status="active",
        created_at=created_at,
        updated_at=created_at,
        last_accessed_at=last_accessed_at,
    )


def test_relative_time_label_buckets():
    now = datetime(2026, 9, 9, 12, 0)
    assert _relative_time_label(now - timedelta(minutes=30), now) is None
    assert _relative_time_label(now - timedelta(hours=5), now) == "5小时前"
    assert _relative_time_label(now - timedelta(hours=30), now) == "昨天"
    assert _relative_time_label(now - timedelta(days=10), now) == "10天前"


def test_time_anchor_appended_and_fresh_memories_untouched():
    now = datetime.now()
    fresh = _memory("用户喜欢西瓜", now - timedelta(minutes=10))
    assert _with_time_anchor(fresh, now).content == "用户喜欢西瓜"
    old = _memory("用户喜欢西瓜", now - timedelta(days=3))
    assert _with_time_anchor(old, now).content == "用户喜欢西瓜（3天前）"


def test_expired_event_materializes_unfinished_memory():
    started = datetime(2026, 9, 8, 19, 0)
    event = WorldEvent(
        id="evt_e1",
        world_id="home:default-user",
        type="cooking",
        title="煮面",
        importance=EventImportance.NORMAL,
        status=EventStatus.EXPIRED,
        started_at=started,
        source=EventSource.USER_MENTION,
    )
    candidates = to_memory_candidates(event)
    assert len(candidates) == 1
    assert "没有完成" in candidates[0]["content"] and "已过期" in candidates[0]["content"]
    assert "09月08日" in candidates[0]["content"]
    assert candidates[0]["importance"] <= 0.5


def test_completed_event_content_unchanged():
    event = WorldEvent(
        id="evt_c1",
        world_id="home:default-user",
        type="interview",
        title="用户的面试",
        importance=EventImportance.NORMAL,
        status=EventStatus.COMPLETED,
        completed_at=datetime(2026, 9, 2, 15, 0),
        source=EventSource.USER_MENTION,
    )
    candidates = to_memory_candidates(event)
    assert candidates[0]["content"] == "用户在09月02日完成了用户的面试"


def test_scene_section_includes_time_anchor_when_known():
    from app.models.scene import PendingAction, SceneState

    state = SceneState(
        session_id="s1",
        location="厨房",
        current_activity="煮面",
        pending_action=PendingAction(action="煮面", created_at_turn=1),
        last_active_at=datetime(2026, 9, 8, 19, 0),
    )
    section = build_scene_section(state)
    assert "现在时间：" in section
    assert "本场景开始于2026-09-08 19:00" in section


def test_scene_section_without_last_active_at_has_no_time_line():
    from app.models.scene import PendingAction, SceneState

    state = SceneState(
        session_id="s1",
        location="厨房",
        pending_action=PendingAction(action="煮面", created_at_turn=1),
    )
    section = build_scene_section(state)
    assert "现在时间：" not in section