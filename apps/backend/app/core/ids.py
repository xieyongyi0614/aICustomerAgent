"""雪花 ID 唯一发号入口。

生成逻辑全部委托 sonyflake（禁止自研位运算）；本模块只负责 epoch / 位分配 / machine_id
装配、跨重启时钟回拨防护、同步与异步两个出口。回拨防护设计见
`docs/refactor/identity-and-id-scheme.md`。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import threading

from sonyflake import Sonyflake

from app.core import redis_client
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

SEQUENCE_BITS = 12
MACHINE_BITS = 10
TIME_UNIT = dt.timedelta(milliseconds=1)
TIME_UNIT_MS = 1

_generator_lock = threading.Lock()
_generator: Sonyflake | None = None
_epoch_ms: int | None = None
_high_water_ms = 0


class ClockRollbackError(RuntimeError):
    """启动时系统时钟早于已发放 ID 水位；继续发号会与历史 ID 重复。"""


def _epoch_millis() -> int:
    global _epoch_ms
    if _epoch_ms is None:
        _epoch_ms = int(get_settings().ids_epoch_datetime().timestamp() * 1000)
    return _epoch_ms


def get_generator() -> Sonyflake:
    global _generator
    if _generator is None:
        with _generator_lock:
            if _generator is None:
                settings = get_settings()
                _generator = Sonyflake(
                    start_time=settings.ids_epoch_datetime(),
                    bits_sequence=SEQUENCE_BITS,
                    bits_machine_id=MACHINE_BITS,
                    time_unit=TIME_UNIT,
                    machine_id=settings.ids_machine_id,
                )
    return _generator


def set_generator(generator: Sonyflake | None) -> None:
    global _generator
    _generator = generator


def _record(generator: Sonyflake, value: int) -> int:
    global _high_water_ms
    logical_ms = _epoch_millis() + generator.decompose(value).time * TIME_UNIT_MS
    if logical_ms > _high_water_ms:
        _high_water_ms = logical_ms
    return value


def new_id() -> int:
    generator = get_generator()
    return _record(generator, generator.next_id())


def new_id_str() -> str:
    """字符串形态：用于 `VARCHAR` 主键列与 API 出参。

    雪花 ID 为 57+ 位，超出 JS 安全整数范围，对外一律字符串（见 ADR-16）。
    """
    return str(new_id())


async def new_id_async() -> int:
    generator = get_generator()
    return _record(generator, await generator.next_id_async())


def high_water_ms() -> int:
    return _high_water_ms


def set_high_water_ms(value: int) -> None:
    global _high_water_ms
    _high_water_ms = value


def now_millis() -> int:
    return int(dt.datetime.now(dt.UTC).timestamp() * 1000)


def assert_clock_not_rolled_back(persisted_high_water_ms: int) -> None:
    tolerance = get_settings().ids_clock_rollback_tolerance_ms
    now_ms = now_millis()
    if now_ms < persisted_high_water_ms - tolerance:
        raise ClockRollbackError(
            f"系统时钟 {now_ms} 早于已发放 ID 水位 {persisted_high_water_ms}："
            "继续发号会与历史 ID 重复。请校正系统时间，或等待时钟追平后再启动。"
        )


async def load_high_water() -> int:
    if not redis_client.is_configured():
        return 0
    try:
        raw = await redis_client.get_redis().get(
            get_settings().ids_high_water_storage_key()
        )
    except Exception:
        logger.warning("读取雪花 ID 水位失败，本次跳过跨重启回拨校验", exc_info=True)
        return 0
    if not raw:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("雪花 ID 水位格式非法：%r，按 0 处理", raw)
        return 0


async def flush_high_water() -> None:
    if not redis_client.is_configured():
        return
    key = get_settings().ids_high_water_storage_key()
    try:
        client = redis_client.get_redis()
        raw = await client.get(key)
        persisted = int(raw) if raw else 0
        if _high_water_ms > persisted:
            await client.set(key, str(_high_water_ms))
    except Exception:
        logger.warning("写入雪花 ID 水位失败", exc_info=True)


async def startup_guard() -> None:
    persisted = await load_high_water()
    assert_clock_not_rolled_back(persisted)
    if persisted > _high_water_ms:
        set_high_water_ms(persisted)
    await flush_high_water()
    logger.info(
        "雪花 ID 发号就绪：epoch=%s machine_id=%d 水位=%d",
        get_settings().ids_epoch_date,
        get_settings().ids_machine_id,
        _high_water_ms,
    )


async def run_high_water_flusher() -> None:
    interval = get_settings().ids_high_water_flush_seconds
    while True:
        await asyncio.sleep(interval)
        await flush_high_water()
