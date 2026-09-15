"""TOOL-008 §6.1/§6.3：工具记忆边界表、三条硬纪律、失败四态与模板渲染（纯函数面）。"""

from typing import Any

import pytest

from app.character.asuna.tool import TOOL_MEMORY_TEMPLATES, render
from app.services.tool import memory_policy as mp
from tests.v24.tool008_support import record, tool_definition

POLICY = mp.get_tool_memory_policy()

REMINDER_PARAMS: dict[str, Any] = {"content": "开会", "due_at": "2026-09-20T08:00:00"}
CANCEL_PARAMS: dict[str, Any] = {"target": "开会"}
OBJECT_PARAMS: dict[str, Any] = {"object": "牛奶"}
NOTIFY_PARAMS: dict[str, Any] = {"content": "喝水"}

TEMPLATE_REMINDER_CREATE = "用户请我提醒：开会"
"""P1-3：模板文案去掉未消解人称代词（原「用户请我提醒他：…」被 R8 恒定拒收）。"""

BOUNDARY_ROWS: tuple[tuple[str, dict[str, Any], dict[str, Any], str], ...] = (
    (
        "builtin.reminder.create",
        {"deposit": True, "memory_type": "important_event", "importance": 0.7, "source": "user_derived"},
        REMINDER_PARAMS,
        "policy_deposit",
    ),
    (
        "builtin.reminder.cancel",
        {"deposit": True, "memory_type": "important_event", "importance": 0.5, "source": "user_derived"},
        CANCEL_PARAMS,
        "policy_deposit",
    ),
    ("builtin.memory.save", {"deposit": "skip", "source": "user_stated"}, {"fact": "喜欢抹茶"}, "policy_skip"),
    (
        "world.object.create",
        {"deposit": True, "memory_type": "user_preference", "importance": 0.5, "source": "user_derived"},
        OBJECT_PARAMS,
        "policy_deposit",
    ),
    ("world.object.move", {"deposit": False}, {"object": "牛奶", "location": "冰箱"}, "policy_declined"),
    ("world.object.use", {"deposit": False}, OBJECT_PARAMS, "policy_declined"),
    ("world.env.query", {"deposit": False}, {"dimension": "weather"}, "read_only_tool"),
    ("builtin.search.query", {"deposit": False}, {"query": "明天天气"}, "read_only_tool"),
    (
        "builtin.notification.send",
        {"deposit": True, "memory_type": "important_event", "importance": 0.6, "source": "ai_inferred"},
        NOTIFY_PARAMS,
        "policy_deposit",
    ),
    (
        "channel.feishu.send",
        {"deposit": True, "memory_type": "important_event", "importance": 0.6, "source": "ai_inferred"},
        NOTIFY_PARAMS,
        "policy_deposit",
    ),
)

TEMPLATE_CASES: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("builtin.reminder.create", REMINDER_PARAMS, TEMPLATE_REMINDER_CREATE),
    ("builtin.reminder.cancel", CANCEL_PARAMS, "用户不想再被提醒：开会"),
    ("world.object.create", OBJECT_PARAMS, "用户请我准备：牛奶"),
    ("builtin.notification.send", NOTIFY_PARAMS, "我主动提醒了用户：喝水"),
    ("channel.feishu.send", NOTIFY_PARAMS, "我主动给用户发了消息：喝水"),
)

EXPECTED_TEMPLATES: dict[str, str] = {
    "builtin.reminder.create": "用户请我提醒：{content}",
    "builtin.reminder.cancel": "用户不想再被提醒：{target}",
    "builtin.memory.save": "用户告诉我：{fact}",
    "world.object.create": "用户请我准备：{object}",
    "builtin.notification.send": "我主动提醒了用户：{content}",
    "channel.feishu.send": "我主动给用户发了消息：{content}",
}

DECLINED_KEYS = ("world.object.move", "world.object.use", "world.env.query", "builtin.search.query")

UNTREATED_STATUSES: tuple[tuple[str, str | None], ...] = (
    ("created", None),
    ("planned", None),
    ("executing", None),
    ("cancelled", "permission_denied"),
    ("cancelled", "invalid_params"),
    ("cancelled", "capability_unavailable"),
    ("planned", "pending_confirmation"),
)


# --- 边界表（§6.1） -----------------------------------------------------------


def test_boundary_table_covers_spec_rows():
    assert set(mp.BOUNDARY_TABLE) == {
        "builtin.reminder.create",
        "builtin.reminder.cancel",
        "builtin.memory.save",
        "world.object.create",
        "world.object.move",
        "world.object.use",
        "world.env.query",
        "builtin.search.query",
        "builtin.notification.send",
        "channel.feishu.send",
    }
    assert set(mp.BOUNDARY_PREFIX_TABLE) == {"ext.api.", "user."}


@pytest.mark.parametrize("key,row,params,reason", BOUNDARY_ROWS)
def test_boundary_row_lookup_and_classification(key, row, params, reason):
    assert POLICY.row_for(key) == row
    decision = POLICY.classify(
        record(key, params=params), tool_definition(key)
    )
    assert decision.reason == reason
    assert decision.deposit == row["deposit"]


def test_row_for_unknown_key_returns_none():
    assert POLICY.row_for("builtin.unknown.tool") is None
    assert POLICY.row_for("") is None


def test_row_for_returns_copy_not_internal_row():
    row = POLICY.row_for("world.env.query")
    row["deposit"] = True
    assert POLICY.row_for("world.env.query") == {"deposit": False}


def test_prefix_rows_cover_untrusted_namespaces():
    assert POLICY.row_for("ext.api.weather.current") == {"deposit": False}
    assert POLICY.row_for("user.custom.keep_note") == {"deposit": False}


def test_classify_without_tool_id_has_no_policy_row():
    decision = POLICY.classify(record(None), None)
    assert decision.deposit is False
    assert decision.reason == mp.REASON_NO_POLICY_ROW


# --- 三条硬纪律（配置违背负例） ------------------------------------------------


def test_read_only_tool_ignores_configured_deposit():
    violating = mp.ToolMemoryPolicy(
        rows={
            "world.env.query": {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.9,
                "source": "user_derived",
            }
        }
    )
    decision = violating.classify(
        record("world.env.query", params={"dimension": "weather"}),
        tool_definition("world.env.query", side_effects=("read",)),
    )
    assert decision.deposit is False
    assert decision.reason == mp.REASON_READ_ONLY
    assert violating.to_candidates(
        record("world.env.query", params={"dimension": "weather"}),
        tool_definition("world.env.query", side_effects=("read",)),
    ) == []


@pytest.mark.parametrize(
    "tool_id,namespace",
    (("ext.api.weather.current", "ext.api"), ("user.custom.keep_note", "user")),
)
def test_untrusted_namespace_ignores_configured_deposit(tool_id, namespace):
    violating = mp.ToolMemoryPolicy(
        rows={
            tool_id: {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.9,
                "source": "user_derived",
            }
        },
        prefix_rows={},
    )
    defn = tool_definition(
        tool_id, namespace=namespace, side_effects=("write_world",)
    )
    decision = violating.classify(record(tool_id, params={"content": "开会"}), defn)
    assert decision.deposit is False
    assert decision.reason == mp.REASON_UNTRUSTED_SOURCE


def test_untrusted_rule_holds_without_definition():
    decision = POLICY.classify(record("ext.api.weather.current"), None)
    assert decision.deposit is False
    assert decision.reason == mp.REASON_UNTRUSTED_SOURCE


def test_mixed_side_effects_is_not_read_only():
    """E11：`read` 与 `write_memory` 混合时不按读类误判，仍走边界表判定。"""
    defn = tool_definition(
        "world.env.query", side_effects=("read", "write_memory")
    )
    decision = POLICY.classify(record("world.env.query"), defn)
    assert decision.reason == mp.REASON_POLICY_DECLINED
    configured = mp.ToolMemoryPolicy(
        rows={
            "world.env.query": {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.9,
                "source": "user_derived",
            }
        }
    )
    assert configured.classify(record("world.env.query"), defn).deposit is True


def test_read_class_rows_decline_by_hard_discipline_without_role_declaration():
    """读类工具的两重保险：声明侧命中①，边界表侧同时是显式 ❌ 行。"""
    for key in ("world.env.query", "builtin.search.query"):
        assert POLICY.row_for(key) == {"deposit": False}
        assert (
            POLICY.classify(record(key), tool_definition(key, side_effects=("write_world",))).reason
            == mp.REASON_POLICY_DECLINED
        )


def test_unclassified_side_effects_are_treated_as_read_only():
    defn = tool_definition("world.env.query", side_effects=())
    decision = POLICY.classify(record("world.env.query"), defn)
    assert decision.deposit is False
    assert decision.reason == mp.REASON_READ_ONLY


# --- 失败四态与未执行态（§2.3 / §6.3） ----------------------------------------


@pytest.mark.parametrize("status,gate_reason", UNTREATED_STATUSES)
def test_unexecuted_states_never_deposit(status, gate_reason):
    rec = record(
        "builtin.reminder.create",
        params=REMINDER_PARAMS,
        status=status,
        gate_reason=gate_reason,
    )
    assert POLICY.to_candidates(rec, None) == []


def test_failed_with_gate_reason_never_deposits():
    """E3：failed + gate_reason 非空 = 未执行，不是失败。"""
    rec = record(
        "builtin.reminder.create",
        params=REMINDER_PARAMS,
        status="failed",
        gate_reason="permission_denied",
    )
    assert POLICY.to_candidates(rec, None) == []


def test_failed_without_gate_reason_deposits_failure_shape():
    rec = record("builtin.reminder.create", params=REMINDER_PARAMS, status="failed")
    candidates = POLICY.to_candidates(rec, None)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.type == "important_event"
    assert candidate.importance >= 0.6
    assert candidate.content == "上次没能帮用户完成：用户请我提醒：开会"


def test_timeout_step_deposits_as_true_failure():
    """E4：timeout 属真失败（可被反思消费）。"""
    rec = record(
        "builtin.reminder.create",
        params=REMINDER_PARAMS,
        status="failed",
        failure_kind="timeout",
    )
    candidates = POLICY.to_candidates(rec, None)
    assert len(candidates) == 1
    assert candidates[0].importance >= 0.6
    assert candidates[0].content.startswith("上次没能帮用户完成：")


def test_timeout_record_status_deposits():
    rec = record("builtin.reminder.create", params=REMINDER_PARAMS).model_copy(
        update={"status": "timeout"}
    )
    assert mp.delivery_status(rec) == mp.STATUS_TIMEOUT
    assert len(POLICY.to_candidates(rec, None)) == 1


def test_pending_confirmation_then_succeeded_deposits_once():
    """E12：未送达不沉淀；确认后成功轮次才沉淀。"""
    pending = record(
        "builtin.reminder.create",
        params=REMINDER_PARAMS,
        status="planned",
        gate_reason="pending_confirmation",
    )
    assert POLICY.to_candidates(pending, None) == []
    succeeded = pending.model_copy(update={"status": "succeeded", "gate_reason": None})
    assert len(POLICY.to_candidates(succeeded, None)) == 1


def test_skip_row_yields_no_candidates():
    """E5：`builtin.memory.save` 直通，不二次投递。"""
    decision = POLICY.classify(
        record("builtin.memory.save", params={"fact": "喜欢抹茶"}),
        tool_definition("builtin.memory.save"),
    )
    assert decision.deposit == mp.DEPOSIT_SKIP
    assert decision.reason == mp.REASON_POLICY_SKIP
    assert decision.source == "user_stated"
    assert (
        POLICY.to_candidates(
            record("builtin.memory.save", params={"fact": "喜欢抹茶"}),
            tool_definition("builtin.memory.save"),
        )
        == []
    )


# --- 候选构造与模板（§6.1 / §6.3） -------------------------------------------


@pytest.mark.parametrize("key,params,expected", TEMPLATE_CASES)
def test_template_content_matches_asset(key, params, expected):
    assert TOOL_MEMORY_TEMPLATES == EXPECTED_TEMPLATES
    assert render(key, params) == expected
    candidates = POLICY.to_candidates(
        record(key, params=params), tool_definition(key)
    )
    assert [candidate.content for candidate in candidates] == [expected]


def test_failure_template_wraps_rendered_content():
    assert (
        render("builtin.reminder.create", REMINDER_PARAMS, failed=True)
        == "上次没能帮用户完成：用户请我提醒：开会"
    )
    assert (
        render("builtin.reminder.create", {}, failed=True) == ""
    )


def test_render_returns_empty_without_template():
    assert render("builtin.unknown.tool", {"content": "开会"}) == ""
    assert render("", {}) == ""


def test_templates_never_trigger_r8_unresolved_reference():
    """P1-3 回归护栏：模板文案自身不得命中 R8，否则该工具的记忆通道会恒定零产出。"""
    from app.services import memory_policy as v9_memory_policy

    for key, template in TOOL_MEMORY_TEMPLATES.items():
        assert not v9_memory_policy.UNRESOLVED_REFERENCE_PATTERN.search(template), (
            f"{key} 的模板文案含未消解人称代词，会被 R8 恒定拒收：{template}"
        )


def test_missing_template_param_skips_deposit():
    """E2：渲染缺参返回空串 → 跳过沉淀（不写半成品内容）。"""
    assert render("builtin.reminder.create", {}) == ""
    assert POLICY.to_candidates(record("builtin.reminder.create", params={}), None) == []


def test_content_is_truncated_to_120_chars():
    """E8：内容超 120 字截断（V9 既有纪律）。"""
    target = "あ" * 200
    candidates = POLICY.to_candidates(
        record("builtin.reminder.cancel", params={"target": target}), None
    )
    assert len(candidates[0].content) == mp.MEMORY_CONTENT_MAX_CHARS == 120
    assert candidates[0].content == f"用户不想再被提醒：{target}"[:120]


def test_birthday_keyword_promotes_importance():
    candidates = POLICY.to_candidates(
        record("builtin.reminder.create", params={"content": "提醒我记住生日"}),
        None,
    )
    assert candidates[0].type == "user_fact"
    assert candidates[0].importance == 0.8


def test_birthday_keyword_only_applies_to_reminder_create():
    candidates = POLICY.to_candidates(
        record("builtin.notification.send", params={"content": "生日提醒"}),
        None,
    )
    assert candidates[0].type == "important_event"
    assert candidates[0].importance == 0.6


def test_declined_keys_never_produce_candidates():
    for key in DECLINED_KEYS:
        assert POLICY.to_candidates(record(key, params=NOTIFY_PARAMS), None) == []


def test_candidate_source_never_outside_declared_rows():
    for key, row, params, _reason in BOUNDARY_ROWS:
        if row["deposit"] is not True:
            continue
        candidates = POLICY.to_candidates(
            record(key, params=params), tool_definition(key)
        )
        assert [candidate.source for candidate in candidates] == [row["source"]]
        assert candidates[0].action == "save"
        assert candidates[0].confidence == mp.DEFAULT_CONFIDENCE


# --- 幂等标记（§4.1） ---------------------------------------------------------


def test_has_memory_effect_detects_registered_memory_effect():
    rec = record(
        "builtin.reminder.create",
        params=REMINDER_PARAMS,
        result={"status": "succeeded", "effects": [{"kind": "world", "ref": "evt-1"}]},
    )
    assert POLICY.has_memory_effect(rec) is False
    rec.result = {
        "status": "succeeded",
        "effects": [{"kind": "memory", "ref": "mem-1", "detail": "已记住"}],
    }
    assert POLICY.has_memory_effect(rec) is True
    assert mp.has_memory_effect(rec) is True


def test_policy_key_prefers_declared_memory_policy_key():
    defn = tool_definition("builtin.reminder.create", memory_policy_key="world.object.create")
    assert mp.policy_key_for(record("builtin.reminder.create"), defn) == "world.object.create"
    assert mp.policy_key_for(record("builtin.reminder.create"), None) == "builtin.reminder.create"
