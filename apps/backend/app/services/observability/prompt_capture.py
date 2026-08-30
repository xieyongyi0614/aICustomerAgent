"""V7.8 Prompt 快照采集（prompt-debug.md §1~§4）。

三重控制：模式（disabled/sampled/always）+ 确定性采样 + 字符上限；redact 可选。
采集只读已组装的 messages，绝不改变发出的 prompt 字节。
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.llm_factory import profile_id_of
from app.core.settings import get_settings
from app.models.observability import (
    CallSite,
    PromptSnapshot,
    deterministic_sample,
    new_record_id,
)

SECTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("emotion", "【角色当前情绪】"),
    ("character_state", "【角色当前状态】"),
    ("relationship", "【与用户的关系】"),
    ("goal", "【角色当前目标】"),
    ("intention", "【本轮意图】"),
    ("behavior", "【本轮行为指令】"),
    ("behavior", "【表现方式】"),
    ("behavior", "【活动延续】"),
    ("scene", "【当前场景】"),
    ("scene", "【回复节奏】"),
    ("scene", "【角色扮演硬约束】"),
    ("scene", "【本轮指令】"),
    ("memory", "【你记得关于用户的事】"),
    ("summary", "【对话摘要】"),
)

_REDACT_PREVIEW_CHARS = 200


def enabled() -> bool:
    settings = get_settings()
    return (
        settings.observability_persist_enabled
        and settings.observability_prompt_capture_mode != "disabled"
    )


def _role_of(message) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "human"
    if isinstance(message, AIMessage):
        return "ai"
    return str(getattr(message, "type", "system"))


def _redact(content: str) -> str:
    from app.core.logutils import content_preview

    if not get_settings().observability_prompt_redact:
        return content
    if not content:
        return content
    if get_settings().log_content_preview_chars > 0:
        return content_preview(content)
    return f"<{len(content)} 字符>"


def _bounded_messages(messages, max_chars: int) -> tuple[list[dict], bool]:
    payload: list[dict] = []
    total = 0
    truncated = False
    for message in messages:
        content = _redact(str(getattr(message, "content", "") or ""))
        allowed = max_chars - total
        if allowed <= 0:
            payload.append({"role": _role_of(message), "content": ""})
            truncated = True
            continue
        if len(content) > allowed:
            content = content[:allowed]
            truncated = True
        total += len(content)
        payload.append({"role": _role_of(message), "content": content})
    return payload, truncated


def section_budget_from_messages(messages) -> dict:
    sections: dict[str, int] = {}
    seen_labeled = False
    human_indexes = [
        index for index, message in enumerate(messages) if isinstance(message, HumanMessage)
    ]
    last_human_index = human_indexes[-1] if human_indexes else -1
    for index, message in enumerate(messages):
        size = len(str(getattr(message, "content", "") or ""))
        if isinstance(message, SystemMessage):
            content = str(getattr(message, "content", "") or "")
            matched = next(
                (name for name, marker in SECTION_MARKERS if content.startswith(marker)),
                None,
            )
            if matched is not None:
                sections[matched] = sections.get(matched, 0) + size
                seen_labeled = True
            elif not seen_labeled:
                sections["identity"] = sections.get("identity", 0) + size
            else:
                sections["tail"] = sections.get("tail", 0) + size
        elif isinstance(message, HumanMessage) and index == last_human_index:
            sections["user_message"] = sections.get("user_message", 0) + size
        else:
            sections["history"] = sections.get("history", 0) + size
    sections["total"] = sum(value for key, value in sections.items() if key != "total")
    sections["budget"] = get_settings().context_total_char_budget
    return sections


def _sample_hit(request_id: str) -> bool:
    settings = get_settings()
    if settings.observability_prompt_capture_mode == "always":
        return True
    return deterministic_sample(request_id, settings.observability_prompt_sample_rate)


def capture_prompt_snapshot(
    call_site: CallSite,
    formatted_messages,
    model=None,
    section_budget: dict | None = None,
) -> None:
    from app.application import observability

    if not enabled():
        return
    trace = observability.current_trace.get()
    request_id = trace.request_id if trace is not None else ""
    if not _sample_hit(request_id):
        return
    settings = get_settings()
    payload, truncated = _bounded_messages(
        formatted_messages or [], settings.observability_prompt_max_chars
    )
    snapshot = PromptSnapshot(
        id=new_record_id(),
        request_id=request_id or None,
        turn_id=trace.turn_id if trace is not None else None,
        call_site=call_site,
        profile_id=profile_id_of(model),
        model=getattr(model, "model_name", None) or getattr(model, "_llm_type", None),
        messages=payload,
        section_budget=section_budget,
        truncated=truncated,
    )
    observability.record_prompt_snapshot(snapshot)


def capture_judge_snapshot(call_site: CallSite, model=None) -> None:
    """judge 快照只记元数据（prompt-debug.md §6）：不存 judge prompt 原文。"""
    from app.application import observability

    if not enabled():
        return
    trace = observability.current_trace.get()
    request_id = trace.request_id if trace is not None else ""
    if not _sample_hit(request_id):
        return
    snapshot = PromptSnapshot(
        id=new_record_id(),
        request_id=request_id or None,
        turn_id=trace.turn_id if trace is not None else None,
        call_site=call_site,
        profile_id=profile_id_of(model),
        model=getattr(model, "model_name", None) or getattr(model, "_llm_type", None),
        messages=[],
        section_budget=None,
        truncated=False,
    )
    observability.record_prompt_snapshot(snapshot)
