"""场景套件装配（testing.md §3）：声明式 JSON 场景 → EvaluationContext → 引擎合并。"""

import json
from datetime import datetime
from pathlib import Path

from app.models.evaluation import EvaluationSubjectKind
from app.models.evaluation_judge import (
    AutonomyJudgement,
    EmotionJudgement,
    MemoryJudgement,
    PersonaJudgement,
    ProactiveJudgeResult,
    TurnJudgeResult,
)
from app.services import evaluation_engine, evaluation_rules
from app.services.evaluation_context import (
    BehaviorSlice,
    EmotionSlice,
    EvaluationContext,
    MemoryRef,
    ProactiveSlice,
    RecentMessage,
    StateSlice,
)

SCENARIO_DIR = Path(__file__).parent / "scenarios"


def load_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        scenarios.extend(data)
    return scenarios


def build_context(scenario: dict) -> EvaluationContext:
    raw = scenario["context"]
    subject = scenario.get("subject", "turn")
    emotion_raw = raw.get("emotion", {})
    behavior_raw = raw.get("behavior")
    memories = [
        MemoryRef(
            id=m["id"],
            type=m.get("type", "user_fact"),
            content=m["content"],
            importance=m.get("importance", 0.0),
        )
        for m in raw.get("memories", [])
    ]
    context = EvaluationContext(
        subject=subject,
        subject_id=raw.get("subject_id", "scenario-1"),
        session_id=raw.get("session_id", "scenario-conv"),
        user_id=raw.get("user_id", "default-user"),
        mode=raw.get("mode", "default"),
        stage=raw.get("stage", "friend"),
        user_message=raw.get("user_message", ""),
        reply=raw.get("reply", ""),
        recent_messages=[
            RecentMessage(role=m["role"], content=m["content"])
            for m in raw.get("recent_messages", [])
        ],
        injected_memories=memories,
        emotion=EmotionSlice(
            mood_before=emotion_raw.get("mood_before"),
            mood_after=emotion_raw.get("mood_after"),
            intensity=emotion_raw.get("intensity"),
            event=emotion_raw.get("event"),
            magnitude=emotion_raw.get("magnitude"),
        ),
        state=StateSlice(
            mood=raw.get("state_mood"),
            intimacy=raw.get("intimacy", 0.3),
            stage=raw.get("stage", "friend"),
        ),
        request_id=raw.get("request_id", "scenario-request"),
    )
    if behavior_raw is not None:
        context.behavior = BehaviorSlice(
            max_action_desc=behavior_raw.get("max_action_desc", 1),
            physical_contact=behavior_raw.get("physical_contact", "none"),
            emotion_expression=behavior_raw.get("emotion_expression", "natural"),
            observed_action_count=behavior_raw.get("observed_action_count", 0),
            observed_contact_level=behavior_raw.get("observed_contact_level", "none"),
        )
    if raw.get("behavior_history") is not None:
        context.behavior_history = raw["behavior_history"]
    if subject == "proactive_action":
        proactive_raw = raw["proactive"]
        context.proactive = ProactiveSlice(
            action_id=proactive_raw.get("action_id", "scenario-action"),
            trigger_type=proactive_raw.get("trigger_type", "conversation_inactivity"),
            intention=proactive_raw.get("intention", "check_in"),
            reason=proactive_raw.get("reason", ""),
            delivered_at=datetime.fromisoformat(proactive_raw["delivered_at"]),
            payload_text=raw.get("reply", ""),
            previous_delivered_at=(
                datetime.fromisoformat(proactive_raw["previous_delivered_at"])
                if proactive_raw.get("previous_delivered_at")
                else None
            ),
            last_user_message_at=(
                datetime.fromisoformat(proactive_raw["last_user_message_at"])
                if proactive_raw.get("last_user_message_at")
                else None
            ),
            episode_attempts=proactive_raw.get("episode_attempts", 1),
        )
    return context


def build_judge(override: dict | None, subject: str):
    if not override:
        return None
    if subject == "proactive_action":
        return ProactiveJudgeResult(
            autonomy=AutonomyJudgement(**override["autonomy"]),
            persona=PersonaJudgement(**override["persona"]),
        )
    return TurnJudgeResult(
        persona=PersonaJudgement(**override["persona"]) if "persona" in override else None,
        emotion=EmotionJudgement(**override["emotion"]) if "emotion" in override else None,
        memory=MemoryJudgement(**override["memory"]) if "memory" in override else None,
    )


def run_scenario(scenario: dict):
    context = build_context(scenario)
    settings = evaluation_rules.get_settings()
    rule_issues = evaluation_rules.run_rules(context)
    eligible = evaluation_rules.eligible_dimensions(context.subject)
    rule_scores = evaluation_rules.compute_rule_scores(rule_issues, eligible, settings)
    judge_result = build_judge(scenario.get("judge_override"), context.subject)
    subject_kind = EvaluationSubjectKind(context.subject)
    return evaluation_engine.finalize_report(
        subject_kind,
        context,
        rule_issues,
        rule_scores,
        judge_result=judge_result,
        judge_sampled=judge_result is not None,
    )
