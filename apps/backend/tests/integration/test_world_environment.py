"""V8-009 环境系统：天气解释、时段光照建议、manual 覆盖、情绪零写回。"""

from datetime import datetime

from app.core import timeutil
from app.application import world_engine, world_engine as engine_module
from app.repositories import world_repository
from app.services.world.context_selector import environment_lighting_suggestion


def test_manual_environment_and_interpreter_weather(db_session_factory):
    world_engine.ensure_world("default-user")
    world_engine.run_turn_update("default-user", "外面下雨了记得关窗")
    world = world_engine.get_world("default-user")
    assert world.environment.weather == "rain"
    assert world.environment.updated_by == "interpreter"


def test_lighting_suggestion_applied_once_and_respects_manual(db_session_factory, override_settings):
    override_settings(world_time_mode="story")
    world_engine.ensure_world("default-user")
    evening = timeutil.ensure_aware(datetime(2026, 9, 1, 20, 0))
    world_engine.advance_time("default-user", evening - timeutil.now())
    world_engine.run_turn_update("default-user", "今天聊了聊天")
    world = world_engine.get_world("default-user")
    assert world.environment.lighting == environment_lighting_suggestion(evening)

    world_engine.set_environment("default-user", lighting="bright")
    world_engine.run_turn_update("default-user", "又聊了聊天")
    env = world_engine.get_world("default-user").environment
    assert env.lighting == "bright"
    assert env.updated_by == "manual"


def test_environment_never_touches_character_state(db_session_factory):
    from app.repositories import (
        character_state_repository,
        emotion_history_repository,
        relationship_repository,
    )

    world_engine.ensure_world("default-user")
    world_engine.run_turn_update("default-user", "外面下雨了")
    with character_state_repository.SessionLocal() as session:
        from app.core.db import CharacterStateRow, EmotionHistoryRow, RelationshipStateRow

        assert session.query(CharacterStateRow).count() == 0
        assert session.query(EmotionHistoryRow).count() == 0
        assert session.query(RelationshipStateRow).count() == 0
