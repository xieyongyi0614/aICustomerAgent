"""MEV-007 语义抽象链：若干情景条目 → **恰好 1 条**语义候选（lite profile 结构化输出）。

契约（`docs/version/v6.0.0/tasks/MEV-007.md` §4.1.1）：

- 类型白名单 **fail-closed**：越界即抛 `ValueError`，**不回落猜测**（D1 / D9）；
- 结论条数必须为 1、内容非空且不超长：不满足同样抛错（由调用方按「丢弃该组」处理）；
- 链内不做任何类型推断、不补全缺失字段、不截断超长内容。

降级判定集中在调用方（`services/memory/semantic.py`）：链只负责「产出或抛错」。
"""

from pydantic import BaseModel, Field

from app.chains.structured import build_structured_chain
from app.core.llm_factory import get_llm
from app.core.settings import SettingsError
from app.prompts.memory_semantic_abstract import (
    SEMANTIC_CONTENT_MAX_CHARS,
    SEMANTIC_TYPES,
    build_semantic_abstract_messages,
    format_episodes,
)

__all__ = [
    "SEMANTIC_CONTENT_MAX_CHARS",
    "SEMANTIC_TYPES",
    "SemanticAbstractItem",
    "SemanticAbstractResult",
    "abstract_from_episodes",
    "build_semantic_abstract_chain",
]

_LLM_LITE_PROFILE_ID = "lite"
_EXPECTED_ITEMS = 1


class SemanticAbstractItem(BaseModel):
    content: str
    proposed_type: str
    reason: str = ""


class SemanticAbstractResult(BaseModel):
    items: list[SemanticAbstractItem] = Field(default_factory=list)


def _resolve_llm():
    try:
        return get_llm(_LLM_LITE_PROFILE_ID)
    except SettingsError:
        return get_llm(None)


def build_semantic_abstract_chain(llm=None):
    model = llm if llm is not None else _resolve_llm()
    return build_structured_chain(
        build_semantic_abstract_messages(), SemanticAbstractResult, model
    )


def _validate(item: SemanticAbstractItem) -> SemanticAbstractItem:
    content = (item.content or "").strip()
    if not content:
        raise ValueError("语义抽象结论为空")
    if len(content) > SEMANTIC_CONTENT_MAX_CHARS:
        raise ValueError(
            f"语义抽象结论超长：{len(content)} > {SEMANTIC_CONTENT_MAX_CHARS}"
        )
    proposed_type = (item.proposed_type or "").strip()
    if proposed_type not in SEMANTIC_TYPES:
        raise ValueError(f"语义抽象类型越界，fail-closed 丢弃：{item.proposed_type!r}")
    return SemanticAbstractItem(
        content=content, proposed_type=proposed_type, reason=item.reason or ""
    )


async def abstract_from_episodes(
    theme: str, episodes: list[tuple[str, str]], llm=None
) -> SemanticAbstractItem:
    """`episodes` = `(memory_id, content)`，按 `created_at` 升序。

    异常（链失败 / 条数非 1 / 长度越界 / 类型越界）一律向调用方抛出——调用方按
    「`logger.warning` + 跳过该组」处理，本函数不吞异常、不回落默认类型。
    """
    if not episodes:
        raise ValueError("语义抽象输入为空")
    chain = build_semantic_abstract_chain(llm)
    result = await chain.ainvoke(
        {"theme": theme, "episodes": format_episodes(episodes)}
    )
    items = getattr(result, "items", None) or []
    if len(items) != _EXPECTED_ITEMS:
        raise ValueError(f"语义抽象结论条数非 {_EXPECTED_ITEMS}：{len(items)}")
    return _validate(items[0])
