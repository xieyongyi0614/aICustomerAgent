"""简报端点：请求校验、偏好落库与定位链（替身天气/地理编码，零真实网络）。

响应契约字段（APP-018 §4.4）：{type, greeting, title, orb_note, cards[], cta, generated_at}。
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import weather


URL = "/api/v1/briefing"


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def fake_weather(monkeypatch):
    calls: list[tuple[float, float]] = []

    async def _fake(latitude, longitude):
        calls.append((latitude, longitude))
        return weather.WeatherSnapshot(
            temperature_c=21.0,
            condition="晴",
            temp_min_c=15.0,
            temp_max_c=27.0,
            precipitation_probability=10,
        )

    monkeypatch.setattr(weather, "get_current_weather", _fake)
    return calls


@pytest.fixture
def fake_weather_unavailable(monkeypatch):
    async def _fake(latitude, longitude):
        return None

    monkeypatch.setattr(weather, "get_current_weather", _fake)


@pytest.fixture
def fake_geocode(monkeypatch):
    async def _fake(city):
        return weather.GeoLocation(name="上海", latitude=31.2304, longitude=121.4737)

    monkeypatch.setattr(weather, "geocode_city", _fake)


async def test_morning_weather_card_degrades_without_location(
    fake_weather_unavailable,
):
    async with _client() as client:
        response = await client.get(URL, params={"type": "morning"})
    assert response.status_code == 200
    content = response.json()
    assert content["type"] == "morning"
    assert content["greeting"].endswith("早间简报")
    assert content["cta"] == "开始今天"
    assert content["generated_at"]
    weather_card = next(card for card in content["cards"] if card["title"] == "天气")
    assert weather_card["body"] == "暂无实时数据"


async def test_morning_uses_request_coordinates(fake_weather):
    async with _client() as client:
        response = await client.get(
            URL, params={"type": "morning", "lat": 39.9042, "lon": 116.4074}
        )
    assert response.status_code == 200
    assert response.json()["orb_note"] == "今天晴，21°"
    weather_card = next(
        card for card in response.json()["cards"] if card["title"] == "天气"
    )
    assert weather_card["body"] == "21° 晴"
    assert fake_weather == [(39.9042, 116.4074)]


async def test_unpaired_coordinates_rejected():
    async with _client() as client:
        response = await client.get(URL, params={"type": "morning", "lat": 39.9})
    assert response.status_code == 422


async def test_out_of_range_coordinates_rejected():
    async with _client() as client:
        response = await client.get(
            URL, params={"type": "morning", "lat": 91.0, "lon": 0.0}
        )
    assert response.status_code == 422


async def test_prefs_roundtrip_with_geocoded_city(fake_geocode):
    async with _client() as client:
        saved = await client.put(
            f"{URL}/preferences", json={"morning_at": "07:30", "city": "上海"}
        )
        assert saved.status_code == 200
        assert saved.json()["city"] == "上海"

        fetched = await client.get(f"{URL}/preferences")
        assert fetched.status_code == 200
        assert fetched.json() == {
            "morning_at": "07:30",
            "evening_at": None,
            "city": "上海",
        }

        briefing = await client.get(URL, params={"type": "morning"})
    assert briefing.json()["greeting"].startswith("07:30 · ")


async def test_unknown_city_rejected(fake_weather_unavailable, monkeypatch):
    async def _fail(city):
        return None

    monkeypatch.setattr(weather, "geocode_city", _fail)
    async with _client() as client:
        response = await client.put(
            f"{URL}/preferences", json={"city": "亚特兰蒂斯"}
        )
    assert response.status_code == 422
    assert "城市无法识别" in response.json()["detail"]


async def test_bad_time_format_rejected():
    async with _client() as client:
        response = await client.put(
            f"{URL}/preferences", json={"morning_at": "25:00"}
        )
    assert response.status_code == 422


async def test_put_without_city_clears_saved_city(fake_geocode):
    async with _client() as client:
        await client.put(f"{URL}/preferences", json={"city": "上海"})
        cleared = await client.put(f"{URL}/preferences", json={})
        fetched = await client.get(f"{URL}/preferences")
    assert cleared.status_code == 200
    assert fetched.json()["city"] is None
