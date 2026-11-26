"""语义抽象（MEV-007）：同一主题下的多条情景条目 → 一条跨事件语义候选。

设计要点（`docs/version/v6.0.0/tasks/MEV-007.md` §4）：

- **无自反馈回路**（D2）：只读 `layer='episodic'`，产物写 `layer='semantic'`——
  产物永不在输入集合内，故「抽象之上再抽象」在结构上不可能；
- **幂等键不含时间**（D3）：`source_id = semantic:{theme_key}:{本轮来源 id 升序}`，
  故跨 tick 的同一组复用同一候选（命中 `uq_memory_candidates_source` 即返回既有行）；
- **类型白名单 fail-closed**（D1 / D9）：越界在链内抛错，本模块只**丢弃该组**、不回落猜测；
- **账目明细禁入**（D4）：命中金额 / 账号模式 → **丢弃该组**（不脱敏写入，避免留下「半个事实」）；
- **唯一写面**（D5）：只经 `ingest.create_candidate`，落库与转正交给既有三段评估链路；
- **单组失败隔离**（§4.1.3）：一组失败不阻断整轮，**整体不抛**（连接级错误交 job 退避）。

与 `MEV-006` 的分工：情景聚合（零 LLM、时间窗内拼接）产出「一段经历」；语义抽象
（lite LLM、**不限时间窗**、累积归纳）产出「跨事件认识」。两者共同构成
episodic / semantic 双通道；`MEV-006` 的聚合产物（`layer='episodic'`）是本模块的合法输入材。

注册：job 类型与周期 hook 由同域 `job_worker` 侧挂载（本模块不反向 import 它，避免循环导入）。
"""

from __future__ import annotations

import asyncio
import logging
import re

from app.chains.memory_semantic_abstract_chain import abstract_from_episodes
from app.core import timeutil
from app.core.db import Memory, SessionLocal
from app.core.settings import get_settings
from app.repositories import background_job_repository
from app.services.memory import episodic as memory_episodic
from app.services.memory import ingest as memory_ingest

logger = logging.getLogger(__name__)

JOB_TYPE_MEMORY_SEMANTIC_ABSTRACT = "memory_semantic_abstract"

MODE_AUTO = "auto"

INPUT_LAYER = "episodic"
"""输入层：本模块**只读**该层（D2）。"""

OUTPUT_LAYER = "semantic"
"""产物层：产物永不在输入集合内（D2）。"""

SOURCE_TABLE_SEMANTIC = "memory_aggregate"
"""候选来源表（与 `MEV-006` 同值，`source_id` 前缀 `semantic:` 保证不碰撞）。"""

SEMANTIC_SOURCE_KIND = "ai_inferred"
"""来源种类：语义结论由模型归纳得出（非用户直述）。"""

ABSTRACT_KIND = "semantic"
"""`source_ref.abstract_kind`：区分同表的两种抽象产物（episodic / semantic）。"""

DEFAULT_SALIENCE = 0.5
"""来源 salience 全为空时的回落（与检索侧 `_DEFAULT_SALIENCE` 同值）。"""

LEDGER_DETAIL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"[¥￥$€]\s*\d",
        r"\d+(?:\.\d+)?\s*(?:元|块钱|块|万|万元|亿元|美元|美金|欧元|日元|港币|英镑)",
        r"\d+(?:\.\d+)?\s*(?:人民币|RMB|CNY)",
        r"(?:账号|帐号|账户|卡号|银行卡|信用卡|支付宝|微信支付|尾号|余额|账单|流水|消费明细|交易记录)",
        r"\d{12,}",
    )
)
"""账目明细护栏（★ 实现期冻结）：命中即**丢弃整组**，不脱敏（D4）。

覆盖两类模式：金额（货币符号 / 带单位数值）与账号（卡号 / 尾号 / 长数字串 / 账目词）。
脱敏会留下残缺事实（「用户每月在 ████ 花费约 2000 元」），既违背「明细永不进记忆」，
又制造不可解释的半真相，故一律整组丢弃。
"""


def _select_episodic() -> list:
    """只读选材：`status='active'` ∧ `layer='episodic'`（**含** `MEV-006` 聚合产物）。

    **不限时间窗**（§4.1.2）：语义是累积归纳，触发依据是「未抽象过的条数」而非时间。
    """
    with SessionLocal() as session:
        rows = (
            session.query(Memory)
            .filter(Memory.status == "active", Memory.layer == INPUT_LAYER)
            .order_by(Memory.created_at.asc(), Memory.id.asc())
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _group(memories) -> dict[tuple[str, str, str], list]:
    """组键 `(user_id, character_id, theme_key)`（复用 `MEV-006` 的 `theme_key`，不含时间）。"""
    groups: dict[tuple[str, str, str], list] = {}
    for memory in memories:
        key = (
            memory.user_id,
            memory.character_id or "*",
            memory_episodic.theme_key(memory),
        )
        groups.setdefault(key, []).append(memory)
    return groups


def _covered_by_user(user_ids) -> dict[str, set[str]]:
    """既有 `semantic` 记忆已覆盖的情景 id 集合（`source_ref.source_ids`）。

    「未抽象过」判定依据（§4.1.2）：只有**未被覆盖**的情景才作为本轮抽象来源，
    从而「已覆盖的不重复抽象、新情景追加后再次触发」。
    """
    ids = list(user_ids)
    if not ids:
        return {}
    with SessionLocal() as session:
        rows = (
            session.query(Memory.user_id, Memory.source_ref)
            .filter(Memory.user_id.in_(ids), Memory.layer == OUTPUT_LAYER)
            .all()
        )
    covered: dict[str, set[str]] = {user_id: set() for user_id in ids}
    for user_id, source_ref in rows:
        if not isinstance(source_ref, dict):
            continue
        for source_id in source_ref.get("source_ids") or ():
            if isinstance(source_id, str):
                covered.setdefault(user_id, set()).add(source_id)
    return covered


def source_id_for(theme: str, source_ids) -> str:
    """幂等键：`semantic:{theme_key}:{本轮来源 id 升序逗号连接}`（★ 不得含时间戳，D3）。"""
    return f"semantic:{theme}:{','.join(sorted(source_ids))}"


def abstract_salience(memories) -> float:
    """取本轮抽象来源 `salience` 的**最大值**（不放大、不累加，D6）。"""
    values = [memory.salience for memory in memories if memory.salience is not None]
    return max(values) if values else DEFAULT_SALIENCE


def has_ledger_detail(content: str) -> bool:
    """确定性检查：内容是否含金额 / 账号类账目明细（D4）。"""
    text = content or ""
    return any(pattern.search(text) for pattern in LEDGER_DETAIL_PATTERNS)


def _candidate_exists(source_id: str) -> bool:
    """候选是否已存在（幂等键）：已存在的组不再占用本轮预算，让剩余组能推进。"""
    from app.core.db import MemoryCandidateRow

    with SessionLocal() as session:
        return (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.source_table == SOURCE_TABLE_SEMANTIC,
                MemoryCandidateRow.source_id == source_id,
            )
            .first()
            is not None
        )


def abstract_once(now=None, llm=None) -> dict:
    """执行一轮语义抽象；返回统计（供日志 / 观测），单组失败隔离。

    `mode != auto` → **零动作**（不查库、不调 LLM）：闸设在最内层入口，
    hook / job / 直调三条路都受控。
    """
    settings = get_settings()
    stats = {
        "groups": 0,
        "created": 0,
        "existing": 0,
        "skipped_small": 0,
        "discarded_detail": 0,
        "failed": 0,
    }
    if settings.memory_semantic_mode != MODE_AUTO:
        return stats
    moment = now or timeutil.now()
    try:
        memories = _select_episodic()
    except Exception:
        logger.exception("语义抽象选材失败，跳过本轮")
        return stats

    groups = _group(memories)
    covered = _covered_by_user({key[0] for key in groups})
    eligible: list[tuple[tuple[str, str, str], list]] = []
    for key in sorted(groups):
        covered_ids = covered.get(key[0], set())
        sources = [memory for memory in groups[key] if memory.id not in covered_ids]
        if len(sources) < settings.memory_semantic_min_sources:
            stats["skipped_small"] += 1
            continue
        eligible.append((key, sources))
    stats["groups"] = len(eligible)

    budget = settings.memory_semantic_max_per_run
    for (user_id, character_id, theme), sources in eligible:
        source_ids = sorted(memory.id for memory in sources)
        source_id = source_id_for(theme, source_ids)
        # 幂等命中不计入预算：否则「最早的一批组」会每轮吃掉配额，剩余组永远轮不到
        if _candidate_exists(source_id):
            stats["existing"] += 1
            continue
        if stats["created"] >= budget:
            break
        try:
            ordered = sorted(sources, key=lambda memory: (memory.created_at, memory.id))
            episodes = [(memory.id, memory.content or "") for memory in ordered]
            item = asyncio.run(abstract_from_episodes(theme, episodes, llm))
            if has_ledger_detail(item.content):
                stats["discarded_detail"] += 1
                logger.warning("语义抽象命中账目明细护栏，丢弃该组：theme=%s", theme)
                continue
            memory_ingest.create_candidate(
                user_id=user_id,
                character_id=character_id,
                source_table=SOURCE_TABLE_SEMANTIC,
                source_id=source_id,
                content=item.content,
                proposed_type=item.proposed_type,
                source_kind=SEMANTIC_SOURCE_KIND,
                salience_init=abstract_salience(sources),
                layer=OUTPUT_LAYER,
                source_ref_extra={
                    "table": SOURCE_TABLE_SEMANTIC,
                    "source_ids": source_ids,
                    "theme": theme,
                    "abstract_kind": ABSTRACT_KIND,
                },
                created_at=moment,
            )
            stats["created"] += 1
        except Exception:
            stats["failed"] += 1
            logger.warning("语义抽象单组失败，跳过：theme=%s", theme, exc_info=True)
    return stats


def run_semantic_tick(now=None) -> dict:
    """周期 hook（`job_worker` 每轮调用）：`mode != auto` → **零动作（不查库不入队）**。"""
    if get_settings().memory_semantic_mode != MODE_AUTO:
        return {"enqueued": False}
    moment = now or timeutil.now()
    idempotency_key = f"{JOB_TYPE_MEMORY_SEMANTIC_ABSTRACT}:{moment:%Y-%m-%dT%H}"
    try:
        enqueued = background_job_repository.enqueue_job(
            JOB_TYPE_MEMORY_SEMANTIC_ABSTRACT, {}, idempotency_key, run_at=moment
        )
    except Exception:
        logger.exception("语义抽象入队失败，跳过本轮")
        return {"enqueued": False}
    return {"enqueued": enqueued}


def run_semantic_job() -> dict:
    """job handler：门控在 `abstract_once` 内（防「入队后关闸」仍生效）。"""
    return abstract_once()
