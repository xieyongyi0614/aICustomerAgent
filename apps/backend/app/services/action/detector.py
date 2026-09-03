"""V9 ActionIntentDetector（planner.md §1）。

确定性检出：词表 + 参数抽取的纯函数，零新增 LLM 调用。
门控 action_enabled and action_detector_enabled；任何异常返回 None（宁缺毋滥）。
词表属角色资产（app/character/asuna/action.py），检出逻辑在此。
"""

import logging
import re
from datetime import datetime

from app.character.asuna.action import (
    ACTION_LEXICON_PRIORITY,
    ACTION_TRIGGER_LEXICON,
    REQUIRED_PARAMS,
)
from app.models.action import ActionIntent, make_dedupe_key
from app.services.action.time_parse import parse_time_phrase

logger = logging.getLogger(__name__)

_QUESTION_GUARDS = ("能不能", "可不可以", "可以吗", "能吗", "会提醒我吗", "你会", "能不能帮我")
_IMPERATIVE_SUBJECTS = ("帮我", "替我", "给我", "记得", "麻烦")

# 祈使主语豁免：把X放到Y 是天然指令；查询/取消是天然请求。
_IMPERATIVE_EXEMPT_TYPES = ("move_object", "query_environment", "cancel_reminder")

# 触发词 → 前置主语要求：词表已含"我"的模式天然祈使，其余要求命令式主语。
_MOVE_PATTERN = re.compile(r"(?:帮我)?把(.{1,12}?)(?:放到|放进|收到)(.{1,16}?)(?:里|里面|中)?(?:[，。！？!?.]|$)")


def _triggered_type(content: str) -> tuple[str, str] | None:
    """一轮至多一个 intent：按词表优先级取最高命中的 (action_type, trigger)。"""
    for action_type in ACTION_LEXICON_PRIORITY:
        for trigger in ACTION_TRIGGER_LEXICON.get(action_type, ()):
            if trigger in content and action_type != "move_object":
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
    field = field_by_type.get(action_type)
    if field is not None:
        value = _text_after(content, trigger)
        if value:
            params[field] = value
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
    }
    return {key: params[key] for key in core_fields.get(action_type, ()) if key in params}


def detect_action_intent(
    content: str,
    scene_state=None,
    world_ctx=None,
    now: datetime | None = None,
) -> ActionIntent | None:
    """确定性检出入口（H-A1）；门控 + 异常降级 None。"""
    from app.core.settings import get_settings

    settings = get_settings()
    if not settings.action_enabled or not settings.action_detector_enabled:
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
    if action_type not in _IMPERATIVE_EXEMPT_TYPES and not _is_imperative(content, trigger):
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
