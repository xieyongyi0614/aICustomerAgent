from datetime import datetime, timedelta

from app.models.observability import CallSite, LlmCallRecord
from app.repositories import llm_call_repository


def make_record(
    record_id="rec-1",
    request_id="req-1",
    turn_id="101",
    call_site=CallSite.ANSWER,
    status="ok",
    input_tokens=100,
    output_tokens=30,
) -> LlmCallRecord:
    return LlmCallRecord(
        id=record_id,
        request_id=request_id,
        turn_id=turn_id,
        call_site=call_site,
        model="fake",
        provider="example.invalid",
        status=status,
        latency_ms=123.4,
        ttft_ms=12.5 if call_site is CallSite.ANSWER else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_kind=None if status == "ok" else "RuntimeError",
        started_at=datetime.now(),
    )


def test_save_and_get_roundtrip(db_session_factory):
    llm_call_repository.save(make_record())
    by_request = llm_call_repository.get_by_request("req-1")
    assert len(by_request) == 1
    record = by_request[0]
    assert record.call_site is CallSite.ANSWER
    assert record.model == "fake"
    assert record.provider == "example.invalid"
    assert record.latency_ms == 123.4
    assert record.ttft_ms == 12.5
    assert (record.input_tokens, record.output_tokens) == (100, 30)
    by_turn = llm_call_repository.get_by_turn("101")
    assert len(by_turn) == 1


def test_save_finalizes_cost_from_settings(db_session_factory, override_settings):
    override_settings(
        observability_llm_cost_json='{"fake": {"input_per_mtok": 1.0, "output_per_mtok": 3.0}}'
    )
    llm_call_repository.save(make_record(input_tokens=1_000_000, output_tokens=1_000_000))
    record = llm_call_repository.get_by_request("req-1")[0]
    assert record.cost_estimate is not None
    assert abs(record.cost_estimate - 4.0) < 1e-6


def test_save_keeps_missing_usage_without_cost(db_session_factory):
    llm_call_repository.save(make_record(input_tokens=None, output_tokens=None))
    record = llm_call_repository.get_by_request("req-1")[0]
    assert record.input_tokens is None
    assert record.cost_estimate is None


def test_search_filters(db_session_factory):
    llm_call_repository.save(make_record(record_id="r1", call_site=CallSite.ANSWER))
    llm_call_repository.save(
        make_record(record_id="r2", request_id="req-2", turn_id="102", call_site=CallSite.JUDGE, status="error")
    )
    assert len(llm_call_repository.search(request_id="req-2")) == 1
    assert len(llm_call_repository.search(turn_id="102")) == 1
    assert len(llm_call_repository.search(call_site="judge")) == 1
    assert len(llm_call_repository.search(model="fake")) == 2
    assert len(llm_call_repository.search(since=datetime.now() + timedelta(hours=1))) == 0
    assert len(llm_call_repository.search()) == 2


def test_prune_before(db_session_factory):
    llm_call_repository.save(make_record(record_id="old"))
    assert llm_call_repository.prune_before(datetime.now() + timedelta(days=1)) >= 1
    assert llm_call_repository.get_by_request("req-1") == []
