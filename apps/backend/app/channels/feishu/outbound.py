"""飞书出站文本纯函数：规范化 / 超长切分（FEISHU-005，两形态共用）。

切分硬不变式：`"".join(parts) == text`（不丢字、不重复、不插分隔符）。
Python str 切片按代码点，不会拆开 UTF-16 代理对；ZWJ 组合 emoji 存在视觉拆分
残余风险，以"不改写内容"优先。
"""

import logging
import unicodedata

logger = logging.getLogger(__name__)

MAX_PARTS = 10
_PARAGRAPH_BREAK = "\n\n"
_SENTENCE_PUNCTS = "。！？；…!?;"
_SOFT_BREAKS = " \t，,、"


def normalize_text(text: str) -> str:
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(
        char
        for char in unified
        if char in ("\n", "\t") or unicodedata.category(char) != "Cc"
    )
    return cleaned.strip()


def split_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    if max_chars < 1:
        max_chars = 1
    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        cut = _break_position(remaining[:max_chars])
        if cut is None:
            cut = max_chars
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if len(parts) > MAX_PARTS:
        logger.warning(
            "feishu outbound text exceeds max parts=%d; last segment truncated",
            MAX_PARTS,
        )
        head = parts[: MAX_PARTS - 1]
        tail = "".join(parts[MAX_PARTS - 1:])[:max_chars]
        parts = head + [tail]
    return parts


def _break_position(chunk: str) -> int | None:
    paragraph = chunk.rfind(_PARAGRAPH_BREAK)
    if paragraph >= 0:
        return paragraph + len(_PARAGRAPH_BREAK)
    line = chunk.rfind("\n")
    if line >= 0:
        return line + 1
    for index in range(len(chunk) - 1, -1, -1):
        if chunk[index] in _SENTENCE_PUNCTS:
            return index + 1
    for index in range(len(chunk) - 1, -1, -1):
        if chunk[index] in _SOFT_BREAKS:
            return index + 1
    return None
