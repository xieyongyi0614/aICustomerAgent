"""关系账本重放对账（REL-004 / E-REL-03，恒只读）。

快照锚点 + 账本重放重建 vs 当前 state：偏差分「可解释/不可解释」两栏。
可解释 = comfort（逐轮漂移不走账本）或与锚点后里程碑 bonus 吻合（bonus
直接入 state 不走账本）；不可解释非空即不一致。V8.5 数学零改动证明由
tests/v8.5/test_relationship_replay.py 与本报告共同承担。
"""

import logging
from datetime import datetime

from app.core.constants import RELATIONSHIP_DIMENSIONS_V85
from app.models.relationship import RelationshipState
from app.repositories import (
    relationship_event_repository,
    relationship_milestone_repository,
    relationship_repository,
    relationship_snapshot_repository,
)
from app.engines import relationship_evolution

logger = logging.getLogger(__name__)

_TOLERANCE = 1e-6
_EVENT_LIMIT = 2000


def replay_report(user_id: str) -> dict:
    """重放对账报告；无快照锚点时返回 consistent=None（跳过）。"""
    snapshots = relationship_snapshot_repository.list_snapshots(user_id, limit=1)
    if not snapshots:
        return {
            "user_id": user_id,
            "consistent": None,
            "note": "无快照锚点，跳过重放",
        }
    anchor = snapshots[0]
    current = relationship_repository.get_relationship(user_id)
    events = relationship_event_repository.list_events(user_id, limit=_EVENT_LIMIT)
    replayable = [event for event in events if event.created_at > anchor.created_at]
    base = RelationshipState(
        intimacy=anchor.dimensions.get("intimacy", current.intimacy),
        trust=anchor.dimensions.get("trust", current.trust),
        familiarity=anchor.dimensions.get("familiarity", current.familiarity),
        respect=anchor.dimensions.get("respect", current.respect),
        comfort=anchor.dimensions.get("comfort", current.comfort),
        tension=anchor.dimensions.get("tension", current.tension),
        stage=anchor.stage,
        conflict_status=anchor.conflict_status,
        neglect_active=current.neglect_active,
        last_interaction_at=current.last_interaction_at,
        version=anchor.version,
        updated_at=current.updated_at,
    )
    rebuilt = relationship_evolution.replay(base, replayable)
    bonuses = _bonus_since(user_id, anchor.created_at)
    reconciled: list[str] = []
    explained: dict[str, dict] = {}
    unexplained: dict[str, dict] = {}
    for dim in RELATIONSHIP_DIMENSIONS_V85:
        replayed = float(getattr(rebuilt, dim))
        actual = float(getattr(current, dim))
        diff = round(actual - replayed, 6)
        if abs(diff) <= _TOLERANCE:
            reconciled.append(dim)
            continue
        bonus = round(float(bonuses.get(dim, 0.0)), 6)
        if dim == "comfort":
            explained[dim] = {"diff": diff, "reason": "comfort_drift"}
        elif abs(diff - bonus) <= _TOLERANCE:
            explained[dim] = {"diff": diff, "reason": "milestone_bonus", "bonus": bonus}
        else:
            unexplained[dim] = {"diff": diff, "bonus": bonus}
    return {
        "user_id": user_id,
        "anchor_version": anchor.version,
        "anchor_time": anchor.created_at.isoformat(),
        "events_replayed": len(replayable),
        "reconciled": reconciled,
        "explained": explained,
        "unexplained": unexplained,
        "stage": {"rebuilt": rebuilt.stage, "actual": current.stage},
        "consistent": not unexplained,
    }


def _bonus_since(user_id: str, since: datetime) -> dict[str, float]:
    totals = {dim: 0.0 for dim in RELATIONSHIP_DIMENSIONS_V85}
    for record in relationship_milestone_repository.list_milestones(user_id):
        if record.created_at <= since:
            continue
        for dim in RELATIONSHIP_DIMENSIONS_V85:
            totals[dim] += float(getattr(record.applied_bonus, dim, 0.0) or 0.0)
    return totals
