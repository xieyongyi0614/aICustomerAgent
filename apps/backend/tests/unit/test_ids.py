"""雪花 ID 发号单测：位分配 / 唯一性 / 进程内回拨 / 跨重启水位防护。"""

from __future__ import annotations

import datetime as dt

import fakeredis.aioredis
import pytest
import sonyflake.sonyflake as sonyflake_module

from app.core import ids, redis_client
from app.core.settings import SettingsError
from app.core.settings.ids import IdsSettings

pytestmark = pytest.mark.unit

EPOCH = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
BASE = dt.datetime(2026, 10, 3, 7, 0, 0, tzinfo=dt.UTC)


class FakeClock:
    def __init__(self, now: dt.datetime) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now

    def set(self, now: dt.datetime) -> None:
        self.now = now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock(BASE)
    monkeypatch.setattr(sonyflake_module, "_utcnow", fake)
    return fake


@pytest.fixture(autouse=True)
def fresh_state(clock):
    ids.set_generator(None)
    ids.set_high_water_ms(0)
    yield
    ids.set_generator(None)
    ids.set_high_water_ms(0)


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis(client)
    yield client
    await client.aclose()
    redis_client.set_redis(None)


def test_bit_allocation_is_41_12_10():
    generator = ids.get_generator()
    assert generator._bits_time == 41
    assert generator._bits_sequence == 12
    assert generator._bits_machine_id == 10


def test_epoch_is_2026_start():
    generator = ids.get_generator()
    assert generator.to_time(0) == EPOCH
    assert generator.to_time(1 << 22) == EPOCH + dt.timedelta(milliseconds=1)


def test_new_id_unique_and_monotonic():
    values = [ids.new_id() for _ in range(2000)]
    assert len(set(values)) == 2000
    assert values == sorted(values)


def test_new_id_fits_signed_int64():
    values = [ids.new_id() for _ in range(100)]
    assert max(v.bit_length() for v in values) <= 63
    assert min(values) > 0


def test_new_id_async_shares_sequence_space_with_sync():
    import asyncio

    async def run():
        return [await ids.new_id_async() for _ in range(10)]

    values = asyncio.run(run())
    values += [ids.new_id() for _ in range(10)]
    assert len(set(values)) == 20
    assert values == sorted(values)


def test_clock_rollback_within_process_does_not_duplicate(clock):
    before = [ids.new_id() for _ in range(100)]
    clock.set(BASE - dt.timedelta(seconds=5))
    after = [ids.new_id() for _ in range(100)]
    merged = before + after
    assert len(set(merged)) == len(merged)
    assert merged == sorted(merged)


def test_clock_rollback_does_not_move_logical_time_backwards(clock):
    generator = ids.get_generator()
    first = ids.new_id()
    clock.set(BASE - dt.timedelta(hours=1))
    second = ids.new_id()
    assert generator.to_time(second) >= generator.to_time(first)


def test_sequence_exhaustion_borrows_forward_without_duplicates():
    values = [ids.new_id() for _ in range(4200)]
    assert len(set(values)) == 4200
    assert values == sorted(values)


def test_high_water_tracks_logical_time(clock):
    assert ids.high_water_ms() == 0
    value = ids.new_id()
    expected = int(EPOCH.timestamp() * 1000) + ids.get_generator().decompose(value).time
    assert ids.high_water_ms() == expected


def test_high_water_never_moves_backwards_on_rollback(clock):
    ids.new_id()
    peak = ids.high_water_ms()
    clock.set(BASE - dt.timedelta(hours=2))
    ids.new_id()
    assert ids.high_water_ms() >= peak


def test_assert_clock_not_rolled_back_rejects_backwards_clock():
    with pytest.raises(ids.ClockRollbackError):
        ids.assert_clock_not_rolled_back(ids.now_millis() + 3_600_000)


def test_assert_clock_not_rolled_back_accepts_clock_ahead():
    ids.assert_clock_not_rolled_back(ids.now_millis() - 3_600_000)


async def test_startup_guard_raises_when_persisted_watermark_is_ahead(redis):
    await redis.set(
        IdsSettings().ids_high_water_storage_key(), str(ids.now_millis() + 3_600_000)
    )
    with pytest.raises(ids.ClockRollbackError):
        await ids.startup_guard()


async def test_startup_guard_adopts_persisted_watermark(redis):
    watermark = ids.now_millis() - 1000
    await redis.set(IdsSettings().ids_high_water_storage_key(), str(watermark))
    await ids.startup_guard()
    assert ids.high_water_ms() == watermark


async def test_flush_high_water_is_monotonic(redis):
    ids.set_high_water_ms(1_000_000)
    await ids.flush_high_water()
    key = IdsSettings().ids_high_water_storage_key()
    assert await redis.get(key) == "1000000"

    ids.set_high_water_ms(500_000)
    await ids.flush_high_water()
    assert await redis.get(key) == "1000000"


async def test_flush_high_water_skips_when_redis_absent():
    redis_client.set_redis(None)
    ids.set_high_water_ms(1_000_000)
    await ids.flush_high_water()


async def test_load_high_water_ignores_malformed_value(redis):
    await redis.set(IdsSettings().ids_high_water_storage_key(), "not-a-number")
    assert await ids.load_high_water() == 0


def test_high_water_key_is_scoped_per_machine():
    assert IdsSettings(ids_machine_id=7).ids_high_water_storage_key() == (
        "ids:high_water_ms:7"
    )


def test_settings_reject_future_epoch():
    with pytest.raises(SettingsError):
        IdsSettings(ids_epoch_date="2099-01-01")


def test_settings_reject_malformed_epoch():
    with pytest.raises(SettingsError):
        IdsSettings(ids_epoch_date="2026/01/01")


def test_settings_reject_out_of_range_machine_id():
    with pytest.raises(SettingsError):
        IdsSettings(ids_machine_id=1024)


def test_settings_defaults_match_2026_plan():
    settings = IdsSettings()
    assert settings.ids_epoch_date == "2026-01-01"
    assert settings.ids_machine_id == 0
    assert settings.ids_high_water_flush_seconds == 5
    assert settings.ids_clock_rollback_tolerance_ms == 0
