"""Memory 2.0 摄取源只读查询封装（MEM-002）。

仅读取 action_records / world_events / relationship_events 表投影；禁止读
relationship_state 数值（domain-boundaries §3）。各源返回的实体交由 ingest 摄取，
幂等键（source_table+source_id）天然安全，重复补扫不会重复产出候选。
"""

from app.repositories import relationship_event_repository, world_repository


def fetch_action_records(user_id: str, limit: int = 20) -> list:
    """最近终态（succeeded/failed）ActionRecord；deposit 判定由 ingest 层负责。"""
    from app.repositories import action_repository

    records = action_repository.list_records(user_id, limit=limit)
    return [r for r in records if r.status in ("succeeded", "failed")]


def fetch_completed_world_events(user_id: str, limit: int = 20) -> list:
    """最近完结 WorldEvent（status=completed）。"""
    world_id = world_repository.world_id_for(user_id)
    return world_repository.list_events(
        world_id, statuses=["completed"], limit=limit
    )


def fetch_relationship_events(user_id: str, limit: int = 50) -> list:
    """最近 RelationshipEvent（读事件表投影，不看 state 数值）。"""
    return relationship_event_repository.list_events(user_id, limit=limit)


def fetch_recent_relationship_milestones(user_id: str, limit: int = 10) -> list:
    """最近 RelationshipMilestone（读里程碑表投影，不看 state 数值）。"""
    from app.repositories import relationship_milestone_repository

    return relationship_milestone_repository.list_milestones(user_id)[:limit]