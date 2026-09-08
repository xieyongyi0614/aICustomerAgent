"""v1 遗留 relationship_event 记忆迁移（REL-001）。

类型归一：relationship_event → relationship_fact（LEGACY_TYPE_ALIASES 既有映射，
检索两侧 affinity 别名一致，检索语义不变）。默认 dry-run 出报告；apply 分批
UPDATE 且幂等（条件命中，重跑零行）。迁移只动 type 列：不回填伪造 source_ref、
不自动双写；memory_replay 回放源枯竭是叙事/数值解耦的预期结果（报告显式输出）。
"""

import logging
from datetime import datetime

from app.core.db import Memory, SessionLocal
from app.services.memory2.types import LEGACY_TYPE_ALIASES
from app.services import memory_service
from app.services.memory2 import retriever

logger = logging.getLogger(__name__)

LEGACY_TYPE = "relationship_event"
TARGET_TYPE = LEGACY_TYPE_ALIASES[LEGACY_TYPE]
BATCH_SIZE = 500


def collect_report() -> dict:
    with SessionLocal() as session:
        rows = (
            session.query(Memory.user_id, Memory.created_at, Memory.source_ref)
            .filter(Memory.type == LEGACY_TYPE)
            .all()
        )
    per_user: dict[str, int] = {}
    without_source_ref = 0
    for user_id, created_at, source_ref in rows:
        per_user[user_id] = per_user.get(user_id, 0) + 1
        if not source_ref:
            without_source_ref += 1
    created = [created_at for _, created_at, _ in rows if created_at is not None]
    return {
        "legacy_type": LEGACY_TYPE,
        "target_type": TARGET_TYPE,
        "pending_rows": len(rows),
        "per_user": per_user,
        "created_at_min": min(created).isoformat() if created else None,
        "created_at_max": max(created).isoformat() if created else None,
        "without_source_ref": without_source_ref,
        "replay_source_rows": len(rows),
    }


def _verify() -> dict:
    return {
        "remaining_rows": collect_report()["pending_rows"],
        "alias_mapping_ok": LEGACY_TYPE_ALIASES.get(LEGACY_TYPE) == TARGET_TYPE,
        "retriever_alias_ok": (
            retriever._AFFINITY_TYPE_ALIASES.get(LEGACY_TYPE) == TARGET_TYPE
        ),
        "v1_affinity_ok": LEGACY_TYPE in memory_service.TYPE_AFFINITY_KEYWORDS,
    }


def apply_migration(batch_size: int = BATCH_SIZE) -> dict:
    report = collect_report()
    migrated = 0
    while True:
        with SessionLocal() as session:
            rows = (
                session.query(Memory)
                .filter(Memory.type == LEGACY_TYPE)
                .limit(batch_size)
                .all()
            )
            if not rows:
                break
            for row in rows:
                row.type = TARGET_TYPE
            session.commit()
            migrated += len(rows)
    logger.info("relationship_event 记忆迁移完成：%s 行", migrated)
    return {
        "mode": "apply",
        "migrated": migrated,
        **report,
        "verification": _verify(),
    }
