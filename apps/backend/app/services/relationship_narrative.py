"""叙事里程碑（REL-004）：Insight 驱动的白名单叙事里程碑。

触发链镜像 development_compile：reflector commit 后 insight_created 事件 →
过滤 scope=relationship 且 confidence 达标 → enqueue job（幂等键
relationship_narrative:{insight_id}，同 Insight 只触发一次）→ handler 重读
Insight（须仍 active）→ 白名单关键词全规则匹配 + 单日频控 → create_milestone
（走 V8.5 里程碑通道唯一写点：零 bonus、零 unlocks，meta 记录溯源）→
REL-001 通道转写 milestone_event 记忆。判定全规则，LLM Usage = NONE。
里程碑只增（HARD）：Insight 失效不回滚已落里程碑（记录的是经历事实）。
"""

import json
import logging
import time
from datetime import datetime

from app.core.db import BackgroundJobRow, InsightRow, SessionLocal
from app.core.settings import get_settings
from app.models.reflection import Insight
from app.repositories import (
    background_job_repository,
    relationship_milestone_repository,
)
from app.services.memory2.ingest import NARRATIVE_MILESTONE_PREFIX
from app.services.memory2 import job_worker as memory2_job_worker
from app.services.reflection import lifecycle as reflection_lifecycle

logger = logging.getLogger(__name__)

JOB_TYPE_NARRATIVE = "relationship_narrative_milestone"
STATUS_ACTIVE = "active"


def load_whitelist() -> dict:
    raw = get_settings().v2_relationship_narrative_whitelist_json
    try:
        table = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("叙事里程碑白名单解析失败，按空白名单处理")
        return {}
    return table if isinstance(table, dict) else {}


def on_insight_created(user_id: str, created: list[dict]) -> None:
    """创建事件回调：relationship 类高置信 Insight → enqueue 叙事里程碑 job。"""
    threshold = get_settings().v2_relationship_narrative_min_confidence
    for item in created or []:
        insight_id = item.get("insight_id")
        if not insight_id:
            continue
        if item.get("scope") != "relationship":
            continue
        if float(item.get("confidence") or 0.0) < threshold:
            continue
        background_job_repository.enqueue_job(
            JOB_TYPE_NARRATIVE,
            {"insight_id": insight_id, "user_id": user_id},
            f"{JOB_TYPE_NARRATIVE}:{insight_id}",
        )


def run_narrative_jobs() -> int:
    """job handler（无参签名对齐 _JOB_HANDLERS）：处理本类型 running 载荷。"""
    with SessionLocal() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(
                BackgroundJobRow.job_type == JOB_TYPE_NARRATIVE,
                BackgroundJobRow.status == "running",
            )
            .all()
        )
        insight_ids = [(row.payload or {}).get("insight_id") for row in rows]
    processed = 0
    for insight_id in insight_ids:
        if not insight_id:
            continue
        if process_insight(insight_id):
            processed += 1
    return processed


def process_insight(insight_id: str, trace=None) -> bool:
    """单 Insight 判定 + 频控 + 落账本；返回是否落叙事里程碑。"""
    started = time.perf_counter()
    insight = _load_eligible_insight(insight_id)
    if insight is None:
        _trace(trace, started, insight_id=insight_id, reason="skip_inactive")
        return False
    milestone_key = _match_whitelist(insight.statement)
    if milestone_key is None:
        _trace(trace, started, insight_id=insight_id, reason="no_whitelist_match")
        return False
    if not _daily_cap_available(insight.user_id):
        _trace(trace, started, insight_id=insight_id, reason="daily_cap")
        return False
    record = relationship_milestone_repository.create_milestone(
        user_id=insight.user_id,
        milestone_key=milestone_key,
        title=str(load_whitelist().get(milestone_key, {}).get("title") or ""),
        period_key="",
        meta={
            "source": "insight",
            "insight_id": insight_id,
            "matched_rule": milestone_key,
            "matched_at": datetime.now().isoformat(timespec="seconds"),
        },
        now=datetime.now(),
    )
    if record is None:
        _trace(trace, started, insight_id=insight_id, reason="already_exists")
        return False
    _trace(
        trace,
        started,
        insight_id=insight_id,
        reason="milestone",
        milestone_id=record.id,
        milestone_key=milestone_key,
    )
    return True


def register_narrative_listener() -> None:
    """Flag ON 编排层注册：job handler + insight_created 订阅（无注册方零行为）。"""

    memory2_job_worker.register_job_type(JOB_TYPE_NARRATIVE, run_narrative_jobs)
    reflection_lifecycle.register_insight_created_listener(on_insight_created)


def _load_eligible_insight(insight_id: str) -> Insight | None:
    settings = get_settings()
    with SessionLocal() as session:
        row = session.get(InsightRow, insight_id)
        if (
            row is None
            or row.status != STATUS_ACTIVE
            or row.scope != "relationship"
            or float(row.confidence) < settings.v2_relationship_narrative_min_confidence
        ):
            return None
        return Insight(
            id=row.id,
            user_id=row.user_id,
            character_id=row.character_id,
            statement=row.statement,
            type=row.type,
            confidence=row.confidence,
            scope=row.scope,
            status=row.status,
            run_id=row.run_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _match_whitelist(statement: str) -> str | None:
    for key in sorted(load_whitelist()):
        spec = load_whitelist()[key]
        if not isinstance(spec, dict):
            continue
        keywords = spec.get("keywords") or []
        if not keywords:
            continue
        hits = (keyword in statement for keyword in keywords)
        matched = all(hits) if spec.get("all", True) else any(hits)
        if matched:
            return key
    return None


def _daily_cap_available(user_id: str) -> bool:
    settings = get_settings()
    now = datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = relationship_milestone_repository.count_keys_since(
        user_id, NARRATIVE_MILESTONE_PREFIX, day_start
    )
    return count < settings.v2_relationship_narrative_daily_cap


def _trace(trace, started: float, **extra) -> None:
    if trace is None:
        return
    trace.record(
        "relationship_milestone",
        (time.perf_counter() - started) * 1000,
        "ok",
        **extra,
    )
