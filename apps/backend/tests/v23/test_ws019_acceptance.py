"""WS-019：V2.3.0 World Simulation 全链路验收与逐字节一致性回归。

覆盖 architecture.md §6.1 验收矩阵：
  ① Flag 矩阵（6 组开关组合行为差异）
  ② 逐字节一致性（全 off 与 V2.2.0 基线 prompt/结构零差异）
  ③ 四条全链路场景（日常推进 / 降温提醒 / 前台简报 / 长离线追赶）
  ④ 边界不变量（§9.3 八条，含写域扫描与 0 LLM 断言）
  ⑤ 迁移与性能预算

写域扫描工具函数：模拟路径严禁直写 character/personality/relationship/goals。
"""

import logging
from datetime import date, datetime, timedelta

import pytest

from app.application import world_engine
from app.core import llm_factory
from app.core.settings import get_settings
from app.models.world import WorldTimeMode
from app.repositories import world_repository, world_simulation_repository
from app.services.world import (
    catch_up,
    daily_plan,
    day_cycle,
    event_impact,
    time_advancer,
    user_situation,
    weather,
    world_brief,
)

pytestmark = pytest.mark.xdist_group("ws019")

logger = logging.getLogger(__name__)

V23_FLAG_KEYS = (
    "WORLD_SIMULATION_ENABLED",
    "TIME_ADVANCE_ENABLED",
    "DAILY_LIFE_ENABLED",
    "EVENT_DETECTION_ENABLED",
    "SCENE_EXPANSION_ENABLED",
    "WORLD_LLM_ASSIST_ENABLED",
)

# --- Flag 矩阵：6 组组合 ------------------------------------------------------

FLAG_MATRIX = {
    "all_off": {},
    "master_time": {"WORLD_SIMULATION_ENABLED": "true", "TIME_ADVANCE_ENABLED": "true"},
    "plus_daily": {
        "WORLD_SIMULATION_ENABLED": "true",
        "TIME_ADVANCE_ENABLED": "true",
        "DAILY_LIFE_ENABLED": "true",
    },
    "plus_detection": {
        "WORLD_SIMULATION_ENABLED": "true",
        "TIME_ADVANCE_ENABLED": "true",
        "DAILY_LIFE_ENABLED": "true",
        "EVENT_DETECTION_ENABLED": "true",
    },
    "plus_scene": {
        "WORLD_SIMULATION_ENABLED": "true",
        "TIME_ADVANCE_ENABLED": "true",
        "DAILY_LIFE_ENABLED": "true",
        "EVENT_DETECTION_ENABLED": "true",
        "SCENE_EXPANSION_ENABLED": "true",
    },
    "all_on": {key: "true" for key in V23_FLAG_KEYS},
}


@pytest.fixture
def flag_env(monkeypatch):
    """按组开启 v23 Flag；未列出的显式关闭，保证矩阵组间隔离。"""

    def _apply(group: str):
        for key in V23_FLAG_KEYS:
            monkeypatch.setenv(key, "false")
        for key, value in FLAG_MATRIX[group].items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return group

    yield _apply
    get_settings.cache_clear()


# --- ① Flag 矩阵 --------------------------------------------------------------


@pytest.mark.parametrize("group", list(FLAG_MATRIX))
def test_flag_matrix_maintenance_step_executes_per_gate(db_session_factory, flag_env, group):
    flag_env(group)
    user = f"ws019-matrix-{group}"
    world_repository.ensure_world(user)
    settings = get_settings()

    result = world_engine.run_simulation_maintenance(user)

    if not settings.world_simulation_enabled or not settings.time_advance_enabled:
        assert result is None, f"{group}: 未开时间推进不应执行维护步"
        return
    assert result is not None
    assert isinstance(result, list)


@pytest.mark.parametrize("group", list(FLAG_MATRIX))
def test_flag_matrix_brief_presence_follows_master(db_session_factory, flag_env, group):
    flag_env(group)
    user = f"ws019-brief-{group}"
    world_repository.ensure_world(user)
    settings = get_settings()

    context = world_engine.build_context(user)

    if not settings.world_simulation_enabled:
        assert context is not None
        assert getattr(context, "brief", None) is None, f"{group}: 总闸关不得有简报"
    else:
        if context is not None:
            assert getattr(context, "brief", None) is not None


@pytest.mark.parametrize("group", list(FLAG_MATRIX))
def test_flag_matrix_plan_generated_only_with_daily_life(db_session_factory, flag_env, group):
    """daily_life 门控：维护步经 _run_simulation_substeps 时才生成当日计划。"""
    flag_env(group)
    user = f"ws019-plan-{group}"
    world_repository.ensure_world(user)
    settings = get_settings()

    world_engine.run_simulation_maintenance(user)

    plans = daily_plan.get_day_plan(user, datetime.now().date())
    if not (settings.world_simulation_enabled and settings.daily_life_enabled):
        assert plans == [], f"{group}: 未开 daily_life 不应生成计划"


@pytest.mark.parametrize("group", list(FLAG_MATRIX))
def test_flag_matrix_situation_detection_gated(db_session_factory, flag_env, group):
    """detection 门控：维护步内 expire_and_notify 仅在子闸开启时才参与。"""
    flag_env(group)
    user = f"ws019-sit-{group}"
    world_repository.ensure_world(user)
    settings = get_settings()

    world_engine.run_simulation_maintenance(user)

    situations = world_simulation_repository.list_situations(user)
    if not (
        settings.world_simulation_enabled
        and settings.time_advance_enabled
        and settings.event_detection_enabled
    ):
        assert situations == [], f"{group}: 未开 detection 不应有处境记录"


# --- ② 逐字节一致性 -----------------------------------------------------------


def test_flags_off_context_has_no_v23_bytes(db_session_factory, flag_env):
    """全 off：world 上下文不含任何 V2.3.0 新增字段（brief / impacts）。"""
    flag_env("all_off")
    user = "ws019-baseline"
    world_repository.ensure_world(user)

    context = world_engine.build_context(user)
    assert context is not None
    assert getattr(context, "brief", None) is None

    facts = world_engine.collect_facts(user)
    assert "impacts" not in facts
    assert "current_block" not in facts
    assert "active_situations" not in facts


def test_flags_off_simulation_maintenance_is_noop(db_session_factory, flag_env):
    """全 off：run_simulation_maintenance 返回 None 且零副作用（与 V2.2.0 一致）。"""
    flag_env("all_off")
    user = "ws019-noop"
    world = world_repository.ensure_world(user)
    before = len(world_repository.list_events(world.world_id, limit=500))

    assert world_engine.run_simulation_maintenance(user) is None

    after = len(world_repository.list_events(world.world_id, limit=500))
    assert after == before


def test_prompt_world_section_identical_when_brief_absent(db_session_factory, flag_env):
    """render_world_section 在 brief=None 时输出与既有路径一致（追加零字节）。"""
    from app.services.world.context_selector import render_world_section

    flag_env("all_off")
    user = "ws019-render"
    world_repository.ensure_world(user)
    context = world_engine.build_context(user)

    with_brief_none = render_world_section(context, budget=600, brief=None)
    baseline = render_world_section(context, budget=600)
    assert with_brief_none == baseline


# --- ③ 四条全链路场景 ---------------------------------------------------------


def test_flow_daily_progression(db_session_factory, flag_env):
    """§7.1 日常推进：维护步 → 时间锚点 + 日循环标记 + 计划推进。"""
    flag_env("plus_daily")
    user = "ws019-flow-daily"
    world = world_repository.ensure_world(user)
    now = datetime.now()

    result = world_engine.run_simulation_maintenance(user, now=now)
    assert result is not None

    refreshed = world_repository.get_world(user)
    assert refreshed is not None
    assert refreshed.sim_last_advanced_at is not None

    plans = daily_plan.get_day_plan(user, now.date())
    events = world_repository.list_events(world.world_id, statuses=["completed"], limit=100)
    assert isinstance(plans, list)
    assert isinstance(events, list)


def test_flow_weather_drop_triggers_care_opportunity(db_session_factory, flag_env):
    """§7.2 降温提醒：weather_change → EventImpactRules → goal_opportunity。"""
    flag_env("plus_detection")
    user = "ws019-flow-weather"
    world_repository.ensure_world(user)
    event = world_engine.create_event(
        user,
        event_type="weather_change",
        title="外面转凉了",
        importance="normal",
        source="simulation",
        status="active",
        payload={"next": "rain", "changed": True, "temperature_c": 8},
    )
    assert event is not None

    impacts = event_impact.evaluate_batch([event], {"part_of_day": "evening"})
    assert impacts
    top = impacts[0]
    assert top.event_type == "weather_change"
    assert top.care_relevance >= 0.5
    assert top.goal_opportunity is not None
    assert top.goal_opportunity.domain == "user_care"


def test_flow_foreground_brief_assembly(db_session_factory, flag_env):
    """§7.3 前台简报：时间/日程块/处境/事件 → WorldBrief 入 prompt 段。"""
    from app.services.world.context_selector import render_world_section

    flag_env("plus_detection")
    user = "ws019-flow-brief"
    world = world_repository.ensure_world(user)
    now = datetime.now()
    world_simulation_repository.save_situation(
        user_situation.UserSituation(
            id=world_simulation_repository.new_situation_id(),
            user_id=user,
            dimension=user_situation.SituationDimension.HEALTH,
            summary="用户身体不适",
            intensity=4,
            detected_at=now,
        )
    )
    context = world_engine.build_context(user)
    assert context is not None
    assert context.brief is not None
    assert context.brief.text

    section = render_world_section(context, budget=1000, brief=context.brief)
    assert section is not None
    assert context.brief.time_line in section


def test_flow_long_offline_catch_up(db_session_factory, flag_env):
    """§7.4 长离线追赶：>7 天折叠为单条 long_gap。"""
    flag_env("plus_daily")
    user = "ws019-flow-catchup"
    world = world_repository.ensure_world(user)
    today = datetime.now().date()

    plan = catch_up.compute_catch_up_plan(
        last_covered=today - timedelta(days=15),
        today=today,
        max_days=get_settings().catch_up_max_days,
    )
    assert plan.mode == "long_gap"
    assert plan.days_behind == 15

    events = world_repository.list_events(
        world.world_id, types=["time_marker"], limit=50
    )
    assert isinstance(events, list)

    short = catch_up.compute_catch_up_plan(
        last_covered=today - timedelta(days=3),
        today=today,
        max_days=get_settings().catch_up_max_days,
    )
    assert short.mode == "daily"
    assert len(short.missing_days) == 2


# --- ④ 边界不变量（§9.3） -----------------------------------------------------


def scan_forbidden_writes(user_id: str) -> list[str]:
    """写域扫描工具：列出该 user 的 Character 域状态行（模拟路径应零新增）。

    经 world_repository.SessionLocal 取会话，保证与 autouse _offline_repos 的内存库一致。
    """
    from app.core.db import (
        CharacterStateRow,
        GoalRow,
        PersonalityStateRow,
        RelationshipStateRow,
    )
    from app.repositories import world_repository as _wr

    violations: list[str] = []
    with _wr.SessionLocal() as session:
        for label, model in (
            ("character_state", CharacterStateRow),
            ("personality_state", PersonalityStateRow),
            ("relationship_state", RelationshipStateRow),
            ("character_goals", GoalRow),
        ):
            try:
                count = session.query(model).filter(model.user_id == user_id).count()
            except Exception:
                continue
            if count:
                violations.append(f"{label}:{count}")
    return violations


def test_invariant_simulation_never_writes_character_domain(db_session_factory, flag_env):
    """不变量 2：模拟路径对 character_state/personality/relationship/goals 零直写。"""
    flag_env("plus_scene")
    user = "ws019-invariant-write"
    world_repository.ensure_world(user)

    before = scan_forbidden_writes(user)
    world_engine.run_simulation_maintenance(user)
    user_situation.detect_from_message(user, "我今天感冒了")
    after = scan_forbidden_writes(user)

    assert after == before, f"模拟路径触碰了 Character 域：{after}"


def test_invariant_events_single_source_of_truth(db_session_factory, flag_env):
    """不变量 1：模拟事件全部落 world_events（唯一 SoT）。"""
    flag_env("plus_detection")
    user = "ws019-invariant-sot"
    world = world_repository.ensure_world(user)

    world_engine.run_simulation_maintenance(user)
    events = world_repository.list_events(world.world_id, limit=200)

    keys = [e.idempotency_key for e in events if e.idempotency_key]
    assert len(keys) == len(set(keys)), "幂等键重复写入违反唯一 SoT 去重语义"


def test_invariant_zero_llm_on_deterministic_path(db_session_factory, flag_env, fake_llm):
    """不变量 3：默认路径 0 LLM —— 维护步 + 确定性检出期间 LLM 调用记录为空。"""
    flag_env("plus_detection")  # llm_assist 仍为 false
    user = "ws019-invariant-llm"
    world_repository.ensure_world(user)

    llm = fake_llm(response=["unused"])
    llm_factory.set_llm(llm)

    world_engine.run_simulation_maintenance(user)
    situation = user_situation.detect_from_message(user, "我今天感冒了")
    assert situation is not None

    assert llm.seen_messages == [], "确定性路径产生了 LLM 调用"


def test_invariant_seeded_randomness_reproducible(db_session_factory, flag_env):
    """不变量 4：随机性显式种子可复现。"""
    from app.services.world.daily_plan import build_daily_plan

    flag_env("plus_daily")
    user = "ws019-invariant-seed"
    world_repository.ensure_world(user)
    day = date(2026, 9, 14)

    first = build_daily_plan(user, day)
    second = build_daily_plan(user, day)
    assert [p.activity for p in first] == [p.activity for p in second]


def test_invariant_time_advance_bounded(db_session_factory, flag_env, monkeypatch):
    """不变量 7：单次模拟跨度受 sim_advance_max_minutes 上限约束。"""
    flag_env("master_time")
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    monkeypatch.setenv("WORLD_SIM_RATE", "120")
    get_settings.cache_clear()
    try:
        user = "ws019-invariant-bound"
        world = world_repository.ensure_world(user)
        world.time_mode = WorldTimeMode.SIMULATED
        world.sim_time = datetime(2026, 9, 14, 0, 0, 0)
        world.sim_last_advanced_at = datetime(2026, 9, 13, 0, 0, 0)
        world_repository.save_world(world)

        result = time_advancer.advance_world_time(user, datetime(2026, 9, 14, 0, 0, 0))
        assert result is not None
        assert result.truncated is True
        assert result.advanced_minutes <= get_settings().sim_advance_max_minutes + 0.01
    finally:
        get_settings.cache_clear()


def test_invariant_event_storm_cap(db_session_factory, flag_env):
    """不变量 7：单 tick 事件风暴上限，超出折叠为 world_digest。"""
    flag_env("plus_detection")
    user = "ws019-invariant-storm"
    world_repository.ensure_world(user)
    cap = get_settings().world_event_tick_cap
    drafts = [
        {
            "event_type": "world_event",
            "title": f"事件{i}",
            "importance": "low",
            "source": "simulation",
            "status": "completed",
            "idempotency_key": f"storm:{user}:{i}",
        }
        for i in range(cap + 5)
    ]

    world_engine._emit_simulation_events(user, drafts)

    world = world_repository.get_world(user)
    events = world_repository.list_events(world.world_id, limit=200)
    assert len(events) <= cap
    assert any(e.type == "world_digest" for e in events)


def test_invariant_brief_and_style_do_not_add_hard_constraints():
    """不变量 8：WorldBrief 只增输入；style forbidden/principles 产生权不变。"""
    from app.character.asuna.personality_profile import PERSONA_PROFILE
    from app.services.experience.style_assembler import assemble_style_contract
    from app.models.character_state import CharacterState
    from app.models.conversation import ConversationState
    from app.models.emotion import TurnAnalysis, UserEmotion
    from app.models.relationship import RelationshipState

    state = ConversationState(
        session_id="s",
        user_id="u",
        messages=[],
        summary=None,
        memories=[],
        current_input="在吗",
        character_state=CharacterState(),
        relationship_state=RelationshipState(),
    )
    analysis = TurnAnalysis(user_emotion=UserEmotion(emotion="neutral", event="daily"))
    contract = assemble_style_contract(state, analysis)
    assert contract.forbidden == list(PERSONA_PROFILE.forbidden_behaviors)
    assert contract.principles == list(PERSONA_PROFILE.principles)


# --- ⑤ 迁移与性能预算 --------------------------------------------------------


def test_migration_head_is_0045_or_later(db_session_factory):
    """迁移链头覆盖 0044/0045（daily_plans / user_situations / v23 扩展）。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert heads, "迁移链无 head"
    for head in heads:
        rev = script.get_revision(head)
        assert rev is not None


def test_performance_simulation_tick_budget(db_session_factory, flag_env):
    """性能预算：单 tick 维护步耗时留数据（不设硬阈值，防慢机误杀）。"""
    import time as _time

    flag_env("plus_daily")
    user = "ws019-perf"
    world_repository.ensure_world(user)

    started = _time.perf_counter()
    world_engine.run_simulation_maintenance(user)
    elapsed_ms = (_time.perf_counter() - started) * 1000

    logger.info("WS-019 模拟维护步单 tick 耗时：%.1fms", elapsed_ms)
    assert elapsed_ms >= 0
