"""V2.3.0 Daily Life（architecture.md §5.3）：日程具象化与当日计划。

种子 = (user_id, plan_date, ROUTINE_VERSION)，同输入同计划（G6）；
用户影响绑定优先级：显式承诺 > 用户处境 > 模板变体；全部确定性。
"""

import logging
import random
from datetime import date, datetime, timedelta

from app.character.asuna.calendar import holiday_of
from app.character.asuna.routine import ROUTINE_VERSION, routine_template
from app.core.settings import get_settings
from app.models.world_simulation import (
    DailyPlan,
    DailyPlanStatus,
    DailyPlanVariability,
    SituationDimension,
    SituationStatus,
)
from app.repositories import (
    memory_repository,
    world_repository,
    world_simulation_repository as plan_repo,
)

logger = logging.getLogger(__name__)

JITTER_MINUTES = 30

_SITUATION_INFLUENCE = {
    SituationDimension.HEALTH.value: {
        "activity": "照顾用户",
        "location_id": "home.living_room",
        "note": "用户健康处境",
        "energy_bias": 1,
    },
    SituationDimension.WORK_PRESSURE.value: {
        "activity": "轻松陪伴",
        "location_id": "home.living_room",
        "note": "用户工作压力处境",
        "energy_bias": 0,
    },
    SituationDimension.TRAVEL.value: {
        "activity": "等候用户消息",
        "location_id": "home.living_room",
        "note": "用户外出处境",
        "energy_bias": 0,
    },
}


def day_type_of(day: date) -> str:
    if holiday_of(day) is not None:
        return "holiday"
    if day.weekday() >= 5:
        return "weekend"
    return "weekday"


def _active_situations(user_id: str) -> list:
    return plan_repo.list_situations(
        user_id, statuses=(SituationStatus.ACTIVE,)
    )


def _pick_situation_influence(situations: list) -> dict | None:
    ranked = sorted(situations, key=lambda s: s.intensity, reverse=True)
    for situation in ranked:
        influence = _SITUATION_INFLUENCE.get(situation.dimension.value)
        if influence is not None:
            return {**influence, "note": f"{influence['note']}（强度{situation.intensity}）"}
    return None


def _commitment_directive(user_id: str, day: date) -> str | None:
    try:
        commitments = memory_repository.list_active_by_types(
            user_id, "asuna", ["commitment"]
        )
    except Exception:
        logger.exception("承诺记忆读取失败，跳过承诺绑定")
        return None
    today_marker = "今天" if day == date.today() else None
    tomorrow_marker = "明天" if day == date.today() + timedelta(days=1) else None
    for memory in commitments:
        content = memory.content or ""
        if (today_marker and today_marker in content) or (
            tomorrow_marker and tomorrow_marker in content
        ):
            return content
    return None


def _resolve_variant(block: dict, rng: random.Random) -> tuple[str, str, DailyPlanVariability]:
    variability = block.get("variability") or {"mode": "fixed"}
    if variability.get("mode") != "variant":
        return block["activity"], block["location_id"], DailyPlanVariability.FIXED
    alternatives = variability.get("alternatives") or []
    if not alternatives:
        return block["activity"], block["location_id"], DailyPlanVariability.FIXED
    total = sum(item.get("weight", 1) for item in alternatives)
    pick = rng.uniform(0, total)
    cursor = 0.0
    chosen = alternatives[-1]
    for item in alternatives:
        cursor += item.get("weight", 1)
        if pick <= cursor:
            chosen = item
            break
    return chosen["activity"], chosen["location_id"], DailyPlanVariability.VARIANT


def _jitter(block: dict, rng: random.Random, variability: DailyPlanVariability) -> tuple[int, int]:
    start = block["start_min"]
    end = block["end_min"]
    if variability is DailyPlanVariability.FIXED:
        return start, end
    offset = rng.randint(-JITTER_MINUTES, JITTER_MINUTES)
    new_start = max(0, min(1438, start + offset))
    new_end = max(new_start + 15, min(1439, end + offset))
    return new_start, new_end


def build_daily_plan(user_id: str, day: date, now: datetime | None = None) -> list[DailyPlan]:
    """具象化当日计划：种子随机 + 用户影响；单事务 supersede 旧行并写入新行。"""
    current = now or datetime.now()
    template = routine_template(day_type_of(day))
    rng = random.Random(f"{user_id}|{day.isoformat()}|{ROUTINE_VERSION}")
    situations = _active_situations(user_id)
    situation_influence = _pick_situation_influence(situations)
    directive = _commitment_directive(user_id, day)
    directive_applied = False
    directive_target = max(
        (block["seq"] for block in template if block.get("user_influencable")),
        default=None,
    )

    plan_repo.supersede_open_plans(user_id, day)
    plan_repo.supersede_open_plans(user_id, day)
    plans: list[DailyPlan] = []
    for block in template:
        activity, location_id, variability = _resolve_variant(block, rng)
        start, end = _jitter(block, rng, variability)
        note = None
        if block["seq"] == directive_target and directive is not None:
            activity = f"兑现承诺：{directive[:30]}"
            variability = DailyPlanVariability.USER_INFLUENCED
            note = "用户承诺"
            directive_applied = True
        elif situation_influence is not None and block.get("user_influencable"):
            activity = situation_influence["activity"]
            location_id = situation_influence["location_id"]
            variability = DailyPlanVariability.USER_INFLUENCED
            note = situation_influence["note"]
        plans.append(
            DailyPlan(
                id=plan_repo.new_plan_id(),
                user_id=user_id,
                plan_date=day,
                seq=block["seq"],
                part_of_day=block["part"],
                start_minutes=start,
                end_minutes=end,
                activity=activity[:50],
                location_id=location_id,
                variability_source=variability,
                status=DailyPlanStatus.PLANNED,
                routine_version=ROUTINE_VERSION,
                note=note,
                created_at=current,
            )
        )
    plan_repo.replace_day_plans(plans)
    if directive is not None and not directive_applied:
        logger.info("承诺记忆无可绑定日程块（user=%s day=%s）", user_id, day)
    return plans


def ensure_day_plan(user_id: str, day: date, now: datetime | None = None) -> list[DailyPlan]:
    """自愈入口：当日无 open 计划时构建（进程重启/漏标记兜底）。"""
    if plan_repo.has_open_plans(user_id, day):
        return plan_repo.get_day_plans(user_id, day, plan_repo.OPEN_PLAN_STATUSES)
    return build_daily_plan(user_id, day, now)


def get_day_plan(user_id: str, day: date) -> list[DailyPlan]:
    return plan_repo.get_day_plans(user_id, day, plan_repo.OPEN_PLAN_STATUSES)


def get_current_block(user_id: str, day: date, minutes: int) -> DailyPlan | None:
    """当前活动块：优先 active，其次时间窗命中的 planned 块。"""
    plans = get_day_plan(user_id, day)
    for plan in plans:
        if plan.status == DailyPlanStatus.ACTIVE:
            return plan
    for plan in plans:
        if plan.status == DailyPlanStatus.PLANNED and plan.start_minutes <= minutes < plan.end_minutes:
            return plan
    return None


def plan_topics(user_id: str, day: date) -> list[str]:
    """今日已完成块的话题素材（主动消息取材用）。"""
    completed = plan_repo.get_day_plans(user_id, day, (DailyPlanStatus.COMPLETED,))
    topics: list[str] = []
    template_by_seq = {
        block["seq"]: block for block in routine_template(day_type_of(day))
    }
    for plan in completed:
        block = template_by_seq.get(plan.seq) or {}
        topics.extend(block.get("topics") or [])
    return topics


def prune_expired_plans(user_id: str, today: date) -> int:
    """清理超过保留期的历史计划行，返回删除条数（保留期见 daily_plan_retention_days）。

    仅按日期裁剪，不区分状态：保留期内的 COMPLETED 行仍可支撑 plan_topics；
    超期后其话题素材已无引用价值。
    """
    retention_days = get_settings().daily_plan_retention_days
    if retention_days <= 0:
        return 0
    cutoff = today - timedelta(days=retention_days)
    try:
        removed = plan_repo.prune_plans_before(user_id, cutoff)
    except Exception:
        logger.exception("历史计划清理失败（user=%s cutoff=%s）", user_id, cutoff)
        return 0
    if removed:
        logger.info("清理历史计划 %s 条（user=%s cutoff=%s）", removed, user_id, cutoff)
    return removed


def _emit_life_event(user_id: str, plan: DailyPlan, kind: str, now: datetime) -> None:
    from app.application import world_engine

    importance = "normal" if plan.variability_source == DailyPlanVariability.USER_INFLUENCED else "low"
    world_engine.create_event(
        user_id,
        event_type="life_event",
        title=f"{plan.activity}（{kind}）",
        importance=importance,
        source="daily_life",
        status="completed",
        payload={
            "kind": kind,
            "plan_id": plan.id,
            "seq": plan.seq,
            "activity": plan.activity,
            "location_id": plan.location_id,
            "variability_source": plan.variability_source.value,
            "date": plan.plan_date.isoformat(),
        },
        idempotency_key=f"life:{plan.id}:{kind}",
    )


def advance_daily_plan(user_id: str, now: datetime) -> dict:
    """块推进：过点闭合/错点跳过/到点激活/位置迁移；单用户单次调用。"""
    from app.services.world import movement

    world = world_repository.get_world(user_id)
    if world is None:
        return {"completed": [], "skipped": [], "activated": None, "moved": False}
    day = now.date()
    minutes = now.hour * 60 + now.minute
    plans = get_day_plan(user_id, day)
    summary = {"completed": [], "skipped": [], "activated": None, "moved": False}

    for plan in plans:
        if plan.status == DailyPlanStatus.ACTIVE and plan.end_minutes <= minutes:
            plan.status = DailyPlanStatus.COMPLETED
            plan_repo.save_plan(plan)
            _emit_life_event(user_id, plan, "activity_done", now)
            summary["completed"].append(plan.id)
        elif plan.status == DailyPlanStatus.PLANNED and plan.end_minutes <= minutes:
            plan.status = DailyPlanStatus.SKIPPED
            plan_repo.save_plan(plan)
            _emit_life_event(user_id, plan, "block_skipped", now)
            summary["skipped"].append(plan.id)

    current = None
    for plan in plans:
        if (
            plan.status == DailyPlanStatus.PLANNED
            and plan.start_minutes <= minutes < plan.end_minutes
        ):
            plan.status = DailyPlanStatus.ACTIVE
            plan_repo.save_plan(plan)
            summary["activated"] = plan.id
            current = plan
            break

    if current is None:
        for plan in get_day_plan(user_id, day):
            if plan.status == DailyPlanStatus.ACTIVE:
                current = plan
                break

    if current is not None and current.location_id != world.current_location:
        move = movement.apply(
            user_id,
            current.location_id,
            source=movement.SOURCE_SCHEDULE,
            reason=f"block:{current.activity}",
            now=now,
        )
        summary["moved"] = move.applied
        summary["move_skipped"] = move.skipped_reason
    return summary
