from fastapi import APIRouter, HTTPException

from app.models.evaluation import EvaluationSubjectKind
from app.repositories import evaluation_repository, trace_repository
from app.services.trace_collector import get_trace_collector

debug_router = APIRouter()


@debug_router.get("/debug/turns/{turn_id}/trace")
def get_turn_trace(turn_id: str):
    session = get_trace_collector().get(turn_id)
    if session is not None:
        return session.snapshot()
    persisted = trace_repository.get_by_turn(turn_id)
    if persisted is not None:
        return persisted.api_dict()
    raise HTTPException(status_code=404, detail="turn trace 不存在或已被清理")


@debug_router.get("/debug/traces/{trace_id}")
def get_trace_by_request_id(trace_id: str):
    persisted = trace_repository.get_by_trace_id(trace_id)
    if persisted is None:
        raise HTTPException(status_code=404, detail="runtime trace 不存在或已过期")
    return persisted.api_dict()


@debug_router.get("/debug/traces")
def list_traces(conversation_id: str, limit: int = 20):
    traces = trace_repository.list_by_conversation(conversation_id, limit=max(1, min(limit, 100)))
    return [trace.api_dict() for trace in traces]


@debug_router.get("/debug/turns/{turn_id}/evaluation")
def get_turn_evaluation(turn_id: str):
    report = evaluation_repository.get_by_subject(
        EvaluationSubjectKind.TURN.value, turn_id
    )
    if report is None:
        raise HTTPException(status_code=404, detail="评估报告不存在或已过期")
    return report.model_dump(mode="json")


@debug_router.get("/debug/proactive/{action_id}/evaluation")
def get_proactive_evaluation(action_id: str):
    report = evaluation_repository.get_by_subject(
        EvaluationSubjectKind.PROACTIVE_ACTION.value, action_id
    )
    if report is None:
        raise HTTPException(status_code=404, detail="评估报告不存在或已过期")
    return report.model_dump(mode="json")
