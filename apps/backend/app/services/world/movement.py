"""V2.3.0 位置变更唯一裁决（architecture.md §5.5 MovementResolver）。

用户叙事 > 日程推进；一切成功迁移落 location_change 事件（经 _emit_simulation_events 漏斗）。
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.models.world import part_of_day
from app.repositories import world_repository

logger = logging.getLogger(__name__)

SOURCE_USER_NARRATIVE = "user_narrative"
SOURCE_SCHEDULE = "schedule"


@dataclass
class MoveResult:
    applied: bool
    from_location: str | None = None
    to_location: str | None = None
    skipped_reason: str | None = None


def _latest_narrative_move(world_id: str, limit: int = 10):
    events = world_repository.list_events(
        world_id,
        statuses=["completed"],
        limit=limit,
        types=["life_event"],
        order="created_at_desc",
    )
    for event in events:
        if (event.payload or {}).get("kind") == "location_change":
            yield event


def _narrative_move_in_current_part(world_id: str, now: datetime) -> bool:
    for event in _latest_narrative_move(world_id):
        moved_at_raw = (event.payload or {}).get("moved_at")
        moved_at = event.created_at
        if isinstance(moved_at_raw, str):
            try:
                moved_at = datetime.fromisoformat(moved_at_raw)
            except ValueError:
                moved_at = event.created_at
        if event.source.value == "user_mention" and part_of_day(
            moved_at or now
        ) == part_of_day(now):
            return True
    return False


def apply(
    user_id: str,
    target_location_id: str,
    source: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> MoveResult:
    """位置迁移仲裁入口；失败只留原因，不抛错（世界旁路纪律）。

    异常分级：仓储/IO 类（SQLAlchemyError）判定为可重试，下一 tick 会自然重放；
    其余视为逻辑缺陷，日志级别更高以便定位。
    """
    from app.services.world import engine_port as world_engine

    try:
        from app.character.asuna.world import WORLD_LOCATION_REGISTRY

        if target_location_id not in WORLD_LOCATION_REGISTRY:
            logger.warning("未知地点，拒绝迁移：%s", target_location_id)
            return MoveResult(applied=False, skipped_reason="unknown_location")
        world = world_repository.ensure_world(user_id)
        if world is None:
            return MoveResult(applied=False, skipped_reason="no_world")
        if world.current_location == target_location_id:
            return MoveResult(
                applied=False,
                from_location=world.current_location,
                to_location=target_location_id,
                skipped_reason="same_location",
            )
        current_time = now or datetime.now()
        if source == SOURCE_SCHEDULE and _narrative_move_in_current_part(
            world.world_id, current_time
        ):
            return MoveResult(
                applied=False,
                from_location=world.current_location,
                to_location=target_location_id,
                skipped_reason="narrative_priority",
            )
        updated = world_engine.set_location(user_id, target_location_id)
        if updated is None:
            return MoveResult(
                applied=False,
                from_location=world.current_location,
                to_location=target_location_id,
                skipped_reason="apply_failed",
            )
        event_source = "user_mention" if source == SOURCE_USER_NARRATIVE else "daily_life"
        world_engine.create_event(
            user_id,
            event_type="life_event",
            title=f"移动到{target_location_id}",
            importance="low",
            source=event_source,
            status="completed",
            payload={
                "kind": "location_change",
                "from": world.current_location,
                "to": target_location_id,
                "move_source": source,
                "reason": reason,
                "moved_at": current_time.isoformat(),
            },
            idempotency_key=f"location:{current_time.date().isoformat()}:{part_of_day(current_time)}:{target_location_id}",
        )
        return MoveResult(
            applied=True,
            from_location=world.current_location,
            to_location=target_location_id,
        )
    except SQLAlchemyError:
        logger.warning(
            "位置迁移仓储异常（可重试，下一 tick 重放）：user=%s target=%s",
            user_id,
            target_location_id,
            exc_info=True,
        )
        return MoveResult(applied=False, skipped_reason="retryable_error")
    except Exception:
        logger.exception("位置迁移裁决失败（逻辑异常）")
        return MoveResult(applied=False, skipped_reason="error")
