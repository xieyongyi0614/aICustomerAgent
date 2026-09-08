"""V7 前端投递（action-queue.md §3）：Outbox + 轮询，ack 语义是"已展示"。"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.api.v1.schemas import ProactiveActionOut, ProactivePendingOut
from app.core.settings import get_settings
from app.repositories import decision_repository, proactive_repository

logger = logging.getLogger(__name__)

proactive_router = APIRouter()


@proactive_router.get("/proactive/pending", response_model=ProactivePendingOut)
def pending(user_id: str = Query(default=get_settings().default_user)):
    actions = proactive_repository.list_pending(user_id)
    return ProactivePendingOut(
        actions=[
            ProactiveActionOut(
                id=action.id,
                intention=action.intention,
                reason=action.reason,
                text=action.payload_text or "",
                session_id=action.session_id,
                delivered_at=action.delivered_at,
            )
            for action in actions
        ]
    )


@proactive_router.post("/proactive/{action_id}/ack")
def ack(action_id: str):
    action = proactive_repository.get_by_id(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")
    if action.status != "delivered":
        raise HTTPException(status_code=409, detail=f"action status is {action.status}")
    updated = proactive_repository.transition(
        action_id, "acked", acked_at=datetime.now()
    )
    if get_settings().observability_persist_enabled:
        try:
            decision_repository.mark_outcome(action_id, "acked")
        except Exception:
            logger.exception("决策结果回写失败：%s", action_id)
    return {"id": action_id, "status": updated.status if updated else "acked"}
