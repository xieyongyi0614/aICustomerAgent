"""V9 声明式场景套件（testing.md §2）。

逐场景加载 scenarios/*.json：命中行动经 检出→run_action_planning 到终态，
并按需断言世界副作用；反例断言不触发。全部确定性。
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.application import world_engine
from app.application.action_engine import run_action_planning
from app.services.action.detector import detect_action_intent

NOW = datetime(2026, 9, 3, 14, 0, 0)
SCENARIO_DIR = Path(__file__).parent / "scenarios"


@pytest.fixture(autouse=True)
def _bind_scenario_clock():
    """场景用固定 NOW 模拟某一时刻：周期外的行动域也须读同一口径。

    否则工具层的 `future_datetime` 语义校验会拿真实时间比 `NOW + 1d` 的 `due_at`，
    把合法提醒判成 `not_future`（V2.4.0 校验段转正常开后才会显形）。
    """
    from app.core import clock as logical_clock

    token = logical_clock.bind(NOW)
    yield
    logical_clock.unbind(token)


def _load_scenarios():
    scenarios = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as fh:
            scenarios.append(json.load(fh))
    return scenarios


SCENARIOS = _load_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
@pytest.mark.asyncio
async def test_scenario(scenario, db_session_factory, override_settings):
    override_settings()
    user_id = f"scenario-{scenario['id']}"
    world_engine.ensure_world(user_id)

    for i, case in enumerate(scenario["positive"]):
        intent = detect_action_intent(case["input"], now=NOW)
        case_prefix = f"{scenario['id']} positive[{i}]"
        assert intent is not None, f"{case_prefix}: 应检出 {case['expect_action_type']}"
        assert intent.action_type == case["expect_action_type"], case_prefix

        expect_terminal = case.get("expect_terminal", "succeeded")
        record = None
        if intent.confidence == "confident":
            record = await run_action_planning(user_id, intent, session_id="s1")
            assert record is not None, case_prefix
        elif intent.confidence == "ambiguous":
            # ambiguous 直接走闸门否决：构造 planning 得到 cancelled(ambiguous_params)
            record = await run_action_planning(user_id, intent, session_id="s1")
            assert record is not None, case_prefix

        if record is not None:
            assert record.status == expect_terminal, (
                f"{case_prefix}: 期望 {expect_terminal} 实得 {record.status}"
            )
            if case.get("expect_gate_reason"):
                assert record.gate_reason == case["expect_gate_reason"]

        expected_object = case.get("expect_world_object")
        if expected_object is not None:
            names = [o.name for o in world_engine.list_active_objects(user_id)]
            assert expected_object in names, case_prefix

        expected_event = case.get("expect_world_event")
        if expected_event is not None:
            events = world_engine.list_active_events(user_id)
            assert any(
                e.type == expected_event["type"]
                and expected_event.get("title_contains") in e.title
                for e in events
            ), case_prefix

    for i, case in enumerate(scenario["negative"]):
        intent = detect_action_intent(case["input"], now=NOW)
        assert intent is None, (
            f"{scenario['id']} negative[{i}]: 不应检出，实得 {intent}"
        )