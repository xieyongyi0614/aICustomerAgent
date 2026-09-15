"""V2.4.0 双层参数校验（architecture.md §4.4 / TOOL-003 §2.2、§4.3、§4.6）。

纯函数、零 IO：结构层由 `ToolParameter` 声明驱动，语义层由工具声明的校验器名驱动。

- 结构层八类错误码：missing_required / type_mismatch / enum_invalid / range_violated /
  length_violated / pattern_mismatch / format_invalid / unknown_param。
- 语义层五类错误码：not_future / location_not_found / object_not_in_inventory /
  recipient_not_authorized / content_over_budget（校验器名 → 错误码由 `_SEMANTIC_CODE_BY_NAME` 映射）。
- `normalized` 幂等：对已规范化参数再规范化结果完全一致；时间统一 ISO 8601、
  字符串空白折叠（内外）、枚举大小写等价形式归一。
- 上下文缺失（`ToolContext` 世界事实维度为空，即 TOOL-007 未装配）时语义校验器
  **降级放行并记日志**，不因未装配而误拒；校验器自身异常按**默认拒绝**处理（fail-closed）。
- 装配态与未装配态的区分（TOOL-007 §4.1）：世界事实**已装配**（`ToolContext.world` 含
  `world_enabled` 且为真，见 `ToolContext.world_facts_enabled()`）时，空集合是**事实**
  （如 `inventory=[]` 表示确实没有物品 → `object_in_inventory` 判失败，E4）；未装配或
  世界不可用时才是**信息不足** → 降级放行。
- 世界事实读面（TOOL-004 §2.2 结构）：地点取 `ToolContext.world["locations"]`（已知地点
  词表，TOOL-007 供数据），库存取 `ToolContext.inventory`，收件人取 `ToolContext.authorized_recipients`。
"""

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.models.tool import ToolDefinition, ToolParameter, ValidationReport
from app.services.tool.context import ToolContext

logger = logging.getLogger(__name__)

STRUCTURAL_ERROR_CODES: tuple[str, ...] = (
    "missing_required",
    "type_mismatch",
    "enum_invalid",
    "range_violated",
    "length_violated",
    "pattern_mismatch",
    "format_invalid",
    "unknown_param",
)

SEMANTIC_ERROR_CODES: tuple[str, ...] = (
    "not_future",
    "location_not_found",
    "object_not_in_inventory",
    "recipient_not_authorized",
    "content_over_budget",
)

UNKNOWN_VALIDATOR_CODE = "validator_unknown"

CONTENT_BUDGET_CHARS = 4000

_STRING_TYPES = frozenset({"string", "str", "text"})
_INTEGER_TYPES = frozenset({"integer", "int"})
_NUMBER_TYPES = frozenset({"number", "float", "double"})
_BOOLEAN_TYPES = frozenset({"boolean", "bool"})
_DATETIME_TYPES = frozenset({"datetime", "date_time", "timestamp"})
_ENUM_TYPES = frozenset({"enum"})
_ARRAY_TYPES = frozenset({"array", "list"})
_OBJECT_TYPES = frozenset({"object", "dict", "map"})

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_PATTERN = re.compile(r"^https?://[^\s]+$")
_LOCATION_ID_PATTERN = re.compile(r"^[^\x00-\x1f]{1,200}$")

_SEMANTIC_CODE_BY_NAME: dict[str, str] = {
    "future_datetime": "not_future",
    "location_exists": "location_not_found",
    "object_in_inventory": "object_not_in_inventory",
    "recipient_authorized": "recipient_not_authorized",
    "content_within_budget": "content_over_budget",
}

_SEMANTIC_PARAM_HINTS: dict[str, tuple[str, ...]] = {
    "future_datetime": ("due_at",),
    "location_exists": ("location",),
    "object_in_inventory": ("object",),
    "recipient_authorized": ("recipient", "to"),
    "content_within_budget": ("content", "query", "fact", "target", "object"),
}

_BUDGET_PARAM_KEYS: tuple[str, ...] = ("content", "query", "fact", "target", "object")


SemanticValidator = Callable[[dict[str, Any], ToolContext], list[str]]


def _issue(param: str, code: str, message: str) -> dict[str, Any]:
    return {"param": param, "code": code, "message": message}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def parse_iso8601(value: Any) -> datetime | None:
    """ISO 8601 解析（容忍末尾 Z）；失败返回 None（不抛错）。"""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def format_iso8601(value: datetime) -> str:
    return value.isoformat()


def _type_matches(declared: str, value: Any) -> bool:
    if declared in _STRING_TYPES:
        return isinstance(value, (str, int, float, bool))
    if declared in _INTEGER_TYPES:
        return isinstance(value, int) and not isinstance(value, bool)
    if declared in _NUMBER_TYPES:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared in _BOOLEAN_TYPES:
        return isinstance(value, bool)
    if declared in _DATETIME_TYPES:
        return isinstance(value, (str, datetime))
    if declared in _ARRAY_TYPES:
        return isinstance(value, (list, tuple))
    if declared in _OBJECT_TYPES:
        return isinstance(value, dict)
    return True


def _resolve_enum(parameter: ToolParameter, value: Any) -> Any:
    """枚举等价形式归一：命中声明值即返回；否则按去空白 + 大小写折叠匹配。"""
    if value in parameter.enum:
        return value
    if isinstance(value, str):
        folded = value.strip().casefold()
        for member in parameter.enum:
            if isinstance(member, str) and member.strip().casefold() == folded:
                return member
    return value


def _collapse_text(value: str) -> str:
    return " ".join(value.split())


def _normalize_value(parameter: ToolParameter, value: Any) -> Any:
    """规范化：时间统一 ISO 8601、字符串去空白并字符串化、枚举等价形式归一。

    只对**通过类型校验**的值做等形变换，因此对已规范化结果再规范化不变（幂等）。
    """
    declared = parameter.type
    if declared in _DATETIME_TYPES or parameter.format == "iso8601":
        parsed = parse_iso8601(value)
        if parsed is not None:
            return format_iso8601(parsed)
        return _collapse_text(value) if isinstance(value, str) else value
    if declared in _ENUM_TYPES or parameter.enum:
        resolved = _resolve_enum(parameter, value)
        return _collapse_text(resolved) if isinstance(resolved, str) else resolved
    if declared in _STRING_TYPES:
        return _collapse_text(str(value)) if not isinstance(value, str) else _collapse_text(value)
    if declared in _ARRAY_TYPES:
        return [_collapse_text(item) if isinstance(item, str) else item for item in value]
    return value


def _length_of(value: Any) -> int | None:
    if isinstance(value, (str, list, tuple, dict)):
        return len(value)
    return None


def _check_format(declared: str, value: Any) -> bool:
    """format 声明校验；未知 format 不做判定（前向兼容）。"""
    if declared == "iso8601":
        return parse_iso8601(value) is not None
    if not isinstance(value, str):
        return True
    if declared == "email":
        return bool(_EMAIL_PATTERN.fullmatch(value))
    if declared == "url":
        return bool(_URL_PATTERN.fullmatch(value))
    if declared == "location_id":
        return bool(_LOCATION_ID_PATTERN.fullmatch(value))
    return True


def _structural_issues(
    parameter: ToolParameter, value: Any
) -> tuple[list[dict[str, Any]], Any | None]:
    """单参数结构校验：返回（错误列表，规范化值）；类型不符时短路后续项。"""
    issues: list[dict[str, Any]] = []
    if not _type_matches(parameter.type, value):
        issues.append(
            _issue(
                parameter.name,
                "type_mismatch",
                f"{parameter.name} 类型不符：声明 {parameter.type}，实际 {type(value).__name__}",
            )
        )
        return issues, None
    normalized = _normalize_value(parameter, value)
    if parameter.enum and normalized not in parameter.enum:
        issues.append(
            _issue(
                parameter.name,
                "enum_invalid",
                f"{parameter.name} 取值非法：{normalized!r}；合法值集 "
                f"{', '.join(str(item) for item in parameter.enum)}",
            )
        )
    numeric = isinstance(normalized, (int, float)) and not isinstance(normalized, bool)
    if numeric:
        if parameter.min is not None and normalized < parameter.min:
            issues.append(
                _issue(
                    parameter.name,
                    "range_violated",
                    f"{parameter.name} 低于下限 {parameter.min}：{normalized}",
                )
            )
        if parameter.max is not None and normalized > parameter.max:
            issues.append(
                _issue(
                    parameter.name,
                    "range_violated",
                    f"{parameter.name} 高于上限 {parameter.max}：{normalized}",
                )
            )
    length = _length_of(normalized)
    if length is not None:
        if parameter.min_length is not None and length < parameter.min_length:
            issues.append(
                _issue(
                    parameter.name,
                    "length_violated",
                    f"{parameter.name} 长度 {length} 小于下限 {parameter.min_length}",
                )
            )
        if parameter.max_length is not None and length > parameter.max_length:
            issues.append(
                _issue(
                    parameter.name,
                    "length_violated",
                    f"{parameter.name} 长度 {length} 超出上限 {parameter.max_length}",
                )
            )
    if parameter.pattern and isinstance(normalized, str):
        try:
            matched = re.search(parameter.pattern, normalized) is not None
        except re.error:
            matched = True
            logger.warning("参数 %s 的 pattern 非法，跳过校验：%s", parameter.name, parameter.pattern)
        if not matched:
            issues.append(
                _issue(
                    parameter.name,
                    "pattern_mismatch",
                    f"{parameter.name} 不匹配声明模式 {parameter.pattern}",
                )
            )
    if parameter.type in _DATETIME_TYPES:
        if parse_iso8601(normalized) is None:
            issues.append(
                _issue(
                    parameter.name,
                    "format_invalid",
                    f"{parameter.name} 不是合法 ISO 8601 时间：{normalized!r}",
                )
            )
    elif parameter.format and not _check_format(parameter.format, normalized):
        issues.append(
            _issue(
                parameter.name,
                "format_invalid",
                f"{parameter.name} 不满足声明格式 {parameter.format}",
            )
        )
    return issues, normalized


def _ctx_now(ctx: ToolContext | None) -> datetime | None:
    return None if ctx is None else ctx.now


def _ctx_world_locations(ctx: ToolContext | None) -> Any:
    """世界地点读面：`ToolContext.world["locations"]`；上下文缺失返回 None。"""
    return None if ctx is None else ctx.world_locations()


def _comparable(left: datetime, right: datetime) -> tuple[datetime, datetime]:
    """时区对齐：一侧带 tz 时统一到另一侧，避免 naive/aware 比较抛错。"""
    if (left.tzinfo is None) == (right.tzinfo is None):
        return left, right
    if left.tzinfo is not None:
        return left.replace(tzinfo=None), right
    return left, right.replace(tzinfo=None)


def _as_texts(values: Any) -> set[str]:
    if values is None or isinstance(values, (str, bytes)):
        return set()
    try:
        return {str(item) for item in values}
    except TypeError:
        return set()


def _future_datetime(params: dict[str, Any], ctx: ToolContext) -> list[str]:
    due = parse_iso8601(params.get("due_at"))
    if due is None:
        return []
    now = _ctx_now(ctx)
    if now is None:
        logger.info("future_datetime 降级放行：ToolContext.now 未提供")
        return []
    due_cmp, now_cmp = _comparable(due, now)
    if due_cmp <= now_cmp:
        return [f"due_at 必须晚于当前时间：due_at={due_cmp.isoformat()}, now={now_cmp.isoformat()}"]
    return []


def _location_exists(params: dict[str, Any], ctx: ToolContext) -> list[str]:
    location = params.get("location")
    if location is None:
        return []
    known = _as_texts(_ctx_world_locations(ctx))
    if not known:
        logger.info(
            "location_exists 降级放行：ToolContext.world['locations'] 未装配（TOOL-007）"
        )
        return []
    if str(location) not in known:
        return [f"location 不存在于当前世界：{location}"]
    return []


def _object_in_inventory(params: dict[str, Any], ctx: ToolContext) -> list[str]:
    """库存语义校验：世界事实**已装配**（`world_enabled` 键存在且为真）时，
    `inventory=[]` 表示确实没有物品 → 任意 object 判失败（TOOL-007 E4）；
    未装配 / 世界不可用 / 上下文缺失 → 信息不足，降级放行。"""
    obj = params.get("object")
    if obj is None:
        return []
    trustworthy = _world_facts_trustworthy(ctx)
    inventory = _as_texts(None if ctx is None else ctx.inventory)
    if not inventory and trustworthy is not True:
        logger.info("object_in_inventory 降级放行：ToolContext.inventory 未装配（TOOL-007）")
        return []
    if str(obj) not in inventory:
        return [f"object 不在当前库存内：{obj}"]
    return []


def _world_facts_trustworthy(ctx: ToolContext | None) -> bool | None:
    """世界事实可信度：已装配且世界可用 → True；未装配 / 世界不可用 → None（降级）。"""
    return None if ctx is None else ctx.world_facts_enabled()


def _recipient_authorized(params: dict[str, Any], ctx: ToolContext) -> list[str]:
    recipient = params.get("recipient") or params.get("to")
    if recipient is None:
        return []
    authorized = _as_texts(ctx.authorized_recipients)
    if not authorized:
        logger.info("recipient_authorized 降级放行：ToolContext.authorized_recipients 未装配（TOOL-005）")
        return []
    if str(recipient) not in authorized:
        return [f"收件人未授权：{recipient}"]
    return []


def _content_within_budget(params: dict[str, Any], ctx: ToolContext) -> list[str]:
    """正文预算（TOOL-010 §2.2）：逐字段判定 `content` / `query` / `fact` / `target` / `object`。

    工具级的长度预算由结构层的 `ToolParameter.max_length` 承担（如通道 ≤ 200、检索 ≤ 60）；
    本校验器是**语义层安全网**（全局 `CONTENT_BUDGET_CHARS`），保证任何进入正文位的字段
    都不会把超长文本带进出站或台账。
    """
    for key in _BUDGET_PARAM_KEYS:
        value = params.get(key)
        if not isinstance(value, str):
            continue
        if len(value) > CONTENT_BUDGET_CHARS:
            return [f"{key} 长度 {len(value)} 超出预算 {CONTENT_BUDGET_CHARS}"]
    return []


BUILTIN_SEMANTIC_VALIDATORS: dict[str, SemanticValidator] = {
    "future_datetime": _future_datetime,
    "location_exists": _location_exists,
    "object_in_inventory": _object_in_inventory,
    "recipient_authorized": _recipient_authorized,
    "content_within_budget": _content_within_budget,
}


class ParamValidator:
    """声明驱动校验器：结构层逐参数执行，语义层按工具声明的名字派发。"""

    def __init__(self, semantic_validators: dict[str, SemanticValidator] | None = None) -> None:
        self._semantic: dict[str, SemanticValidator] = dict(
            BUILTIN_SEMANTIC_VALIDATORS if semantic_validators is None else semantic_validators
        )

    def register_semantic(self, name: str, fn: SemanticValidator) -> None:
        """注册语义校验器：`fn(params, ctx) -> list[str]`，空列表表示通过。"""
        if not isinstance(name, str) or not name:
            raise ValueError("语义校验器名不得为空")
        if not callable(fn):
            raise ValueError(f"语义校验器必须是可调用对象: {name}")
        self._semantic[name] = fn

    def semantic_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._semantic))

    def validate(
        self, defn: ToolDefinition, params: dict[str, Any], ctx: ToolContext | None = None
    ) -> ValidationReport:
        schema = defn.input_schema
        declared_names = {parameter.name for parameter in schema.parameters}
        structural: list[dict[str, Any]] = []
        normalized: dict[str, Any] = {}
        for parameter in schema.parameters:
            value = params.get(parameter.name)
            if _is_blank(value):
                if parameter.required:
                    structural.append(
                        _issue(
                            parameter.name,
                            "missing_required",
                            f"缺少必需参数: {parameter.name}",
                        )
                    )
                continue
            issues, normalized_value = _structural_issues(parameter, value)
            structural.extend(issues)
            if not issues:
                normalized[parameter.name] = normalized_value
        for name in sorted(params):
            if name in declared_names:
                continue
            if schema.strict:
                structural.append(
                    _issue(
                        name,
                        "unknown_param",
                        f"未声明的参数: {name}（strict 模式拒绝）",
                    )
                )
            else:
                logger.info("未声明参数被忽略（strict=False）：%s", name)
        semantic: list[dict[str, Any]] = []
        if not structural:
            semantic = self._run_semantic(defn, normalized, ctx)
        return ValidationReport(
            passed=not structural and not semantic,
            structural=structural,
            semantic=semantic,
            normalized=normalized,
        )

    def _run_semantic(
        self,
        defn: ToolDefinition,
        params: dict[str, Any],
        ctx: ToolContext | None,
    ) -> list[dict[str, Any]]:
        semantic: list[dict[str, Any]] = []
        for name in defn.input_schema.semantic_validators:
            validator = self._semantic.get(name)
            if validator is None:
                semantic.append(
                    _issue("", UNKNOWN_VALIDATOR_CODE, f"未注册的语义校验器: {name}")
                )
                continue
            try:
                messages = validator(params, ctx)
            except Exception:
                logger.exception("语义校验器执行异常，按默认拒绝处理：%s", name)
                semantic.append(_issue("", name, f"语义校验器执行异常: {name}"))
                continue
            target = next(
                (hint for hint in _SEMANTIC_PARAM_HINTS.get(name, ()) if hint in params), ""
            )
            code = _SEMANTIC_CODE_BY_NAME.get(name, name)
            for message in messages:
                semantic.append(_issue(target, code, str(message)))
        return semantic


_default_validator: ParamValidator | None = None


def get_param_validator() -> ParamValidator:
    """模块级默认校验器（含五个内置语义校验器）；只读消费，注册走实例。"""
    global _default_validator
    if _default_validator is None:
        _default_validator = ParamValidator()
    return _default_validator
