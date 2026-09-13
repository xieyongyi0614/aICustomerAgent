"""WS-012：WorldBriefAssembler 与 Context 注入测试。"""

from datetime import datetime

import pytest

from app.application import world_engine
from app.core.settings import get_settings
from app.models.world import TimeContext, WorldTimeMode
from app.models.world_simulation import (
    SituationDimension,
    SituationSource,
    SituationStatus,
    UserSituation,
    WorldBrief,
)
from app.repositories import world_repository, world_simulation_repository as repo
from app.services.world import world_brief
from app.services.world.context_selector import render_world_section

pytestmark = pytest.mark.xdist_group("ws012")


def _time_ctx(now: datetime) -> TimeContext:
    from app.models.world import WEEKDAY_CN, part_of_day

    return TimeContext(
        now=now,
        weekday=WEEKDAY_CN[now.weekday()],
        part_of_day=part_of_day(now),
        time_mode=WorldTimeMode.REAL_SYNC,
    )


def _situation(user_id: str) -> UserSituation:
    now = datetime.now()
    return UserSituation(
        id=repo.new_situation_id(),
        user_id=user_id,
        dimension=SituationDimension.WORK_PRESSURE,
        summary="用户工作压力大",
        intensity=3,
        status=SituationStatus.ACTIVE,
        source=SituationSource.CONVERSATION_PATTERN,
        evidence={"quote": "加班"},
        detected_at=now,
        valid_until=now.replace(year=now.year + 1),
    )


def test_brief_full_shape(db_session_factory):
    user = "ws012-full"
    world = world_repository.ensure_world(user)
    block = type("B", (), {"activity": "阅读"})()
    situations = [_situation(user)]
    brief = world_brief.build_world_brief(
        _time_ctx(datetime(2026, 9, 14, 21, 30)),
        world,
        block,
        situations,
        budget=400,
    )
    assert isinstance(brief, WorldBrief)
    assert "09-14" in brief.time_line
    assert "晚上" in brief.time_line
    assert "阅读" in brief.place_line
    assert brief.situations_line and "工作压力" in brief.situations_line
    assert len(brief.text) <= 400
    assert brief.text.endswith("。")


def test_brief_degrades_without_inputs(db_session_factory):
    user = "ws012-degrade"
    world = world_repository.ensure_world(user)
    brief = world_brief.build_world_brief(_time_ctx(datetime(2026, 9, 14, 10, 0)), world)
    assert brief.situations_line is None
    assert brief.events_line is None
    assert brief.place_line
    assert "正在" not in brief.place_line


def test_brief_budget_trims_events_first(db_session_factory):
    user = "ws012-trim"
    world = world_repository.ensure_world(user)
    event = type("E", (), {"title": "x" * 200})()
    brief = world_brief.build_world_brief(
        _time_ctx(datetime(2026, 9, 14, 10, 0)),
        world,
        None,
        [_situation(user)],
        [event],
        budget=120,
    )
    assert len(brief.text) <= 120


def test_render_without_brief_byte_identical(db_session_factory):
    user = "ws012-render"
    world = world_repository.ensure_world(user)
    ctx = world_engine.build_context(user)
    baseline = render_world_section(ctx, 600)
    assert render_world_section(ctx, 600, brief=None) == baseline


def test_render_with_brief_prepends_lines(db_session_factory):
    user = "ws012-render2"
    world = world_repository.ensure_world(user)
    ctx = world_engine.build_context(user)
    brief = WorldBrief(
        text="简报。",
        time_line="09-14 周一 晚上 21:30 晴天",
        place_line="她此刻在家·客厅。",
    )
    rendered = render_world_section(ctx, 1000, brief=brief)
    baseline = render_world_section(ctx, 1000)
    assert rendered.startswith(baseline.split("\n")[0])
    assert "09-14 周一 晚上 21:30 晴天" in rendered
    assert rendered.index("09-14") < rendered.index("【当前世界】") + 30


def test_build_context_attaches_brief_only_when_enabled(db_session_factory, monkeypatch):
    user = "ws012-flag"
    world_repository.ensure_world(user)
    ctx_off = world_engine.build_context(user)
    assert ctx_off.brief is None

    monkeypatch.setenv("V23_WORLD_SIMULATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        ctx_on = world_engine.build_context(user)
        assert ctx_on.brief is not None
        assert ctx_on.brief.time_line
    finally:
        get_settings.cache_clear()


def test_prompt_builder_budget_switch(monkeypatch):
    from app.prompts.builder import PromptBuilder

    settings = get_settings()
    assert settings.world_context_char_budget == 600
    assert settings.world_context_char_budget_v23 == 1000
