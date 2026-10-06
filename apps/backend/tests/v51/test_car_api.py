"""API-020 车辆域产品级接口用例。"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import timeutil
from app.api.v1 import auth as auth_api
from app.main import create_app
from app.services.car import aggregate as car_aggregate
from app.services.car import entries as car_entries
from app.services.car import service as car_service
from tests.conftest import TEST_USER_ID

BACKEND = Path(__file__).resolve().parents[2]
USER = TEST_USER_ID
NOW = timeutil.ensure_aware(datetime(2026, 9, 30, 12, 0, 0))
CHARGE_AT = timeutil.ensure_aware(datetime(2026, 9, 28, 9, 0, 0))
SERVICE_AT = timeutil.ensure_aware(datetime(2026, 9, 29, 9, 0, 0))


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW
ENDPOINTS = (
    ("GET", "/api/v1/car/overview"),
    ("GET", "/api/v1/car/profile"),
    ("PUT", "/api/v1/car/profile"),
    ("POST", "/api/v1/car/entries"),
    ("GET", "/api/v1/car/services"),
)
HINT_MARKERS = ("生活 · 记账", "不用重复记")


@pytest.fixture()
def client():
    test_app = create_app()
    test_app.dependency_overrides[auth_api.require_user] = lambda: TEST_USER_ID
    return TestClient(test_app)


def _seed_expenses() -> None:
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=CHARGE_AT,
        note="快充",
        idempotency_key="api-key-charge1",
        now=NOW,
    )
    car_entries.record_car_expense(
        USER,
        kind="service",
        amount_minor=20000,
        note="小保养 · 机油机滤",
        place="华迪 4S 店",
        odometer_km=10380,
        occurred_at=SERVICE_AT,
        idempotency_key="api-key-service1",
        now=NOW,
    )


def _put_profile(client, payload: dict):
    return client.put("/api/v1/car/profile", json=payload)


def test_car_overview_returns_all_blocks_in_one_request(client, monkeypatch):
    monkeypatch.setattr(car_service, "datetime", _FixedClock)
    _seed_expenses()
    response = _put_profile(
        client,
        {
            "model": "比亚迪 汉 EV",
            "plate": "沪 A·D8F2K",
            "battery_kwh": 85.4,
            "odometer_km": 12480,
            "purchased_at": "2024-06-15T00:00:00",
            "service_interval_km": 10000,
            "service_interval_months": 12,
            "insurance_due_at": "2026-11-01T00:00:00",
        },
    )
    assert response.status_code == 200

    body = client.get("/api/v1/car/overview").json()

    assert body["profile"] == {
        "model": "比亚迪 汉 EV",
        "plate": "沪 A·D8F2K",
        "odometer_km": 12480,
    }
    assert body["loan"] is None
    assert body["expense_total_minor"] == 24200
    assert body["expense_total_text"] == "242.00"
    assert [line["category_name"] for line in body["expense_breakdown"]] == [
        "保养",
        "充电",
    ]
    assert body["expense_breakdown"][1]["count"] == 1
    assert body["ev_metrics"]["charge_cost_minor_month"] == 4200
    assert body["ev_metrics"]["charge_count_month"] == 1
    assert body["ev_metrics"]["charge_kwh_month"] is None
    assert body["ev_metrics"]["basis"] == "approximate"
    assert body["recent_records"][0]["title"] == "小保养 · 机油机滤"
    assert body["degraded_blocks"] == []
    assert body["restriction_guide"]
    assert [item["kind"] for item in body["reminders"]] == ["service", "insurance"]


def test_car_overview_expense_matches_aggregate(client, monkeypatch):
    monkeypatch.setattr(car_service, "datetime", _FixedClock)
    _seed_expenses()

    body = client.get("/api/v1/car/overview").json()
    lines = car_aggregate.car_expense_breakdown(USER, now=NOW)

    assert [line["net_minor"] for line in body["expense_breakdown"]] == [
        line.net_minor for line in lines
    ]
    assert body["expense_total_minor"] == car_aggregate.car_expense_total(lines)


def test_car_overview_degrades_block_without_500(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("聚合不可用")

    monkeypatch.setattr(car_aggregate, "car_expense_breakdown", boom)

    response = client.get("/api/v1/car/overview")

    assert response.status_code == 200
    body = response.json()
    assert "expense_breakdown" in body["degraded_blocks"]
    assert body["expense_breakdown"] == []
    assert body["expense_total_minor"] == 0


def test_car_profile_derives_age_and_paid_ratio(client):
    response = _put_profile(
        client,
        {
            "battery_kwh": 85.4,
            "odometer_km": 12480,
            "purchased_at": "2024-06-15T00:00:00",
            "charger_power_kw": 7.0,
            "charger_note": "家用 7 kW · 谷电",
            "loan": {
                "principal_minor": 13860000,
                "monthly_minor": 385000,
                "paid_periods": 18,
                "total_periods": 36,
                "next_due_at": "2026-10-05T00:00:00",
            },
        },
    )

    assert response.status_code == 200
    body = client.get("/api/v1/car/profile").json()

    assert body["identity"]["age_text"] == "2 年 3 个月"
    assert body["identity"]["battery_kwh"] == 85.4
    assert body["loan"]["remaining_minor"] == 6930000
    assert body["loan"]["remaining_text"] == "69300.00"
    assert body["loan"]["paid_ratio"] == 0.5
    files = {row["key"]: row for row in body["files"]}
    assert set(files) == {"insurance", "inspection", "charger", "service_interval"}
    assert files["charger"]["value_text"] == "7 kW"
    assert files["insurance"]["value_text"] == "未填写"
    assert files["service_interval"]["value_text"] == "未填写"


def test_car_profile_returns_services_with_pending_last_row(client):
    _seed_expenses()
    _put_profile(client, {"odometer_km": 12480, "service_interval_km": 10000})

    body = client.get("/api/v1/car/profile").json()

    services = body["services"]
    assert len(services) == 2
    assert services[0]["upcoming"] is False
    assert services[0]["amount_text"] == "200.00"
    assert services[0]["amount_minor"] == 20000
    assert services[-1]["upcoming"] is True
    assert services[-1]["due_km"] is not None
    assert services[-1]["amount_minor"] is None
    assert [item["kind"] for item in body["reminders"]] == ["service"]


def test_car_profile_put_partial_update_keeps_other_fields(client):
    _put_profile(client, {"model": "汉 EV", "odometer_km": 12000})
    _put_profile(client, {"plate": "沪 A·D8F2K"})

    body = client.get("/api/v1/car/profile").json()

    assert body["identity"]["model"] == "汉 EV"
    assert body["identity"]["plate"] == "沪 A·D8F2K"
    assert body["identity"]["odometer_km"] == 12000


def test_car_profile_put_validates_battery_and_odometer(client):
    assert _put_profile(client, {"battery_kwh": 0}).status_code == 422
    assert _put_profile(client, {"odometer_km": -1}).status_code == 422


def test_car_profile_put_validates_loan_invariants(client):
    response = _put_profile(
        client,
        {
            "loan": {
                "monthly_minor": 385000,
                "paid_periods": 40,
                "total_periods": 36,
            }
        },
    )

    assert response.status_code == 422
    assert client.get("/api/v1/car/profile").json()["loan"] is None


def test_car_profile_put_validates_loan_invariants_against_existing(client):
    _put_profile(
        client,
        {
            "loan": {
                "monthly_minor": 385000,
                "paid_periods": 18,
                "total_periods": 36,
            }
        },
    )

    response = _put_profile(client, {"loan": {"paid_periods": 40}})

    assert response.status_code == 422


def test_car_entries_passthrough_kinds(client):
    cases = (
        ("charge", 4200, "充电"),
        ("fuel", 10000, "加油费"),
        ("parking", 5000, "停车费"),
        ("toll", 13000, "过路"),
        ("service", 20000, "保养"),
    )
    for kind, amount_minor, category_name in cases:
        response = client.post(
            "/api/v1/car/entries",
            json={
                "kind": kind,
                "amount_minor": amount_minor,
                "idempotency_key": f"api-key-{kind}-0001",
                "odometer_km": 12480,
            },
        )
        assert response.status_code == 200, kind
        body = response.json()
        assert body["kind"] == kind
        assert body["entry_id"]
        assert body["category_name"] == category_name

    mileage = client.post(
        "/api/v1/car/entries",
        json={
            "kind": "mileage",
            "odometer_km": 12500,
            "note": "通勤往返",
            "idempotency_key": "api-key-mileage-0001",
        },
    )
    assert mileage.status_code == 200
    body = mileage.json()
    assert body["entry_id"] is None
    assert body["category_name"] == ""
    assert body["odometer_delta_km"] == 20
    assert "账目" in body["hint"]


def test_car_entries_hint_is_server_side_text(client):
    response = client.post(
        "/api/v1/car/entries",
        json={"kind": "charge", "amount_minor": 4200, "idempotency_key": "api-key-hint-01"},
    )

    assert response.status_code == 200
    hint = response.json()["hint"]
    assert hint
    for marker in HINT_MARKERS:
        assert marker in hint


def test_car_entries_rejects_missing_amount_and_short_key(client):
    missing = client.post(
        "/api/v1/car/entries",
        json={"kind": "charge", "idempotency_key": "api-key-amount-01"},
    )
    short = client.post(
        "/api/v1/car/entries",
        json={"kind": "charge", "amount_minor": 4200, "idempotency_key": "short"},
    )

    assert missing.status_code == 422
    assert short.status_code == 422


def test_car_services_endpoint_paginates(client):
    _seed_expenses()
    _put_profile(client, {"odometer_km": 12480, "service_interval_km": 10000})

    body = client.get("/api/v1/car/services", params={"limit": 1}).json()

    assert body["total"] == 1
    assert body["limit"] == 1
    assert [item["upcoming"] for item in body["items"]] == [False, True]
    assert client.get("/api/v1/car/services", params={"limit": 99}).status_code == 400


def test_car_endpoints_require_token():
    test_app = create_app()
    with TestClient(test_app) as raw_client:
        for method, path in ENDPOINTS:
            response = raw_client.request(method, path)
            assert response.status_code == 401, (method, path)


def test_car_api_has_zero_repositories_import():
    source = (BACKEND / "app" / "api" / "v1" / "car.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = [
        name
        for name in imported
        if name.startswith("app.repositories")
        or name.startswith("app.core.db")
        or name.startswith("langchain")
        or name.startswith("app.application")
    ]
    assert forbidden == []
