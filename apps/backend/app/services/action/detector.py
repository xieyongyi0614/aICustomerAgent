"""V9 ActionIntentDetector（planner.md §1）。

确定性检出：词表 + 参数抽取的纯函数，零新增 LLM 调用。
门控 action_detector_enabled；任何异常返回 None（宁缺毋滥）。
词表属角色资产（app/character/asuna/action.py），检出逻辑在此。
"""

import logging
import re
from datetime import datetime

from app.character.asuna.action import (
    ACTION_LEXICON_PRIORITY,
    ACTION_TRIGGER_LEXICON,
    LEDGER_FALSE_POSITIVE_MARKERS,
    LEDGER_INCOME_MARKERS,
    LEDGER_QUERY_TRIGGERS,
    LEDGER_RECORD_TRIGGERS,
    LEDGER_REVISE_TRIGGERS,
    REQUIRED_PARAMS,
    SELF_IMPERATIVE_TRIGGERS,
)
from app.core.settings import get_settings
from app.models.action import ActionIntent, make_dedupe_key
from app.models.ledger import LedgerAmountError, to_minor
from app.services.action.time_parse import parse_time_phrase

logger = logging.getLogger(__name__)

_QUESTION_GUARDS = ("能不能", "可不可以", "可以吗", "能吗", "会提醒我吗", "你会", "能不能帮我")
_IMPERATIVE_SUBJECTS = ("帮我", "替我", "给我", "记得", "麻烦")

# 记账金额结构：带单位金额，或收入动词后的裸数字（PLA-009 组合判定）。
_AMOUNT_WITH_UNIT = re.compile(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块|块钱|角|毛|¥|￥)")
_AMOUNT_AFTER_INCOME = re.compile(
    r"(?:收到|报销|入账|工资|奖金|转入|收入|进账)\D{0,6}(\d+(?:\.\d{1,2})?)"
)

# 数量清单抽取：数词/数字 + 量词 + 名词（"俩个鸡蛋" → 鸡蛋×2），供 use_object 批量消耗。
_ITEM_PATTERN = re.compile(
    r"([0-9]+|[一二两俩三四五六七八九十半]+)([个只瓶罐袋条碗份块杯桶片盒根包])\s*([\u4e00-\u9fa5]{1,4})"
)
_CN_NUMERALS = {
    "一": 1.0,
    "二": 2.0,
    "两": 2.0,
    "俩": 2.0,
    "三": 3.0,
    "四": 4.0,
    "五": 5.0,
    "六": 6.0,
    "七": 7.0,
    "八": 8.0,
    "九": 9.0,
    "十": 10.0,
    "半": 0.5,
}


def _extract_items(content: str) -> list[dict]:
    items: list[dict] = []
    for numeral, _measure, noun in _ITEM_PATTERN.findall(content):
        value = _CN_NUMERALS.get(numeral)
        if value is None:
            try:
                value = float(numeral)
            except ValueError:
                continue
        items.append({"object": noun, "quantity": value})
    return items

# 祈使主语豁免：把X放到Y 是天然指令；查询/取消/记账陈述是天然请求。
_IMPERATIVE_EXEMPT_TYPES = (
    "move_object",
    "query_environment",
    "cancel_reminder",
    "record_ledger_entry",
    "revise_ledger_entry",
    "query_ledger",
)

# 触发词 → 前置主语要求：词表已含"我"的模式天然祈使，其余要求命令式主语。
_MOVE_PATTERN = re.compile(r"(?:帮我)?把(.{1,12}?)(?:放到|放进|收到)(.{1,16}?)(?:里|里面|中)?(?:[，。！？!?.]|$)")


def _to_minor_or_none(amount_text: str) -> int | None:
    """金额原文 → 整数分；精度/格式不合规时返回 None（由 missing 兜成 ambiguous）。"""
    try:
        return to_minor(amount_text)
    except LedgerAmountError:
        return None


def _ledger_false_positive(content: str) -> bool:
    if any(marker in content for marker in LEDGER_FALSE_POSITIVE_MARKERS):
        return not _AMOUNT_WITH_UNIT.search(content) and not _AMOUNT_AFTER_INCOME.search(content)
    return False


def _detect_ledger(content: str) -> tuple[str, str] | None:
    """记账意图组合判定：动词/短语 + 金额结构；反例（「我记得」）不命中。"""
    if _ledger_false_positive(content):
        return None
    for trigger in LEDGER_REVISE_TRIGGERS:
        if trigger in content:
            return "revise_ledger_entry", trigger
    for trigger in LEDGER_QUERY_TRIGGERS:
        if trigger in content:
            return "query_ledger", trigger
    amount_hit = _AMOUNT_WITH_UNIT.search(content) or _AMOUNT_AFTER_INCOME.search(content)
    if amount_hit is None:
        return None
    for trigger in LEDGER_RECORD_TRIGGERS:
        if trigger in content:
            return "record_ledger_entry", trigger
    return None


def _triggered_type(content: str) -> tuple[str, str] | None:
    """一轮至多一个 intent：按词表优先级取最高命中的 (action_type, trigger)。"""
    ledger_hit = _detect_ledger(content)
    if ledger_hit is not None:
        return ledger_hit
    for action_type in ACTION_LEXICON_PRIORITY:
        for trigger in ACTION_TRIGGER_LEXICON.get(action_type, ()):
            if trigger in content and action_type not in ("move_object", "record_ledger_entry", "revise_ledger_entry", "query_ledger"):
                return action_type, trigger
    if _MOVE_PATTERN.search(content):
        return "move_object", "放到"
    return None


def _is_imperative(content: str, trigger: str) -> bool:
    """祈使优先：触发词 + 用户主语（我/帮我/替我）才命中；自述/转述不命中。"""
    idx = content.find(trigger)
    context = content[max(0, idx - 6):idx + len(trigger) + 2]
    if "我" in context:
        return True
    return any(subject in content for subject in _IMPERATIVE_SUBJECTS)


def _is_question_inquiry(content: str) -> bool:
    """问句守卫：询问能力（"你能提醒我吗"）不触发执行，存疑即不执行。"""
    if any(guard in content for guard in _QUESTION_GUARDS):
        return True
    import re as _re

    return _re.search(r"(你|能|可以|会).{0,10}(吗|么|嘛)", content) is not None


def _text_after(content: str, trigger: str, limit: int = 40) -> str:
    idx = content.find(trigger)
    tail = content[idx + len(trigger):].strip(" ，,。.!？?；;：:～~")
    return tail[:limit].strip()


def _extract_params(action_type: str, content: str, trigger: str, now: datetime) -> tuple[dict, list[str]]:
    """参数抽取（planner.md §1.2）：触发词后置文本 + 时间短语解析。"""
    params: dict = {}
    missing: list[str] = []

    if action_type == "create_reminder":
        due_at = parse_time_phrase(content, now)
        if due_at is not None:
            params["due_at"] = due_at.isoformat()
        content_text = _text_after(content, trigger)
        if content_text:
            params["content"] = content_text
        for name in REQUIRED_PARAMS[action_type]:
            if name not in params:
                missing.append(name)
        return params, missing

    if action_type == "move_object":
        match = _MOVE_PATTERN.search(content)
        if match:
            params["object"] = match.group(1).strip()
            params["location"] = match.group(2).strip()
        for name in REQUIRED_PARAMS[action_type]:
            if name not in params:
                missing.append(name)
        return params, missing

    field_by_type = {
        "cancel_reminder": "target",
        "remember_fact": "fact",
        "create_object": "object",
        "use_object": "object",
        "query_search": "query",
        "send_notification": "content",
    }
    if action_type == "record_ledger_entry":
        amount = _AMOUNT_WITH_UNIT.search(content) or _AMOUNT_AFTER_INCOME.search(content)
        if amount:
            params["amount_minor"] = _to_minor_or_none(amount.group(1))
        direction = "income" if any(m in content for m in LEDGER_INCOME_MARKERS) else "expense"
        params["direction"] = direction
        params["source"] = "conversation"
        params["idempotency_key"] = make_dedupe_key(
            action_type, _core_params(action_type, params)
        )
        for name in REQUIRED_PARAMS[action_type]:
            if params.get(name) in (None, ""):
                missing.append(name)
        return params, missing
    if action_type == "revise_ledger_entry":
        params["reason"] = content.strip()[:80]
        for name in REQUIRED_PARAMS[action_type]:
            if name not in params:
                missing.append(name)
        return params, missing
    if action_type == "query_ledger":
        params["period"] = "month"
        for name in REQUIRED_PARAMS[action_type]:
            if name not in params:
                missing.append(name)
        return params, missing
    field = field_by_type.get(action_type)
    if field is not None:
        value = _text_after(content, trigger)
        if value:
            params[field] = value
    if action_type == "use_object":
        items = _extract_items(content)
        if items:
            params["items"] = items
    for name in REQUIRED_PARAMS[action_type]:
        if name not in params:
            missing.append(name)
    return params, missing


def _core_params(action_type: str, params: dict) -> dict:
    """dedupe_key 只取核心参数（时间短语原文不参与，解析结果参与）。"""
    core_fields = {
        "create_reminder": ("content", "due_at"),
        "cancel_reminder": ("target",),
        "remember_fact": ("fact",),
        "create_object": ("object",),
        "move_object": ("object", "location"),
        "use_object": ("object",),
        "query_environment": (),
        "query_search": ("query",),
        "send_notification": ("content",),
        "record_ledger_entry": ("amount_minor", "direction"),
        "revise_ledger_entry": ("reason",),
        "query_ledger": ("period",),
    }
    return {key: params[key] for key in core_fields.get(action_type, ()) if key in params}


def detect_action_intent(
    content: str,
    scene_state=None,
    world_ctx=None,
    now: datetime | None = None,
) -> ActionIntent | None:
    """确定性检出入口（H-A1）；异常降级 None。"""
    settings = get_settings()
    if not settings.action_detector_enabled:
        return None
    try:
        return _detect(content, now or datetime.now())
    except Exception:
        logger.exception("行动检出异常，降级为 None")
        return None


def _detect(content: str, now: datetime) -> ActionIntent | None:
    if not content or not content.strip():
        return None
    if _is_question_inquiry(content):
        return None
    hit = _triggered_type(content)
    if hit is None:
        return None
    action_type, trigger = hit
    if (
        action_type not in _IMPERATIVE_EXEMPT_TYPES
        and trigger not in SELF_IMPERATIVE_TRIGGERS
        and not _is_imperative(content, trigger)
    ):
        return None

    params, missing = _extract_params(action_type, content, trigger, now)
    confidence = "confident" if not missing else "ambiguous"
    dedupe_key = make_dedupe_key(action_type, _core_params(action_type, params))
    return ActionIntent(
        action_type=action_type,
        confidence=confidence,
        params=params,
        missing_params=missing,
        evidence=trigger[:40],
        dedupe_key=dedupe_key,
    )
