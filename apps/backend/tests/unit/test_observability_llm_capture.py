import time
from datetime import datetime

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.models.observability import CallSite
from app.services.observability.llm_capture import (
    UsageCallbackHandler,
    build_llm_record,
)


def _result_with_usage_metadata(input_tokens=10, output_tokens=5):
    message = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return ChatResult(generations=[ChatGeneration(message=message)])


def test_handler_accumulates_usage_metadata():
    handler = UsageCallbackHandler()
    handler.on_llm_end(_result_with_usage_metadata(10, 5))
    handler.on_llm_end(_result_with_usage_metadata(7, 3))
    assert handler.calls == 2
    assert (handler.input_tokens, handler.output_tokens) == (17, 8)


def test_handler_reads_llm_output_token_usage():
    handler = UsageCallbackHandler()
    result = ChatResult(
        generations=[ChatGeneration(message=AIMessage(content="ok"))],
        llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    )
    handler.on_llm_end(result)
    assert (handler.input_tokens, handler.output_tokens) == (7, 3)


def test_handler_tolerates_missing_usage_and_errors():
    handler = UsageCallbackHandler()
    handler.on_llm_end(ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))]))
    assert handler.input_tokens is None
    assert handler.output_tokens is None
    handler.on_llm_error(RuntimeError("boom"))
    assert handler.errors == 1
    assert handler.calls == 1


class _FakeModel:
    model_name = "fake-model"


def test_build_llm_record_ok():
    handler = UsageCallbackHandler()
    handler.on_llm_end(_result_with_usage_metadata(100, 30))
    started = time.perf_counter() - 0.01
    record = build_llm_record(
        CallSite.ANSWER,
        _FakeModel(),
        handler,
        started,
        datetime.now(),
        ttft_ms=12.345,
        request_id="req-1",
    )
    assert record.call_site is CallSite.ANSWER
    assert record.model == "fake-model"
    assert record.status == "ok"
    assert record.latency_ms >= 10
    assert record.ttft_ms == 12.35
    assert (record.input_tokens, record.output_tokens) == (100, 30)
    assert record.request_id == "req-1"


def test_build_llm_record_error_without_usage():
    started = time.perf_counter()
    record = build_llm_record(
        CallSite.JUDGE,
        _FakeModel(),
        None,
        started,
        datetime.now(),
        status="error",
        error_kind="RuntimeError",
    )
    assert record.status == "error"
    assert record.error_kind == "RuntimeError"
    assert record.input_tokens is None
    assert record.cost_estimate is None
