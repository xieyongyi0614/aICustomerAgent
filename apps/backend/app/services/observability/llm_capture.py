"""V7.8 LLM 调用捕获（llm-observability.md §2）：观察发生在调用返回之后。

结构化链经 _ObservedChain 统一拦截（schema 名 → call_site），生成/汇总/主动链各自
补一个"返回后读取"；usage 通过 LangChain callbacks 读取，不改任何请求构造。
"""

import logging
import time
from datetime import datetime

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.llm_factory import profile_id_of, provider_of
from app.core.settings import get_settings
from app.models.observability import (
    LLM_CALL_ERROR,
    LLM_CALL_OK,
    LlmCallRecord,
    SCHEMA_CALL_SITES,
    CallSite,
)

logger = logging.getLogger(__name__)


def _extract_usage(response: LLMResult) -> tuple[int, int] | None:
    for batch in getattr(response, "generations", None) or []:
        for generation in batch if isinstance(batch, list) else [batch]:
            meta = getattr(getattr(generation, "message", None), "usage_metadata", None)
            if isinstance(meta, dict) and meta.get("input_tokens") is not None:
                return int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0)
    llm_output = getattr(response, "llm_output", None)
    token_usage = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
    if isinstance(token_usage, dict) and token_usage.get("prompt_tokens") is not None:
        return (
            int(token_usage.get("prompt_tokens") or 0),
            int(token_usage.get("completion_tokens") or 0),
        )
    return None


class UsageCallbackHandler(BaseCallbackHandler):
    """usage 只读收集：单次调用点内多次 LLM 调用（主链+降级）token 求和。"""

    def __init__(self) -> None:
        self.calls = 0
        self.errors = 0
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        self.calls += 1
        usage = _extract_usage(response)
        if usage is None:
            return
        input_tokens, output_tokens = usage
        self.input_tokens = (self.input_tokens or 0) + input_tokens
        self.output_tokens = (self.output_tokens or 0) + output_tokens

    def on_llm_error(self, error: BaseException, **kwargs) -> None:
        self.errors += 1


def _usage_of(handler: UsageCallbackHandler) -> tuple[int | None, int | None]:
    return handler.input_tokens, handler.output_tokens


def build_llm_record(
    call_site: CallSite,
    model,
    handler: UsageCallbackHandler | None,
    started_monotonic: float,
    started_at: datetime,
    status: str = LLM_CALL_OK,
    error_kind: str | None = None,
    ttft_ms: float | None = None,
    request_id: str | None = None,
    turn_id: str | None = None,
) -> LlmCallRecord:
    input_tokens, output_tokens = _usage_of(handler) if handler is not None else (None, None)
    return LlmCallRecord(
        request_id=request_id,
        turn_id=turn_id,
        call_site=call_site,
        profile_id=profile_id_of(model),
        model=getattr(model, "model_name", None) or getattr(model, "_llm_type", None),
        provider=provider_of(model),
        status=status,
        latency_ms=round((time.perf_counter() - started_monotonic) * 1000, 2),
        ttft_ms=round(ttft_ms, 2) if ttft_ms is not None else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_kind=error_kind,
        started_at=started_at,
    )


def _with_callbacks(config, handler) -> dict:
    merged = dict(config) if config else {}
    merged["callbacks"] = [*(merged.get("callbacks") or []), handler]
    return merged


class _ObservedChain:
    """结构化链观测壳：ainvoke/invoke 透传，调用前后读取 usage 与错误。"""

    def __init__(self, inner, prompt, call_site: CallSite, model) -> None:
        self._inner = inner
        self._prompt = prompt
        self._call_site = call_site
        self._model = model

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def invoke(self, input_data, config=None, **kwargs):
        return _run_observed(self, input_data, config, kwargs, sync=True)

    async def ainvoke(self, input_data, config=None, **kwargs):
        return await _run_observed(self, input_data, config, kwargs, sync=False)


async def _run_observed(observed, input_data, config, kwargs, sync: bool):
    from app.application import observability

    if not get_settings().observability_persist_enabled:
        if sync:
            return observed._inner.invoke(input_data, config=config, **kwargs)
        return await observed._inner.ainvoke(input_data, config=config, **kwargs)

    handler = UsageCallbackHandler()
    started = time.perf_counter()
    started_at = datetime.now()
    _capture_structured_prompt(observed, input_data)
    try:
        if sync:
            result = observed._inner.invoke(
                input_data, config=_with_callbacks(config, handler), **kwargs
            )
        else:
            result = await observed._inner.ainvoke(
                input_data, config=_with_callbacks(config, handler), **kwargs
            )
    except Exception as exc:
        record = build_llm_record(
            observed._call_site,
            observed._model,
            handler,
            started,
            started_at,
            status=LLM_CALL_ERROR,
            error_kind=exc.__class__.__name__,
        )
        observability.record_llm_call(record)
        raise
    record = build_llm_record(
        observed._call_site,
        observed._model,
        handler,
        started,
        started_at,
        request_id=None,
        turn_id=None,
    )
    observability.record_llm_call(record)
    return result


def _capture_structured_prompt(observed, input_data) -> None:
    from app.services.observability import prompt_capture

    try:
        if not prompt_capture.enabled():
            return
        if observed._call_site is CallSite.JUDGE:
            prompt_capture.capture_judge_snapshot(observed._call_site, observed._model)
            return
        formatted = observed._prompt.format_messages(**(input_data or {}))
        prompt_capture.capture_prompt_snapshot(observed._call_site, formatted, observed._model)
    except Exception:
        logger.exception("结构化链 prompt 快照采集失败，已忽略")


def observe_structured_chain(inner, prompt, schema, model):
    """schema 名可识别才包观测壳；未知 schema 原样透传（不为记录而记录）。"""
    call_site = SCHEMA_CALL_SITES.get(getattr(schema, "__name__", ""))
    if call_site is None:
        return inner
    return _ObservedChain(inner, prompt, call_site, model)
