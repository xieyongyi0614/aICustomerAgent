"""V7.5 Offline 评估器（persistence.md §3 / autonomy-evaluation.md §3.2）。

从 DB 重建 EvaluationContext（fidelity=reconstructed）批量评估历史会话；
聚合统计（均值 / verdict 分布 / issue 直方图 / 主动 ack 率）持久化为
subject=offline_batch 单行（overall 为 NULL），聚合派生不建表。
"""

import logging
import uuid
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.evaluation import (
    EvaluationMeta,
    EvaluationReport,
    EvaluationSubjectKind,
)
from app.repositories import (
    conversation_repository,
    emotion_history_repository,
    evaluation_repository,
    memory_repository,
    proactive_repository,
)
from app.services import evaluation_engine, evaluation_rules
from app.services.evaluation_context import (
    EvaluationContext,
    MemoryRef,
    RecentMessage,
    StateSlice,
    build_digest,
)
from app.services.evaluation_rules import lexicons
from app.chains import evaluation_judge_chain
from app.repositories import character_state_repository, relationship_repository
from app.services.development.evaluation import (
    build_db_report as build_development_db_report,
)
from app.services.evaluation_context import collect_life_loop_slice, collect_goal_slice
from app.services.reflection.evaluation import (
    build_db_report as build_reflection_db_report,
)
from app.services.relationship_evaluation import (
    build_db_report as build_relationship_db_report,
)

logger = logging.getLogger(__name__)

REBUILD_MESSAGE_LIMIT = 1000
RECENT_WINDOW = 6
MEMORY_CLIP_CHARS = 40


async def evaluate_session(session_id: str, llm=None) -> dict:
    conversation = conversation_repository.find_conversation(session_id)
    if conversation is None:
        return {"error": "conversation_not_found", "session_id": session_id}
    user_id = conversation.user_id
    settings = get_settings()
    messages = conversation_repository.get_recent_messages(
        session_id, limit=REBUILD_MESSAGE_LIMIT
    )
    memories = memory_repository.list_active(user_id, "asuna", limit=50)
    memory_refs = [
        MemoryRef(
            id=str(m.id),
            type=m.type,
            content=m.content[:MEMORY_CLIP_CHARS],
            importance=m.importance,
        )
        for m in memories
    ]
    emotion_rows = emotion_history_repository.list_recent(user_id, limit=REBUILD_MESSAGE_LIMIT)
    state = _state_slice(user_id)

    turn_messages = [m for m in messages if m.role == "ai" and not m.is_proactive]
    emotion_by_turn = _pair_emotions(turn_messages, emotion_rows)

    results = []
    for index, message in enumerate(turn_messages):
        context = _rebuild_context(
            index, message, messages, memory_refs, emotion_by_turn, state, user_id, session_id
        )
        if context is None:
            continue
        rule_issues = evaluation_rules.run_rules(context)
        eligible = evaluation_rules.eligible_dimensions("turn")
        rule_scores = evaluation_rules.compute_rule_scores(rule_issues, eligible, settings)
        judge_result = None
        if llm is not None and evaluation_engine.should_sample(context.request_id, settings):
            judge_result = await evaluation_judge_chain.judge_turn(
                build_digest(context), character_id=context.character_id, llm=llm
            )
        report = evaluation_engine.finalize_report(
            EvaluationSubjectKind.TURN,
            context,
            rule_issues,
            rule_scores,
            judge_result=judge_result,
            judge_sampled=judge_result is not None,
            model_name=getattr(llm, "model_name", None),
        )
        results.append(
            {
                "turn_id": context.subject_id,
                "scores": {d.value: s.score for d, s in report.scores.items()},
                "verdict": report.verdict,
                "issues": [i.code.value for i in report.issues],
            }
        )

    aggregate = _aggregate(results, user_id, settings)
    _persist_run(session_id, user_id, aggregate)
    return {"run_id": aggregate["run_id"], "session_id": session_id, **aggregate}


def _state_slice(user_id: str) -> StateSlice:
    try:
        character = character_state_repository.get_state(user_id)
        relationship = relationship_repository.get_relationship(user_id)
        return StateSlice(
            mood=character.mood,
            energy=character.energy,
            stage=relationship.stage,
            intimacy=relationship.intimacy,
        )
    except Exception:
        logger.exception("离线状态切片读取失败，降级")
        return StateSlice()


def _pair_emotions(turn_messages, emotion_rows) -> dict[int, object]:
    """按从尾配对：第 i（从尾数）个对话轮 ↔ 第 i 条情绪史（V7.5 审计口径的近似重建）。"""
    paired: dict[int, object] = {}
    total = len(turn_messages)
    for offset, row in enumerate(reversed(emotion_rows)):
        index = total - 1 - offset
        if index >= 0:
            paired[index] = row
    return paired


def _rebuild_context(
    index, message, messages, memory_refs, emotion_by_turn, state, user_id, session_id
) -> EvaluationContext | None:
    prior = [m for m in messages if m.id < message.id]
    user_messages = [m for m in prior if m.role == "human"]
    user_message = user_messages[-1].content if user_messages else ""
    if not user_message:
        return None
    history = [m for m in prior][-RECENT_WINDOW:]
    emotion_row = emotion_by_turn.get(index)
    context = EvaluationContext(
        subject="turn",
        subject_id=str(message.id),
        session_id=session_id,
        user_id=user_id,
        stage=state.stage or "friend",
        user_message=user_message[:200],
        reply=message.content[:400],
        recent_messages=[
            RecentMessage(role=m.role, content=m.content[:120]) for m in history
        ],
        injected_memories=memory_refs,
        behavior_history=[lexicons.classify_actions(m.content) for m in prior if m.role == "ai"][
            -get_settings().evaluation_behavior_monotony_window :
        ],
        state=state,
        request_id=f"offline-{message.id}",
        fidelity="reconstructed",
    )
    if emotion_row is not None:
        context.emotion.mood_before = getattr(emotion_row, "mood_before", None)
        context.emotion.mood_after = getattr(emotion_row, "mood_after", None)
    return context


def _aggregate(results: list[dict], user_id: str, settings) -> dict:
    verdict_distribution: dict[str, int] = {}
    issue_histogram: dict[str, int] = {}
    dimension_sums: dict[str, list[float]] = {}
    for item in results:
        verdict_distribution[item["verdict"]] = (
            verdict_distribution.get(item["verdict"], 0) + 1
        )
        for code in item["issues"]:
            issue_histogram[code] = issue_histogram.get(code, 0) + 1
        for dimension, score in item["scores"].items():
            dimension_sums.setdefault(dimension, []).append(score)
    mean_scores = {
        dimension: round(sum(scores) / len(scores), 4)
        for dimension, scores in dimension_sums.items()
        if scores
    }
    proactive_stats = _proactive_outcome_stats(user_id, settings)
    return {
        "run_id": uuid.uuid4().hex,
        "turns_evaluated": len(results),
        "mean_scores": mean_scores,
        "verdict_distribution": verdict_distribution,
        "issue_histogram": issue_histogram,
        "proactive_stats": proactive_stats,
        "reflection": _reflection_stats(settings),
        "development": _development_stats(settings),
        "relationship": _relationship_stats(settings),
        "life_loop": _life_loop_stats(user_id),
        "goal": _goal_stats(user_id),
        "context_fidelity": "reconstructed",
    }


def _reflection_stats(settings) -> dict:
    """REF-006：reflection 小节（只读 DB 统计；Flag OFF 为空）。"""
    try:
        return build_reflection_db_report()
    except Exception:
        logger.exception("reflection 小节统计失败，降级为空")
        return {}


def _development_stats(settings) -> dict:
    """DEV-005：development 小节（只读 DB 统计；Flag OFF 为空）。"""
    try:
        return build_development_db_report()
    except Exception:
        logger.exception("development 小节统计失败，降级为空")
        return {}


def _relationship_stats(settings) -> dict:
    """REL-004：relationship 小节（只读 DB 统计；Flag OFF 为空）。"""
    try:
        return build_relationship_db_report()
    except Exception:
        logger.exception("relationship 小节统计失败，降级为空")
        return {}


def _proactive_outcome_stats(user_id: str, settings) -> dict:
    """观察窗结果统计（仅离线）：24h 内无 ack 无回复记 LOW_OUTCOME 直方图信号。"""
    try:
        history = proactive_repository.list_delivered_history(user_id, limit=50)
        now = datetime.now()
        window = timedelta(hours=settings.evaluation_proactive_reply_window_hours)
        delivered = 0
        acked = 0
        low_outcome = 0
        for action in history:
            if action.delivered_at is None:
                continue
            delivered += 1
            if action.acked_at is not None:
                acked += 1
            elif now - action.delivered_at > window:
                low_outcome += 1
        return {
            "delivered": delivered,
            "acked": acked,
            "low_outcome": low_outcome,
            "ack_rate": round(acked / delivered, 4) if delivered else None,
        }
    except Exception:
        logger.exception("主动结果统计失败，降级")
        return {"delivered": 0, "acked": 0, "low_outcome": 0, "ack_rate": None}


def _persist_run(session_id: str, user_id: str, aggregate: dict) -> None:
    try:
        report = EvaluationReport(
            id=aggregate["run_id"],
            subject=EvaluationSubjectKind.OFFLINE_BATCH,
            subject_id=aggregate["run_id"],
            session_id=session_id,
            user_id=user_id,
            scores={},
            overall_score=None,
            verdict="pass",
            issues=[],
            context_digest=aggregate,
            meta=EvaluationMeta(context_fidelity="reconstructed", judge_used=False),
            created_at=datetime.now(),
        )
        evaluation_repository.save(report)
    except Exception:
        logger.exception("离线评估运行记录落库失败，仅返回聚合")


def _life_loop_stats(user_id: str) -> dict:
    """LIFE-006：life_loop 小节（只读 DB 统计；E-LIFE-02/03/05 汇总面）。"""
    try:
        from datetime import datetime as _dt


        slice_ = collect_life_loop_slice(user_id, now=_dt.now(), window_hours=24.0)
        autonomy_runs = [r for r in slice_.runs if r.kind == "autonomy"]
        complete = sum(
            1
            for r in autonomy_runs
            if r.status == "done" and "decision" in r.step_names
        )
        terminal_triggers = [
            t for t in slice_.triggers if t.status in ("done", "cancelled")
        ]
        provenanced = sum(
            1 for p in slice_.delivered_proactive if p.provenanced
        )
        return {
            "runs_total": len(autonomy_runs),
            "runs_complete": complete,
            "runs_complete_rate": (
                round(complete / len(autonomy_runs), 4) if autonomy_runs else None
            ),
            "runs_aborted": sum(
                1 for r in autonomy_runs if r.status == "aborted"
            ),
            "triggers_total": len(slice_.triggers),
            "triggers_terminal_rate": (
                round(len(terminal_triggers) / len(slice_.triggers), 4)
                if slice_.triggers
                else None
            ),
            "trigger_orphans": sum(1 for t in slice_.triggers if t.stale),
            "proactive_delivered": len(slice_.delivered_proactive),
            "proactive_provenance_rate": (
                round(provenanced / len(slice_.delivered_proactive), 4)
                if slice_.delivered_proactive
                else None
            ),
            "day_llm_calls": slice_.day_llm_calls,
            "day_llm_call_limit": slice_.day_llm_call_limit,
            "outbox_dead_letters": slice_.outbox_dead_letters,
        }
    except Exception:
        logger.exception("life_loop 小节统计失败，降级为空")
        return {}


def _goal_stats(user_id: str) -> dict:
    """AUT-005：goal 小节（只读 DB 统计；E-AUT-01~03 汇总面）。"""
    try:
        from datetime import datetime as _dt


        slice_ = collect_goal_slice(user_id, now=_dt.now())
        terminal = [g for g in slice_.goals if g.status != "active"]
        attributed = {
            (ref.goal_id, ref.decision) for ref in slice_.lifecycles
        }
        consistent = sum(
            1
            for g in terminal
            if (g.goal_id, g.status) in attributed
        )
        plans_by_status = {}
        for plan in slice_.plans:
            plans_by_status[plan.status] = plans_by_status.get(plan.status, 0) + 1
        return {
            "goals_total": len(slice_.goals),
            "goals_terminal": len(terminal),
            "terminal_attributed": consistent,
            "terminal_attribution_rate": (
                round(consistent / len(terminal), 4) if terminal else None
            ),
            "plans_total": len(slice_.plans),
            "plans_active": plans_by_status.get("active", 0),
            "plans_rejected": plans_by_status.get("rejected", 0),
            "lifecycle_records": len(slice_.lifecycles),
        }
    except Exception:
        logger.exception("goal 小节统计失败，降级为空")
        return {}
