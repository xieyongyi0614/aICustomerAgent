"""Agent State Archiver（V2.1.0 AGENT-002）：Snapshot 时点存档策略。

显著变化（榜首/mood/关系阶段/活跃目标集）∧ 距上次 ≥ 最小间隔 → 存档；
每日保底 1 行；组件值不变则沿用版本号，否则递增；顺带清理保留期外旧行。
存档失败不阻塞 Run（调用方容错）。
"""

import logging
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.agent_state import AgentStateSnapshot
from app.repositories import agent_state_snapshot_repository as snapshot_repo

logger = logging.getLogger(__name__)

_SIGNIFICANT_FIELDS = ("interest_focus", "mood", "relationship")


def archive_if_significant(
    user_id: str,
    character_id: str,
    snapshot: AgentStateSnapshot,
    run_id: str | None = None,
    now: datetime | None = None,
) -> bool:
    settings = get_settings()
    now = now or datetime.now()
    last = snapshot_repo.latest(user_id, character_id)
    if last is not None and not _interval_ok(last.created_at, now, settings):
        return False
    changed = last is None or _content_changed(last, snapshot)
    fallback_due = last is None or last.created_at.date() < now.date()
    if not changed and not fallback_due:
        return False
    if changed:
        version = (last.version if last is not None else 0) + 1
    else:
        version = last.version
    snapshot_repo.save(
        user_id,
        snapshot=snapshot.model_dump(mode="json"),
        version=version,
        run_id=run_id,
        character_id=character_id,
        now=now,
    )
    try:
        snapshot_repo.cleanup_expired(settings.state_snapshot_retention_days, now)
    except Exception:
        logger.exception("快照保留期清理失败，已忽略")
    return True


def _interval_ok(last_created: datetime, now: datetime, settings) -> bool:
    min_interval = max(settings.state_snapshot_min_interval_minutes, 0)
    return (now - last_created).total_seconds() >= min_interval * 60


def _content_changed(last_row, snapshot: AgentStateSnapshot) -> bool:
    last = last_row.snapshot or {}
    current = snapshot.model_dump(mode="json")
    for field in _SIGNIFICANT_FIELDS:
        if last.get(field) != current.get(field):
            return True
    last_goal = (last.get("current_focus") or {}).get("goal_id")
    current_goal = (current.get("current_focus") or {}).get("goal_id")
    return last_goal != current_goal
