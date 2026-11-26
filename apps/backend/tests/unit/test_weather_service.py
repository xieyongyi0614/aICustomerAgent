"""现实天气服务：响应映射、坐标分键缓存、地理编码与降级（替身传输，零真实网络）。"""

import pytest

from app.services.briefing import weather


class FakeTransport(weather.WeatherTransport):
    def __init__(self, payload=None, error=None):
        self.calls = 0
        self.last_url = ""
        self._payload = payload
        self._error = error

    async def fetch_json(self, url, timeout_seconds):
        self.calls += 1
        self.last_url = url
        if self._error is not None:
            raise self._error
        return self._payload


def _open_meteo_payload():
    return {
        "current": {"temperature_2m": 18.3, "weather_code": 2},
        "daily": {
            "temperature_2m_max": [22.1],
            "temperature_2m_min": [12.4],
            "precipitation_probability_max": [30],
        },
    }


def _geocode_payload():
    return {
        "results": [
            {
                "name": "上海",
                "latitude": 31.2304,
                "longitude": 121.4737,
                "country": "中国",
                "admin1": "上海市",
            }
        ]
    }


@pytest.fixture(autouse=True)
def _restore_state():
    weather.reset_weather_cache()
    weather.set_weather_transport(None)
    yield
    weather.reset_weather_cache()
    weather.set_weather_transport(None)


async def test_maps_current_and_daily_fields():
    transport = FakeTransport(payload=_open_meteo_payload())
    weather.set_weather_transport(transport)

    snapshot = await weather.get_current_weather(39.9042, 116.4074)

    assert snapshot == weather.WeatherSnapshot(
        temperature_c=18.3,
        condition="少云",
        temp_min_c=12.4,
        temp_max_c=22.1,
        precipitation_probability=30,
    )
    assert "latitude=39.9042" in transport.last_url
    assert "longitude=116.4074" in transport.last_url


async def test_network_failure_degrades_to_none():
    weather.set_weather_transport(FakeTransport(error=OSError("network down")))

    assert await weather.get_current_weather(39.9042, 116.4074) is None


async def test_malformed_payload_degrades_to_none():
    weather.set_weather_transport(FakeTransport(payload={"current": None}))

    assert await weather.get_current_weather(39.9042, 116.4074) is None


async def test_unknown_weather_code_maps_to_placeholder():
    payload = {"current": {"temperature_2m": 20.0, "weather_code": 42}}
    weather.set_weather_transport(FakeTransport(payload=payload))

    snapshot = await weather.get_current_weather(39.9042, 116.4074)

    assert snapshot is not None
    assert snapshot.condition == "未知"


async def test_cache_hits_within_ttl(override_settings):
    override_settings(weather_cache_ttl_seconds=300)
    transport = FakeTransport(payload=_open_meteo_payload())
    weather.set_weather_transport(transport)

    first = await weather.get_current_weather(39.9042, 116.4074)
    second = await weather.get_current_weather(39.9042, 116.4074)

    assert transport.calls == 1
    assert second is first


async def test_cache_is_keyed_by_coordinates():
    transport = FakeTransport(payload=_open_meteo_payload())
    weather.set_weather_transport(transport)

    await weather.get_current_weather(39.9042, 116.4074)
    await weather.get_current_weather(31.2304, 121.4737)

    assert transport.calls == 2


async def test_zero_ttl_disables_cache(override_settings):
    override_settings(weather_cache_ttl_seconds=0)
    transport = FakeTransport(payload=_open_meteo_payload())
    weather.set_weather_transport(transport)

    await weather.get_current_weather(39.9042, 116.4074)
    await weather.get_current_weather(39.9042, 116.4074)

    assert transport.calls == 2


async def test_geocode_maps_first_result():
    transport = FakeTransport(payload=_geocode_payload())
    weather.set_weather_transport(transport)

    location = await weather.geocode_city("上海")

    assert location == weather.GeoLocation(
        name="上海", latitude=31.2304, longitude=121.4737
    )
    assert "name=%E4%B8%8A%E6%B5%B7" in transport.last_url


async def test_geocode_unknown_city_returns_none():
    weather.set_weather_transport(FakeTransport(payload={}))

    assert await weather.geocode_city("不存在的地方") is None


async def test_geocode_failure_returns_none():
    weather.set_weather_transport(FakeTransport(error=OSError("network down")))

    assert await weather.geocode_city("上海") is None


async def test_geocode_result_is_cached():
    transport = FakeTransport(payload=_geocode_payload())
    weather.set_weather_transport(transport)

    first = await weather.geocode_city("上海")
    second = await weather.geocode_city("上海")

    assert transport.calls == 1
    assert second is first
