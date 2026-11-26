"""TOOL-003 §6.1：参数校验双层 / 规范化幂等 / 语义校验器（E3~E6、E11）。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models.tool import ToolSchema
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.validator import (
    BUILTIN_SEMANTIC_VALIDATORS,
    CONTENT_BUDGET_CHARS,
    SEMANTIC_ERROR_CODES,
    STRUCTURAL_ERROR_CODES,
    UNKNOWN_VALIDATOR_CODE,
    ParamValidator,
)
from tests.v24.tool002_support import definition, schema
from tests.v24.tool003_support import param

BACKEND_ROOT = Path(__file__).resolve().parents[2]

NOW = datetime(2026, 6, 1, 12, 0, 0)

VALIDATOR = ParamValidator()


def _ctx(**overrides) -> ToolContext:
    payload = {"user_id": "u-1", "now": NOW}
    payload.update(overrides)
    return ToolContext(**payload)


def _codes(report, bucket: str = "structural") -> list[str]:
    return [issue["code"] for issue in getattr(report, bucket)]


def _due_params(due_at: str = "2026-06-02T08:00:00") -> dict:
    return {"content": "买牛奶", "due_at": due_at}


def _reminder_schema():
    """content / due_at / importance 三参声明（TOOL-002 内置声明同形）。"""
    return schema(
        param("content", required=True),
        param("due_at", "datetime", required=True, format_="iso8601"),
        param("importance", "enum", enum=("low", "normal", "high"), default="normal"),
    )


def _with_validators(validators: tuple[str, ...], parameters) -> object:
    return definition(
        input_schema=ToolSchema(parameters=list(parameters), semantic_validators=validators)
    )


# --- 结构层八类错误码 ---------------------------------------------------------


def test_missing_required():
    report = VALIDATOR.validate(definition(), {"due_at": "2026-06-02T08:00:00"}, _ctx())
    assert report.passed is False
    assert _codes(report) == ["missing_required"]
    assert report.structural[0]["param"] == "content"
    assert "content" not in report.normalized


def test_missing_required_treats_blank_string_as_missing():
    report = VALIDATOR.validate(definition(), {"content": "   ", "due_at": "2026-06-02T08:00:00"}, _ctx())
    assert _codes(report) == ["missing_required"]


def test_type_mismatch():
    report = VALIDATOR.validate(
        definition(input_schema=schema(param("quantity", "number", required=True))),
        {"quantity": "两个"},
        _ctx(),
    )
    assert _codes(report) == ["type_mismatch"]
    assert report.normalized == {}


def test_enum_invalid():
    report = VALIDATOR.validate(
        definition(input_schema=schema(param("importance", "enum", enum=("low", "normal")))),
        {"importance": "urgent"},
        _ctx(),
    )
    assert _codes(report) == ["enum_invalid"]


def test_range_violated_both_bounds():
    bounded = schema(param("importance", "number", min_value=0, max_value=1))
    low = VALIDATOR.validate(definition(input_schema=bounded), {"importance": -0.5}, _ctx())
    high = VALIDATOR.validate(definition(input_schema=bounded), {"importance": 1.5}, _ctx())
    assert _codes(low) == ["range_violated"]
    assert _codes(high) == ["range_violated"]


def test_length_violated_both_bounds():
    bounded = schema(param("content", min_length=2, max_length=5))
    short = VALIDATOR.validate(definition(input_schema=bounded), {"content": "a"}, _ctx())
    long = VALIDATOR.validate(definition(input_schema=bounded), {"content": "abcdef"}, _ctx())
    assert _codes(short) == ["length_violated"]
    assert _codes(long) == ["length_violated"]


def test_pattern_mismatch():
    patterned = schema(param("target", pattern=r"^evt-\d+$"))
    ok = VALIDATOR.validate(definition(input_schema=patterned), {"target": "evt-12"}, _ctx())
    bad = VALIDATOR.validate(definition(input_schema=patterned), {"target": "abc"}, _ctx())
    assert ok.passed is True
    assert _codes(bad) == ["pattern_mismatch"]


def test_format_invalid_for_declared_formats():
    iso = schema(param("due_at", "datetime", required=True, format_="iso8601"))
    email = schema(param("recipient", format_="email"))
    assert _codes(VALIDATOR.validate(definition(input_schema=iso), {"due_at": "明天"}, _ctx())) == [
        "format_invalid"
    ]
    assert _codes(
        VALIDATOR.validate(definition(input_schema=email), {"recipient": "not-an-email"}, _ctx())
    ) == ["format_invalid"]


def test_unknown_format_is_not_judged():
    report = VALIDATOR.validate(
        definition(input_schema=schema(param("content", format_="custom-format"))),
        {"content": "任意内容"},
        _ctx(),
    )
    assert report.passed is True


def test_unknown_param_strict_rejects_e3():
    report = VALIDATOR.validate(definition(), {**_due_params(), "hallucinated": 1}, _ctx())
    assert report.passed is False
    assert _codes(report) == ["unknown_param"]
    assert report.structural[0]["param"] == "hallucinated"
    assert "hallucinated" not in report.normalized


def test_unknown_param_non_strict_ignored_e4():
    loose = definition(
        input_schema=ToolSchema(
            parameters=list(definition().input_schema.parameters), strict=False
        )
    )
    report = VALIDATOR.validate(loose, {**_due_params(), "hallucinated": 1}, _ctx())
    assert report.passed is True
    assert report.structural == []
    assert report.normalized == {"content": "买牛奶", "due_at": "2026-06-02T08:00:00"}


def test_eight_structural_codes_are_all_reachable():
    cases = [
        (definition(), {"due_at": "2026-06-02T08:00:00"}),
        (definition(input_schema=schema(param("quantity", "number"))), {"quantity": "两个"}),
        (definition(input_schema=schema(param("importance", "enum", enum=("low",)))), {"importance": "high"}),
        (definition(input_schema=schema(param("importance", "number", max_value=1))), {"importance": 9}),
        (definition(input_schema=schema(param("content", max_length=2))), {"content": "abcdef"}),
        (definition(input_schema=schema(param("target", pattern=r"^e$"))), {"target": "x"}),
        (definition(input_schema=schema(param("due_at", "datetime", format_="iso8601"))), {"due_at": "x"}),
        (definition(), {**_due_params(), "ghost": 1}),
    ]
    reached = set()
    for defn, params in cases:
        reached.update(_codes(VALIDATOR.validate(defn, params, _ctx())))
    assert reached == set(STRUCTURAL_ERROR_CODES)


# --- 规范化 ------------------------------------------------------------------


def test_normalized_unifies_time_whitespace_and_enum():
    report = VALIDATOR.validate(
        definition(input_schema=_reminder_schema()),
        {"content": "  买   牛奶 ", "due_at": "2026-06-02T08:00:00Z", "importance": "HIGH"},
        _ctx(),
    )
    assert report.passed is True
    assert report.normalized == {
        "content": "买 牛奶",
        "due_at": "2026-06-02T08:00:00+00:00",
        "importance": "high",
    }


def test_normalized_is_idempotent():
    first = VALIDATOR.validate(
        definition(input_schema=_reminder_schema()),
        {"content": " 买  牛奶", "due_at": "2026-06-02 08:00:00", "importance": " Normal "},
        _ctx(),
    )
    assert first.passed is True
    second = VALIDATOR.validate(definition(input_schema=_reminder_schema()), first.normalized, _ctx())
    assert second.passed is True
    assert second.normalized == first.normalized


def test_normalized_normalizes_array_items_and_stringifies_scalars():
    defn = definition(
        input_schema=schema(
            param("quantity", "integer"),
            param("enabled", "boolean"),
            param("tags", "array"),
            param("content"),
        )
    )
    report = VALIDATOR.validate(
        defn,
        {"quantity": 3, "enabled": True, "tags": [" a ", "b"], "content": 42},
        _ctx(),
    )
    assert report.passed is True
    assert report.normalized == {
        "quantity": 3,
        "enabled": True,
        "tags": ["a", "b"],
        "content": "42",
    }
    assert VALIDATOR.validate(defn, report.normalized, _ctx()).normalized == report.normalized


def test_numeric_string_is_type_mismatch_not_coerced():
    defn = definition(input_schema=schema(param("quantity", "integer")))
    assert _codes(VALIDATOR.validate(defn, {"quantity": "3"}, _ctx())) == ["type_mismatch"]


def test_report_shape_is_frozen():
    report = VALIDATOR.validate(definition(), _due_params(), _ctx())
    assert set(report.model_dump()) == {"passed", "structural", "semantic", "normalized"}
    assert report.structural == []
    assert report.semantic == []


def test_normalized_does_not_inject_declared_defaults():
    defn = definition(
        input_schema=schema(
            param("content", required=True),
            param("due_at", "datetime", required=True, format_="iso8601"),
            param("importance", "enum", enum=("low", "normal", "high"), default="normal"),
        )
    )
    report = VALIDATOR.validate(defn, _due_params(), _ctx())
    assert report.passed is True
    assert "importance" not in report.normalized


def test_optional_blank_string_is_skipped_not_normalized():
    report = VALIDATOR.validate(
        definition(input_schema=_reminder_schema()), {**_due_params(), "importance": "  "}, _ctx()
    )
    assert report.passed is True
    assert "importance" not in report.normalized


def test_required_datetime_accepts_datetime_object_and_normalizes():
    report = VALIDATOR.validate(
        definition(), {"content": "x", "due_at": NOW + timedelta(hours=1)}, _ctx()
    )
    assert report.passed is True
    assert report.normalized["due_at"] == (NOW + timedelta(hours=1)).isoformat()


# --- 语义层五类错误码 --------------------------------------------------------


def test_not_future_rejects_past_and_accepts_future():
    defn = _with_validators(("future_datetime",), definition().input_schema.parameters)
    past = VALIDATOR.validate(defn, _due_params("2026-05-31T08:00:00"), _ctx())
    future = VALIDATOR.validate(defn, _due_params("2026-06-02T08:00:00"), _ctx())
    assert past.passed is False
    assert _codes(past, "semantic") == ["not_future"]
    assert past.semantic[0]["param"] == "due_at"
    assert future.passed is True


def test_not_future_equal_to_now_is_rejected():
    defn = _with_validators(("future_datetime",), definition().input_schema.parameters)
    assert _codes(VALIDATOR.validate(defn, _due_params(NOW.isoformat()), _ctx()), "semantic") == [
        "not_future"
    ]


def test_location_exists():
    defn = _with_validators(("location_exists",), [param("location", required=True)])
    world = {"locations": ("home", "workshop")}
    ok = VALIDATOR.validate(defn, {"location": "workshop"}, _ctx(world=world))
    bad = VALIDATOR.validate(defn, {"location": "kitchen"}, _ctx(world=world))
    assert ok.passed is True
    assert _codes(bad, "semantic") == ["location_not_found"]
    assert bad.semantic[0]["param"] == "location"


def test_object_in_inventory():
    defn = _with_validators(("object_in_inventory",), [param("object", required=True)])
    ok = VALIDATOR.validate(defn, {"object": "苹果"}, _ctx(inventory=["苹果"]))
    bad = VALIDATOR.validate(defn, {"object": "梨"}, _ctx(inventory=["苹果"]))
    assert ok.passed is True
    assert _codes(bad, "semantic") == ["object_not_in_inventory"]


def test_recipient_authorized():
    defn = _with_validators(("recipient_authorized",), [param("recipient", required=True)])
    ok = VALIDATOR.validate(defn, {"recipient": "u-9"}, _ctx(authorized_recipients=["u-9"]))
    bad = VALIDATOR.validate(defn, {"recipient": "u-8"}, _ctx(authorized_recipients=["u-9"]))
    assert ok.passed is True
    assert _codes(bad, "semantic") == ["recipient_not_authorized"]


def test_content_within_budget():
    defn = _with_validators(("content_within_budget",), [param("content", required=True)])
    ok = VALIDATOR.validate(defn, {"content": "短内容"}, _ctx())
    over = VALIDATOR.validate(defn, {"content": "长" * (CONTENT_BUDGET_CHARS + 1)}, _ctx())
    assert ok.passed is True
    assert _codes(over, "semantic") == ["content_over_budget"]


def test_five_semantic_codes_are_all_reachable():
    cases = [
        (_with_validators(("future_datetime",), definition().input_schema.parameters), _due_params("2026-05-01T00:00:00"), _ctx()),
        (_with_validators(("location_exists",), [param("location", required=True)]), {"location": "x"}, _ctx(world={"locations": ("y",)})),
        (_with_validators(("object_in_inventory",), [param("object", required=True)]), {"object": "x"}, _ctx(inventory=["y"])),
        (_with_validators(("recipient_authorized",), [param("recipient", required=True)]), {"recipient": "x"}, _ctx(authorized_recipients=["y"])),
        (_with_validators(("content_within_budget",), [param("content", required=True)]), {"content": "x" * (CONTENT_BUDGET_CHARS + 1)}, _ctx()),
    ]
    reached = set()
    for defn, params, ctx in cases:
        reached.update(_codes(VALIDATOR.validate(defn, params, ctx), "semantic"))
    assert reached == set(SEMANTIC_ERROR_CODES)


# --- 上下文缺失降级（E6）与失败兜底 ------------------------------------------


@pytest.mark.parametrize(
    "validators,params",
    [
        (("location_exists",), {"location": "kitchen"}),
        (("object_in_inventory",), {"object": "梨"}),
        (("recipient_authorized",), {"recipient": "u-9"}),
    ],
)
def test_semantic_downgrade_when_context_field_absent_e6(validators, params):
    defn = _with_validators(validators, [param(name, required=True) for name in params])
    report = VALIDATOR.validate(defn, params, _ctx())
    assert report.passed is True
    assert report.semantic == []


def test_semantic_downgrade_when_context_field_empty_is_also_permissive():
    defn = _with_validators(("location_exists",), [param("location", required=True)])
    report = VALIDATOR.validate(defn, {"location": "kitchen"}, _ctx(world={"locations": ()}))
    assert report.passed is True


def test_future_datetime_downgrades_without_now():
    defn = _with_validators(("future_datetime",), definition().input_schema.parameters)
    report = VALIDATOR.validate(defn, _due_params("2000-01-01T00:00:00"), ToolContext(user_id="u"))
    assert report.passed is True


def test_semantic_validators_skip_when_structural_fails():
    defn = _with_validators(("future_datetime",), definition().input_schema.parameters)
    report = VALIDATOR.validate(
        defn, {"content": "x", "due_at": "2000-01-01T00:00:00", "ghost": 1}, _ctx()
    )
    assert _codes(report) == ["unknown_param"]
    assert report.semantic == []


def test_unknown_semantic_validator_fails_closed():
    defn = _with_validators(("nope_validator",), definition().input_schema.parameters)
    report = VALIDATOR.validate(defn, _due_params(), _ctx())
    assert report.passed is False
    assert _codes(report, "semantic") == [UNKNOWN_VALIDATOR_CODE]


def test_semantic_validator_exception_fails_closed():
    validator = ParamValidator()
    validator.register_semantic("future_datetime", lambda params, ctx: 1 / 0)
    defn = _with_validators(("future_datetime",), definition().input_schema.parameters)
    report = validator.validate(defn, _due_params(), _ctx())
    assert report.passed is False
    assert _codes(report, "semantic") == ["future_datetime"]


def test_register_semantic_custom_validator():
    defn = _with_validators(("no_shouting",), definition().input_schema.parameters)
    validator = ParamValidator()
    validator.register_semantic(
        "no_shouting",
        lambda params, ctx: ["content 不得全大写"] if str(params.get("content", "")).isupper() else [],
    )
    assert "no_shouting" in validator.semantic_names()
    assert validator.validate(defn, {"content": "OK", "due_at": "2026-06-02T08:00:00"}, _ctx()).passed is False
    assert validator.validate(defn, {"content": "ok", "due_at": "2026-06-02T08:00:00"}, _ctx()).passed is True


def test_register_semantic_rejects_invalid_input():
    validator = ParamValidator()
    with pytest.raises(ValueError):
        validator.register_semantic("", lambda params, ctx: [])
    with pytest.raises(ValueError):
        validator.register_semantic("x", "not-callable")


def test_builtin_semantic_validators_cover_documented_names():
    assert set(BUILTIN_SEMANTIC_VALIDATORS) == {
        "future_datetime",
        "location_exists",
        "object_in_inventory",
        "recipient_authorized",
        "content_within_budget",
    }
    assert set(ParamValidator().semantic_names()) == set(BUILTIN_SEMANTIC_VALIDATORS)


def test_semantic_validators_are_declared_on_builtin_tools():
    """TOOL-010｜按 §2.2 表补全绑定：提醒追加正文预算、移动追加库存校验，
    并新增通道工具（收件人授权 + 正文预算）。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    assert registry.get("builtin.reminder.create").input_schema.semantic_validators == (
        "future_datetime",
        "content_within_budget",
    )
    assert registry.get("world.object.move").input_schema.semantic_validators == (
        "object_in_inventory",
        "location_exists",
    )
    assert registry.get("world.object.use").input_schema.semantic_validators == (
        "object_in_inventory",
    )
    assert registry.get("channel.feishu.send").input_schema.semantic_validators == (
        "recipient_authorized",
        "content_within_budget",
    )
    declared = {
        name
        for item in registry.list()
        for name in item.input_schema.semantic_validators
    }
    assert declared <= set(BUILTIN_SEMANTIC_VALIDATORS)
    assert declared == {
        "future_datetime",
        "location_exists",
        "object_in_inventory",
        "recipient_authorized",
        "content_within_budget",
    }


def test_declared_validators_are_all_registered():
    from app.services.tool.normalizer import TOOL_OBSERVATION_MAP

    registry = ToolRegistry()
    register_builtin_tools(registry)
    validator = ParamValidator()
    for item in registry.list():
        for name in item.input_schema.semantic_validators:
            assert name in validator.semantic_names(), name
    assert set(TOOL_OBSERVATION_MAP) <= {item.id for item in registry.list()}


def test_validator_module_has_no_io_imports():
    source = (BACKEND_ROOT / "app/services/tool/validator.py").read_text(encoding="utf-8")
    for forbidden in ("app.repositories", "sqlalchemy", "httpx", "requests", "SessionLocal"):
        assert forbidden not in source


def test_timezone_mixed_comparison_does_not_raise():
    defn = _with_validators(("future_datetime",), definition().input_schema.parameters)
    aware = _ctx(now=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc))
    assert VALIDATOR.validate(defn, _due_params("2026-06-02T08:00:00"), aware).passed is True
    assert _codes(
        VALIDATOR.validate(defn, _due_params("2026-05-01T08:00:00"), aware), "semantic"
    ) == ["not_future"]


def test_declared_max_length_blocks_oversized_string_e11():
    defn = definition(input_schema=schema(param("content", max_length=100)))
    report = VALIDATOR.validate(defn, {"content": "x" * 10_000}, _ctx())
    assert _codes(report) == ["length_violated"]
    assert report.normalized == {}
