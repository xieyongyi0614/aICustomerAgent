"""情景聚合（MEV-006）：同窗同主题的情景碎片 → 一条上层情景候选。

设计要点（对应 `docs/version/v6.0.0/tasks/MEV-006.md` §4）：

- **零 LLM、零随机**（D1）：归组（`theme_key`）与拼接（`aggregate_content`）全部确定性纯计算，
  同一输入恒定输出——幂等因此可被单测证明；
- **幂等键不含时间**（D2/D3）：`source_id = episodic:{theme_key}:{组内 id 升序}`，窗口只用于选材，
  故跨 tick 的同主题片段复用同一候选（命中 `uq_memory_candidates_source` 即返回既有行）；
- **防递归硬护栏**（D4）：`source_ref.table == SOURCE_TABLE_AGGREGATE` 的记忆一律排除，
  否则每轮都会在产物之上再聚合；
- **唯一写面**（D5）：只经 `ingest.create_candidate`，落库与转正交给既有三段评估链路；
- **单组失败隔离**（D8）：一组脏数据不阻断整轮，整体不抛（连接级错误交 job 退避）。

注册：job 类型与周期 hook 由同域 `job_worker` 侧挂载（本模块不反向 import 它，避免循环导入）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.db import Memory, SessionLocal
from app.core.settings import get_settings
from app.repositories import background_job_repository
from app.services.memory import ingest as memory_ingest

logger = logging.getLogger(__name__)

JOB_TYPE_MEMORY_EPISODIC_AGGREGATE = "memory_episodic_aggregate"

MODE_AUTO = "auto"

SOURCE_TABLE_AGGREGATE = "memory_aggregate"
PROPOSED_TYPE_AGGREGATE = "experience"
AGGREGATE_LAYER = "episodic"
AGGREGATE_SOURCE_KIND = "user_derived"

MISC_THEME = "misc"
"""无主题命中：**不聚合**（宁缺毋滥）——避免把互不相干的片段煮成一锅。"""

CONTENT_SEPARATOR = "；"
CONTENT_ITEM_MAX_CHARS = 60
CONTENT_MAX_CHARS = 500
"""聚合内容上限：与产品读面 `CONTENT_MAX` 同量纲，防单条聚合吃掉 prompt 预算。"""

DEFAULT_SALIENCE = 0.5
"""组内 salience 全为空时的回落（与检索侧 `_DEFAULT_SALIENCE` 同值）。"""

THEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("outdoor", ("露营", "徒步", "爬山", "野餐", "公园", "海边", "郊游", "骑行")),
    ("career", ("面试", "入职", "转正", "晋升", "汇报", "出差", "项目", "加班", "离职")),
    ("health", ("体检", "医院", "看病", "复诊", "生病", "感冒", "失眠", "健身")),
    ("study", ("考试", "课程", "复习", "论文", "证书", "报名", "学习")),
    ("food", ("做饭", "餐厅", "外卖", "咖啡", "火锅", "烘焙", "早餐", "晚饭")),
    ("travel", ("旅行", "机票", "酒店", "行程", "景点", "签证", "返程")),
    ("social", ("朋友", "同事", "聚会", "生日", "礼物", "婚礼", "同学")),
)
"""主题词表（★ 冻结，顺序即优先级）：子串命中即定主题；零 LLM、确定性。"""


def theme_key(memory) -> str:
    """纯函数：`{source_table}:{theme}`；无主题命中 → `misc`。同一输入恒定输出。"""
    table = str((memory.source_ref or {}).get("table") or "memories")
    return f"{table}:{_theme_of(memory.content or '')}"


def _theme_of(content: str) -> str:
    for theme, keywords in THEME_KEYWORDS:
        if any(keyword in content for keyword in keywords):
            return theme
    return MISC_THEME


def aggregate_content(memories) -> str:
    """按 `created_at` 升序拼接组内内容（单条截断 + 总量截断），确定性、不引入改写。"""
    ordered = sorted(memories, key=lambda memory: (memory.created_at, memory.id))
    parts = []
    for memory in ordered:
        text = (memory.content or "").strip()
        if not text:
            continue
        parts.append(text[:CONTENT_ITEM_MAX_CHARS])
    return CONTENT_SEPARATOR.join(parts)[:CONTENT_MAX_CHARS]


def aggregate_salience(memories) -> float:
    """取组内 salience **最大值**（不放大、不累加，D9）。"""
    values = [memory.salience for memory in memories if memory.salience is not None]
    return max(values) if values else DEFAULT_SALIENCE


def source_id_for(theme: str, source_ids) -> str:
    """幂等键：`episodic:{theme_key}:{组内 id 升序逗号连接}`（★ 不得含时间戳，D2）。"""
    return f"episodic:{theme}:{','.join(sorted(source_ids))}"


def _select_window(now: datetime) -> list:
    """只读选材：active ∧ layer=episodic ∧ type=experience ∧ 窗口内（D4 在归组侧二次过滤）。"""
    settings = get_settings()
    window_start = now - timedelta(hours=settings.memory_episodic_window_hours)
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(
                Memory.status == "active",
                Memory.layer == AGGREGATE_LAYER,
                Memory.type == PROPOSED_TYPE_AGGREGATE,
                Memory.created_at >= window_start,
                Memory.created_at <= now,
            )
            .order_by(Memory.created_at.asc(), Memory.id.asc())
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _is_aggregate(memory) -> bool:
    return str((memory.source_ref or {}).get("table") or "") == SOURCE_TABLE_AGGREGATE


def _group(memories) -> dict[tuple[str, str, str], list]:
    """组键 `(user_id, character_id, theme_key)`（不含窗口，D3）；聚合产物不入组（D4）。"""
    groups: dict[tuple[str, str, str], list] = {}
    for memory in memories:
        if _is_aggregate(memory):
            continue
        key = (memory.user_id, memory.character_id or "*", theme_key(memory))
        groups.setdefault(key, []).append(memory)
    return groups


def _candidate_exists(source_id: str) -> bool:
    """候选是否已存在（幂等键）：已存在的组不再占用本轮预算，让剩余组能推进（D7）。"""
    from app.core.db import MemoryCandidateRow

    with SessionLocal() as session:
        return (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.source_table == SOURCE_TABLE_AGGREGATE,
                MemoryCandidateRow.source_id == source_id,
            )
            .first()
            is not None
        )


def aggregate_once(now: datetime | None = None) -> dict:
    """执行一轮聚合；返回统计（供日志/观测），单组失败隔离。

    `mode != auto` → **零动作**（不查库）：闸设在最内层入口，hook / job / 直调三条路都受控。
    """
    settings = get_settings()
    stats = {
        "groups": 0,
        "created": 0,
        "existing": 0,
        "skipped_small": 0,
        "skipped_misc": 0,
        "failed": 0,
    }
    if settings.memory_episodic_mode != MODE_AUTO:
        return stats
    moment = now or timeutil.now()
    try:
        memories = _select_window(moment)
    except Exception:
        logger.exception("情景聚合选材失败，跳过本轮")
        return stats

    window_start = moment - timedelta(hours=settings.memory_episodic_window_hours)
    groups = _group(memories)
    eligible: list[tuple[tuple[str, str, str], list]] = []
    for key in sorted(groups):
        theme = key[2]
        if theme.endswith(f":{MISC_THEME}"):
            stats["skipped_misc"] += 1
            continue
        members = groups[key]
        if len(members) < settings.memory_episodic_min_events:
            stats["skipped_small"] += 1
            continue
        eligible.append((key, members))
    stats["groups"] = len(eligible)

    budget = settings.memory_episodic_max_per_run
    for (user_id, character_id, theme), members in eligible:
        source_ids = sorted(memory.id for memory in members)
        source_id = source_id_for(theme, source_ids)
        # 幂等命中不计入预算：否则「最早的一批组」会每轮吃掉配额，剩余组永远轮不到（D7）
        if _candidate_exists(source_id):
            stats["existing"] += 1
            continue
        if stats["created"] >= budget:
            break
        try:
            content = aggregate_content(members)
            if not content:
                stats["failed"] += 1
                logger.warning("情景聚合内容为空，跳过该组：theme=%s", theme)
                continue
            memory_ingest.create_candidate(
                user_id=user_id,
                character_id=character_id,
                source_table=SOURCE_TABLE_AGGREGATE,
                source_id=source_id,
                content=content,
                proposed_type=PROPOSED_TYPE_AGGREGATE,
                source_kind=AGGREGATE_SOURCE_KIND,
                salience_init=aggregate_salience(members),
                layer=AGGREGATE_LAYER,
                source_ref_extra={
                    "table": SOURCE_TABLE_AGGREGATE,
                    "source_ids": source_ids,
                    "window_start": window_start.isoformat(timespec="seconds"),
                    "theme": theme,
                },
                created_at=moment,
            )
            stats["created"] += 1
        except Exception:
            stats["failed"] += 1
            logger.warning("情景聚合单组失败，跳过：theme=%s", theme, exc_info=True)
    return stats


def run_aggregate_tick(now: datetime | None = None) -> dict:
    """周期 hook（`job_worker` 每轮调用）：`mode != auto` → **零动作（不查库不入队）**。"""
    if get_settings().memory_episodic_mode != MODE_AUTO:
        return {"enqueued": False}
    moment = now or timeutil.now()
    idempotency_key = f"{JOB_TYPE_MEMORY_EPISODIC_AGGREGATE}:{moment:%Y-%m-%dT%H}"
    try:
        enqueued = background_job_repository.enqueue_job(
            JOB_TYPE_MEMORY_EPISODIC_AGGREGATE, {}, idempotency_key, run_at=moment
        )
    except Exception:
        logger.exception("情景聚合入队失败，跳过本轮")
        return {"enqueued": False}
    return {"enqueued": enqueued}


def run_aggregate_job() -> dict:
    """job handler：门控在 `aggregate_once` 内（防「入队后关闸」仍生效）。"""
    return aggregate_once()
