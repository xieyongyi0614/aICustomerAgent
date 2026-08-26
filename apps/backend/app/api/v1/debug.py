from fastapi import APIRouter, HTTPException

from app.services.trace_collector import get_trace_collector

debug_router = APIRouter()


@debug_router.get("/debug/turns/{turn_id}/trace")
def get_turn_trace(turn_id: str):
    session = get_trace_collector().get(turn_id)
    if session is None:
        raise HTTPException(status_code=404, detail="turn trace 不存在或已被清理")
    return session.snapshot()
