"""Agent State Assembler（V2.1.0 AGENT-002）：统一意识状态投影，0 LLM。

六只读源 → 规则合成七组件 Snapshot；各域 SoT 零改动、本模块零写入业务域。
任一来源失败按空值降级；Personality 读取带幂等种子（AGENT-005 接管写入）。
"""

import logging
from datetime import datetime

from app.core import timeutil
from app.character.asuna import evolution
from app.core.settings import get_settings
from app.models.agent_state import (
    AgentStateSnapshot,
    CurrentFocus,
    InterestTopic,
    PersonalityAxisState,
)
from app.repositories import (
    action_repository,
    agent_state_snapshot_repository as snapshot_repo,
    goal_repository,
    memory_repository,
    personality_state_repository,
)
from app.services.conversation import state as state_service
from app.services.development import aggregate as development_aggregate
from app.application import agent_state_context

logger = logging.getLogger(__name__)

_IN_PROGRESS_ACTION_STATUSES = ("created", "planned", "executing")


def assemble(user_id: str, character_id: str = "asuna", now: datetime | None = None) -> AgentStateSnapshot:
    now = timeutil.ensure_aware(now) or timeutil.now()
    settings = get_settings()

    character, relationship = _load_states(user_id)
    goals = _load_goals(user_id)
    preferences = _load_preferences(user_id, character_id)
    world_facts = _load_world_facts(user_id)
    memories = _load_salient_memories(user_id, settings)
    personality = _load_personality(user_id, character_id)

    return AgentStateSnapshot(
        mood=character.mood,
        energy=character.energy,
        intensity=character.intensity,
        inner_state=character.inner_state or "",
        emotion_cause=character.cause or "",
        relationship={
            "stage": getattr(relationship, "stage", None),
            "intimacy": round(float(getattr(relationship, "intimacy", 0.0) or 0.0), 3),
            "trust": round(float(getattr(relationship, "trust", 0.0) or 0.0), 3),
            "tension": round(float(getattr(relationship, "tension", 0.0) or 0.0), 3),
        },
        interest_focus=_compose_interest(
            goals, preferences, world_facts, memories, settings
        ),
        current_focus=_compose_focus(character, goals, user_id),
        personality=personality,
    )


def assemble_snapshot(user_id: str, character_id: str = "asuna") -> AgentStateSnapshot:
    """阻塞组装（供 to_thread 调用）；激活走 activate_run_state。"""
    return assemble(user_id, character_id)


def activate_run_state(snapshot: AgentStateSnapshot, run) -> None:
    """主协程上下文调用：激活 contextvar 通道 + 存档判定（前台/后台共用）。"""
    agent_state_context.set_snapshot(snapshot)
    run.data["state_snapshot_version"] = snapshot.snapshot_version
    try:
        from app.application.agent_state_archiver import archive_if_significant

        archive_if_significant(
            run.user_id, "asuna", snapshot, run_id=run.run_id
        )
    except Exception:
        logger.exception("快照存档失败，不影响 Run")


def reset_run_state(run) -> None:
    agent_state_context.clear()
    run.data.pop("state_snapshot_version", None)


def run_state_snapshot_stage(user_id: str, run) -> dict:
    """autonomous_tick 的 state_snapshot 阶段实现（controller 经 run_stage_async 调用）。"""
    snapshot = assemble(user_id)
    activate_run_state(snapshot, run)
    top = snapshot.interest_focus[0].topic if snapshot.interest_focus else ""
    return {
        "status": "ok",
        "snapshot_version": snapshot.snapshot_version,
        "top_interest": top,
    }


def _load_states(user_id: str):
    try:
        return state_service.load_states(user_id)
    except Exception:
        logger.exception("状态读取失败，按默认值降级")
        from app.models.character_state import CharacterState
        from app.models.relationship import RelationshipState

        return CharacterState(), RelationshipState()


def _load_goals(user_id: str) -> list:
    try:
        return goal_repository.list_active(user_id)
    except Exception:
        logger.exception("活跃目标读取失败，按空降级")
        return []


def _load_preferences(user_id: str, character_id: str) -> list:
    try:
        return [
            mod
            for mod in development_aggregate.list_active_modulations(
                user_id, character_id
            )
            if mod.kind == "preference"
        ]
    except Exception:
        logger.exception("偏好读取失败，按空降级")
        return []


def _load_world_facts(user_id: str) -> dict:
    try:
        from app.application import world_engine

        return world_engine.collect_facts(user_id) or {}
    except Exception:
        logger.exception("世界事实读取失败，按空降级")
        return {}


def _load_salient_memories(user_id: str, settings) -> list:
    try:
        return memory_repository.list_top_salience(
            user_id,
            min_salience=settings.life_loop_memory_min_salience,
            limit=5,
        )
    except Exception:
        logger.exception("显著记忆读取失败，按空降级")
        return []


def ensure_personality_baseline(user_id: str | None, character_id: str = "asuna") -> bool:
    """AGENT-002 人格基线播种（显式初始化步骤，非快照读路径副作用）。

    由 Run Open 调用：Run 生命周期内的显式初始化，保证组装阶段为纯只读。
    """
    if not user_id:
        return False
    try:
        return personality_state_repository.seed_if_absent(
            user_id, evolution.PERSONALITY_AXES, character_id
        )
    except Exception:
        logger.exception("人格基线播种失败，不影响 Run")
        return False


def _load_personality(user_id: str, character_id: str) -> list[PersonalityAxisState]:
    try:
        rows = personality_state_repository.get_all(user_id, character_id)
        return [
            PersonalityAxisState(
                axis=row.axis,
                baseline=row.baseline,
                current=row.current,
                bound_min=row.bound_min,
                bound_max=row.bound_max,
            )
            for row in rows
        ]
    except Exception:
        logger.exception("人格轴读取失败，按空降级")
        return []


def _compose_interest(goals, preferences, world_facts, memories, settings) -> list[InterestTopic]:
    scores: dict[str, float] = {}

    def _add(topic: str, score: float) -> None:
        topic = (topic or "").strip()[:40]
        if topic:
            scores[topic] = scores.get(topic, 0.0) + max(score, 0.0)

    for goal in goals:
        _add(
            goal.description,
            settings.interest_weight_goal * (goal.priority / 5.0),
        )
    for mod in preferences:
        strength = float(getattr(mod, "strength", 0.0) or 0.0)
        _add(mod.key, settings.interest_weight_preference * strength)
    for memory in memories:
        salience = float(getattr(memory, "salience", 0.0) or 0.0)
        _add(memory.content[:24], settings.interest_weight_memory * salience)
    for event in world_facts.get("salient_events") or []:
        title = (
            event.get("title") or event.get("description")
            if isinstance(event, dict)
            else str(event)
        )
        _add(str(title or ""), settings.interest_weight_world)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_n = max(settings.interest_top_n, 0)
    return [InterestTopic(topic=topic, score=round(score, 4)) for topic, score in ranked[:top_n]]


def _compose_focus(character, goals, user_id: str) -> CurrentFocus:
    goal = next(
        (g for g in goals if getattr(g, "layer", None) == "short_term"),
        goals[0] if goals else None,
    )
    action = ""
    try:
        for record in action_repository.list_records(user_id, limit=20):
            if record.status in _IN_PROGRESS_ACTION_STATUSES:
                action = f"{record.action_type}:{record.status}"
                break
    except Exception:
        logger.exception("进行中行动读取失败，焦点行动为空")
    return CurrentFocus(
        topic=character.current_topic or "",
        goal_id=getattr(goal, "id", None),
        goal_description=getattr(goal, "description", "") or "",
        action=action,
        attention="user",
    )

