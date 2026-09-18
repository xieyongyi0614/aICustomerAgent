"""Memory 2.0 Embedding 批处理（MEM-004）。

转正记忆经 enqueue 进内存队列，双条件触发 flush（条数 ≥ v2_embedding_batch_size
或队首等待 ≥ v2_embedding_batch_window_seconds）；每批一次 embedding 端点调用，
条件回填（active 且 embedding IS NULL）单事务完成；失败退避重试 2 次后写入
background_jobs（幂等键 embedding:{memory_id}:{content_hash}），由存量 NULL 补扫
闭环恢复。embedding 不作 SoT：任何时刻可清列后由 backfill_scan 全量重建。
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime

from app.core.llm_factory import get_embedding_client
from app.core.settings import get_settings
from app.repositories import background_job_repository, memory_repository

logger = logging.getLogger(__name__)

JOB_TYPE_EMBEDDING_BACKFILL = "embedding_backfill"
EMBED_RETRY_ATTEMPTS = 3
EMBED_RETRY_BACKOFF_SECONDS = 1.0

STEP_NAME = "memory_embed"


class EmbeddingClientUnavailableError(Exception):
    pass


@dataclass
class _PendingItem:
    memory_id: str
    content: str
    enqueued_at: float


_queue: list[_PendingItem] = []
_queued_ids: set[str] = set()


def enqueue(memory_id: str, content: str) -> None:
    """转正后入队（纯内存，不阻塞前台）；重复 memory_id 忽略，凑满批量即 flush。"""
    settings = get_settings()
    if memory_id in _queued_ids:
        return
    _queued_ids.add(memory_id)
    _queue.append(_PendingItem(memory_id, content or "", time.monotonic()))
    if len(_queue) >= settings.v2_embedding_batch_size:
        _flush()


def flush_if_due(trace=None) -> int:
    """时间窗口触发：队首等待超过 v2_embedding_batch_window_seconds 时 flush。"""
    if not _queue:
        return 0
    settings = get_settings()
    first_age = time.monotonic() - _queue[0].enqueued_at
    if first_age < settings.v2_embedding_batch_window_seconds:
        return 0
    return _flush(trace=trace)


def backfill_scan(trace=None) -> int:
    """存量补扫：active 且 embedding IS NULL 的行进批处理，覆盖中断积压与重启恢复。"""
    settings = get_settings()
    rows = memory_repository.list_pending_embedding(
        limit=settings.v2_embedding_batch_size
    )
    items = [
        _PendingItem(row.id, row.content or "", time.monotonic())
        for row in rows
        if row.id not in _queued_ids
    ]
    if not items:
        return 0
    return _process(items, trace=trace)


def _flush(trace=None) -> int:
    settings = get_settings()
    items: list[_PendingItem] = []
    while _queue and len(items) < settings.v2_embedding_batch_size:
        item = _queue.pop(0)
        _queued_ids.discard(item.memory_id)
        items.append(item)
    if not items:
        return 0
    return _process(items, trace=trace)


def _truncate(content: str) -> str:
    return content[: get_settings().v2_embedding_max_input_chars]


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _job_key(item: _PendingItem) -> str:
    return f"embedding:{item.memory_id}:{_content_hash(item.content)}"


def _embed_batch(texts: list[str]) -> list[list[float]]:
    client = get_embedding_client()
    if client is None:
        raise EmbeddingClientUnavailableError("v2_embedding_model 未配置")
    response = client.embeddings.create(
        model=get_settings().v2_embedding_model, input=texts
    )
    data = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in data]


def _embed_batch_with_retry(texts: list[str]) -> list[list[float]]:
    last_exc: Exception | None = None
    for attempt in range(EMBED_RETRY_ATTEMPTS):
        if attempt:
            time.sleep(EMBED_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        try:
            return _embed_batch(texts)
        except EmbeddingClientUnavailableError:
            raise
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "embedding 批量调用失败（第 %d 次）：%s", attempt + 1, exc.__class__.__name__
            )
    assert last_exc is not None
    raise last_exc


def _record_job_failures(items: list[_PendingItem], error: str) -> None:
    for item in items:
        background_job_repository.enqueue_job(
            JOB_TYPE_EMBEDDING_BACKFILL,
            {
                "memory_id": item.memory_id,
                "content_hash": _content_hash(item.content),
            },
            _job_key(item),
            last_error=error,
        )


def _process(items: list[_PendingItem], trace=None) -> int:
    started = time.perf_counter()
    settings = get_settings()
    client = get_embedding_client()
    if client is None:
        logger.warning("embedding 客户端未配置，本批 %d 条保持 NULL", len(items))
        return 0
    texts = [_truncate(item.content) for item in items]
    try:
        vectors = _embed_batch_with_retry(texts)
    except EmbeddingClientUnavailableError as exc:
        logger.warning("embedding 客户端不可用：%s", exc)
        return 0
    except Exception as exc:
        _record_job_failures(items, exc.__class__.__name__)
        _trace_batch(trace, started, items, 0, failed=len(items))
        return 0
    if len(vectors) != len(items) or any(
        len(vector) != settings.v2_embedding_dimensions for vector in vectors
    ):
        logger.warning(
            "embedding 返回维度/条数异常：期望 %d 维 %d 条", settings.v2_embedding_dimensions, len(items)
        )
        _record_job_failures(items, "dimension_mismatch")
        _trace_batch(trace, started, items, 0, failed=len(items))
        return 0
    pairs = [(item.memory_id, vector) for item, vector in zip(items, vectors)]
    updated = memory_repository.update_embeddings_batch(pairs)
    background_job_repository.complete_jobs(
        JOB_TYPE_EMBEDDING_BACKFILL, [_job_key(item) for item in items]
    )
    _trace_batch(trace, started, items, updated)
    return updated


def _trace_batch(
    trace, started: float, items: list[_PendingItem], updated: int, failed: int = 0
) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(
        STEP_NAME,
        duration,
        "error" if failed and not updated else "ok",
        batch_size=len(items),
        updated=updated,
        failed=failed,
    )


def embed_query(text: str) -> list[float] | None:
    """单条查询向量化；未配置或端点异常返回 None（检索侧降级纯结构化）。"""
    if not (text or "").strip():
        return None
    client = get_embedding_client()
    if client is None:
        return None
    try:
        return _embed_batch([_truncate(text)])[0]
    except Exception as exc:
        logger.warning("query 向量化失败，降级结构化检索：%s", exc.__class__.__name__)
        return None


def reset_queue() -> None:
    """清空内存队列（测试与运维复位用；持久恢复依赖 NULL 补扫，不依赖内存态）。"""
    _queue.clear()
    _queued_ids.clear()
