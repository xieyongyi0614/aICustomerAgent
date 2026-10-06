"""V7.8 debug metrics 端点：种子数据聚合与空窗口零值结构。"""

from datetime import datetime

from httpx import ASGITransport, AsyncClient
import pytest

from app.core import timeutil
from app.main import app
from app.models.autonomy import ProactiveAction
from app.models.evaluation import (
    DimensionScore,
    EvaluationDimension,
    EvaluationReport,
    EvaluationSubjectKind,
)
from app.repositories import (
    conversation_repository,
    evaluation_repository,
    llm_call_repository,
    proactive_repository,
    trace_repository,
)
from app.models.observability import CallSite, LlmCallRecord, RuntimeTrace, TraceKind, TraceStep


def _seed():
    trace_repository.save(
        RuntimeTrace(
            trace_id="m-req-1",
            kind=TraceKind.TURN,
            user_id="default-user",
            conversation_id="s-metrics",
            turn_id="9001",
            status="complete",
            duration_ms=123.4,
            steps=[TraceStep(name="llm", duration_ms=88.0)],
        )
    )
    llm_call_repository.save(
        LlmCallRecord(
            request_id="m-req-1",
            turn_id="9001",
            call_site=CallSite.ANSWER,
            model="fake",
            status="ok",
            latency_ms=90.0,
            input_tokens=120,
            output_tokens=30,
        )
    )
    evaluation_repository.save(
        EvaluationReport(
            id="m-report-1",
            subject=EvaluationSubjectKind.TURN,
            subject_id="9001",
            user_id="default-user",
            scores={
                EvaluationDimension.PERSONA: DimensionScore(
                    dimension=EvaluationDimension.PERSONA, score=0.7
                )
            },
            verdict="warn",
            created_at=timeutil.now(),
        )
    )
    conversation_repository.get_or_create_conversation("s-metrics", "default-user")
    conversation_repository.save_message("s-metrics", "human", "hi")
    conversation_repository.save_message("s-metrics", "ai", "hello")
    now = timeutil.now()
    proactive_repository.enqueue(
        ProactiveAction(
            id="m-action-1",
            user_id="default-user",
            session_id="s-metrics",
            trigger_type="conversation_inactivity",
            dedupe_key="m-dedupe-1",
            intention="check_in",
            reason="r",
            created_at=now,
            updated_at=now,
        )
    )


@pytest.mark.asyncio
async def test_debug_metrics_endpoint(db_session_factory):
    _seed()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/debug/metrics", params={"window_hours": 24})
        assert resp.status_code == 200
        body = resp.json()
        assert body["window_hours"] == 24
        assert body["pipeline"]["turn_count"] == 1
        assert body["pipeline"]["steps"]["llm"]["count"] == 1
        assert body["llm"]["calls"] == 1
        assert body["llm"]["by_call_site"]["answer"]["input_tokens"] == 120
        assert body["quality"]["reports"] == 1
        assert body["quality"]["verdict_distribution"] == {"warn": 1}
        assert body["quality"]["dimension_mean"]["persona"] == 0.7
        assert body["business"]["message_count"] == 2
        assert body["business"]["conversation_count"] == 1
        assert body["business"]["proactive"]["delivered"] == 0


@pytest.mark.asyncio
async def test_debug_metrics_empty_window_zeroed(db_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/debug/metrics", params={"window_hours": 0.000001})
        assert resp.status_code == 200
        body = resp.json()
        assert body["pipeline"]["turn_count"] == 0
        assert body["llm"]["calls"] == 0
        assert body["quality"]["reports"] == 0
        assert body["business"]["response_success_rate"] is None
