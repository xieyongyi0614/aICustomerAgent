"""V9 search 能力：无可用检索来源时的**明确降级**（V2.4.0 TOOL-010 §2.3 路线 B）。

裁决（见任务报告"search 路线裁决"）：既有依赖内**不存在可直接使用的检索来源**——
`pyproject.toml` / `uv.lock` 无任何检索 / 向量 / 抓取依赖，settings 无检索端点与凭据，
`app/` 内无检索实现，且 TOOL-010 §1.2 Non-Scope 明确把外部 API 工具留给 TOOL-011。
故走路线 B：**保持 `unavailable`，但不留空壳**——

- `failure_kind="unavailable"`（归一器提升为顶层，V9 旧位置保留）；
- `reason_kind="source_not_configured"` 让失败可判定、可统计；
- `message` 为角色语气的用户可见话术（`TOOL_FAILURE_TEXT`，≤ 60 字）；
- 工具面按 `TOOL_UNAVAILABLE_TOOL_IDS` 默认裁剪（`tool/surface.py`），
  避免用户反复触发必然失败的工具（§6.3 E1）。

执行语义：**不接真实数据源、零网络、零写入**。总闸 off 时返回与 V9 逐字节一致的
`{"failure_kind": "unavailable"}`（既有 V9 测试与 Flag-off 行为不变）；总闸 on 时才附加
`reason_kind` / `message` / `retryable` / `result_count`，供工具层与回复素材消费。
"""

from app.character.asuna.tool import TOOL_FAILURE_TEXT
from app.core.settings import get_settings
from app.models.action import ActionSchema, CapabilityResult
from app.services.action.registry import ExecutionContext

TOOL_ID = "builtin.search.query"

SEARCH_QUERY_MAX_CHARS = 60

UNAVAILABLE_STATUS = "unavailable"

FAILURE_KIND_UNAVAILABLE = "unavailable"

REASON_SOURCE_NOT_CONFIGURED = "source_not_configured"

SEARCH_RESULT_COUNT = 0

UNTRUSTED = True

V9_ERROR_TEXT = "该能力尚未接入"


def _settings_of(ctx: ExecutionContext):
    return getattr(ctx, "settings", None) or get_settings()


class SearchCapability:
    name = "search"
    description = "信息检索（本版本无可用来源，调用即得明确降级结果）"
    actions = {
        "query": ActionSchema(required=["query"]),
    }

    def validate(self, action: str, params: dict) -> list[str]:
        schema = self.actions.get(action)
        if schema is None:
            return [f"未知动作: {action}"]
        errors = schema.validate(params)
        query = params.get("query")
        if isinstance(query, str) and len(query) > SEARCH_QUERY_MAX_CHARS:
            errors.append(f"query 长度 {len(query)} 超出上限 {SEARCH_QUERY_MAX_CHARS}")
        return errors

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult:
        if action != "query":
            return CapabilityResult(
                status="failed",
                error=f"未知动作: {action}",
                payload={"failure_kind": "permanent", "reason_kind": "unknown_action"},
            )
        if not bool(getattr(_settings_of(ctx), "tool_system_enabled", False)):
            return CapabilityResult(
                status=UNAVAILABLE_STATUS,
                error=V9_ERROR_TEXT,
                payload={"failure_kind": FAILURE_KIND_UNAVAILABLE},
            )
        return CapabilityResult(
            status=UNAVAILABLE_STATUS,
            error="该能力尚未接入可用的检索来源",
            payload={
                "failure_kind": FAILURE_KIND_UNAVAILABLE,
                "reason_kind": REASON_SOURCE_NOT_CONFIGURED,
                "retryable": False,
                "result_count": SEARCH_RESULT_COUNT,
                "untrusted": UNTRUSTED,
                "message": TOOL_FAILURE_TEXT[TOOL_ID],
            },
        )
