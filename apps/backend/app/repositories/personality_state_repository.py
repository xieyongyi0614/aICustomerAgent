"""personality_state 仓储（AGENT-002）：种子幂等 + 只读；唯一写面为种子。

AGENT-005 接管后新增编译写入；本阶段除种子外任何写路径不存在。
"""

import logging
from datetime import datetime

from app.core import timeutil
from app.core import ids
from app.core.db import PersonalityStateRow, SessionLocal

logger = logging.getLogger(__name__)


def get_all(user_id: str, character_id: str = "asuna") -> list[PersonalityStateRow]:
    with SessionLocal() as session:
        return (
            session.query(PersonalityStateRow)
            .filter(
                PersonalityStateRow.user_id == user_id,
                PersonalityStateRow.character_id == character_id,
            )
            .order_by(PersonalityStateRow.axis.asc())
            .all()
        )


def seed_if_absent(
    user_id: str, axes: dict[str, dict[str, float]], character_id: str = "asuna"
) -> bool:
    """按（user, character, axis）幂等播种：existing 跳过；baseline/bound 物化。"""
    existing = {row.axis for row in get_all(user_id, character_id)}
    missing = [axis for axis in axes if axis not in existing]
    if not missing:
        return False
    now = timeutil.now()
    with SessionLocal() as session:
        for axis in missing:
            spec = axes[axis]
            baseline = float(spec["baseline"])
            bound = float(spec["bound"])
            session.add(
                PersonalityStateRow(
                    id=ids.new_id_str(),
                    user_id=user_id,
                    character_id=character_id,
                    axis=axis,
                    baseline=baseline,
                    current=baseline,
                    bound_min=round(max(0.0, baseline - bound), 6),
                    bound_max=round(min(1.0, baseline + bound), 6),
                    version=1,
                    created_at=now,
                )
            )
        session.commit()
    logger.info(
        "personality_state 播种：%s/%s axes=%s", user_id, character_id, missing
    )
    return True


def get_all_or_seed(
    user_id: str, axes: dict[str, dict[str, float]], character_id: str = "asuna"
) -> list[PersonalityStateRow]:
    seed_if_absent(user_id, axes, character_id)
    return get_all(user_id, character_id)
