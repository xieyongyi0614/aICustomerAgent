"""TOOL-011 受限 DSL（§2.2、§4.4、§6.1）：动作白名单 / 步骤校验 / 副作用推导。"""

import ast
from pathlib import Path

import pytest

from app.models.tool import TOOL_SIDE_EFFECT_KINDS
from app.services.tool import dsl


def _step(capability: str, action: str, **params_map) -> dict:
    step: dict = {"capability": capability, "action": action}
    if params_map:
        step["params_map"] = params_map
    return step


def test_allowed_actions_are_the_builtin_capability_actions():
    allowed = dsl.ToolDSL().allowed_actions()
    assert allowed == dsl.ALLOWED_ACTIONS
    assert ("memory", "save") in allowed
    assert ("world_action", "move") in allowed
    assert ("environment_query", "query") in allowed


def test_outbound_and_external_http_are_not_composable():
    """白名单不含外发通道与外部 HTTP：自定义工具不能包一层绕过凭据与白名单机制。"""
    allowed = dsl.allowed_actions()
    assert ("channel_feishu", "send") not in allowed
    assert ("external_api", "call") not in allowed
    assert all(capability not in {"channel_feishu", "external_api"} for capability, _ in allowed)


def test_valid_steps_pass():
    steps = [
        _step("memory", "save", fact="{params.fact}"),
        _step("environment_query", "query"),
        _step("notification", "send", content="fixed"),
    ]
    assert dsl.validate_steps(steps) == []
    assert dsl.ToolDSL().validate_steps(steps) == []


@pytest.mark.parametrize(
    ("steps", "reason"),
    [
        ([], "步骤"),
        ("not-a-list", "步骤"),
        ([{"capability": "memory", "action": "save"}], None),
    ],
)
def test_steps_shape_rules(steps, reason):
    errors = dsl.validate_steps(steps)
    if reason is None:
        assert errors == []
    else:
        assert errors


def test_steps_over_limit_are_rejected():
    steps = [_step("environment_query", "query") for _ in range(4)]
    errors = dsl.validate_steps(steps)
    assert errors
    assert "上限 3" in errors[0]


def test_exactly_three_steps_is_allowed():
    steps = [_step("environment_query", "query") for _ in range(3)]
    assert dsl.validate_steps(steps) == []


def test_non_mapping_step_is_rejected():
    assert dsl.validate_steps(["memory.save"]) != []


@pytest.mark.parametrize(
    "extra", ["code", "script", "python", "shell", "command", "exec", "eval", "http", "url", "file"]
)
def test_step_with_injected_payload_keys_is_rejected(extra):
    step = _step("memory", "save", fact="{params.fact}")
    step[extra] = "anything"
    errors = dsl.validate_steps([step])
    assert errors
    assert "安全红线" in errors[0]


@pytest.mark.parametrize(
    ("capability", "action"),
    [
        ("http", "get"),
        ("requests", "post"),
        ("urllib", "open"),
        ("subprocess", "run"),
        ("shell", "exec"),
        ("fs", "read_file"),
        ("file", "read"),
        ("eval", "call"),
    ],
)
def test_http_direct_file_access_and_code_are_rejected(capability, action):
    errors = dsl.validate_steps([_step(capability, action)])
    assert errors
    assert "安全红线" in errors[0]


@pytest.mark.parametrize(
    ("capability", "action"),
    [("memory", "read"), ("memory", "search"), ("world_action", "delete"), ("ghost", "query")],
)
def test_non_whitelisted_pairs_are_rejected(capability, action):
    errors = dsl.validate_steps([_step(capability, action)])
    assert errors
    assert "白名单" in errors[0]


def test_step_missing_capability_or_action_is_rejected():
    assert dsl.validate_steps([{"capability": "memory"}]) != []
    assert dsl.validate_steps([{"action": "save"}]) != []


def test_http_url_and_code_tokens_in_params_are_rejected():
    errors = dsl.validate_steps(
        [
            {
                "capability": "notification",
                "action": "send",
                "params_map": {"content": "https://evil.example.org/hook"},
            }
        ]
    )
    assert errors
    assert "安全红线" in errors[0]


def test_params_map_with_expression_is_rejected():
    errors = dsl.validate_steps(
        [
            {
                "capability": "memory",
                "action": "save",
                "params_map": {"fact": "{params.fact} + str(1)"},
            }
        ]
    )
    assert errors
    assert "占位符" in errors[0]


def test_params_map_shape_rules():
    base = {"capability": "memory", "action": "save"}
    assert dsl.validate_steps([{**base, "params_map": ["fact"]}]) != []
    assert dsl.validate_steps([{**base, "params_map": {"Fact": "{params.fact}"}}]) != []
    assert dsl.validate_steps([{**base, "params_map": {"fact": {"nested": 1}}}]) != []
    assert dsl.validate_steps([{**base, "params_map": {"fact": None}}]) == []
    assert dsl.validate_steps([{**base, "params_map": {"fact": 3}}]) == []


def test_derive_side_effects_from_steps_union():
    steps = [
        _step("environment_query", "query"),
        _step("memory", "save", fact="{params.fact}"),
    ]
    derived = dsl.derive_side_effects(steps)
    assert set(derived) == {"read", "write_memory"}
    assert list(derived) == [kind for kind in TOOL_SIDE_EFFECT_KINDS if kind in set(derived)]


def test_derive_side_effects_read_only_tool():
    assert dsl.derive_side_effects([_step("search", "query")]) == ("read",)


def test_derive_side_effects_ignores_unknown_steps():
    assert dsl.derive_side_effects([{"capability": "ghost", "action": "go"}]) == ()
    assert dsl.derive_side_effects(None) == ()


def test_e11_write_step_never_derives_read_only():
    """E11：声明只读但步骤含写动作 → 推导结果不含 `read` 独占形态。"""
    steps = [_step("world_action", "create", object="{params.object}")]
    derived = dsl.derive_side_effects(steps)
    assert derived == ("write_world",)
    assert not set(derived) <= {"read"}


def test_required_params_and_rendering():
    steps = [
        {
            "capability": "memory",
            "action": "save",
            "params_map": {"fact": "{params.content}", "importance": 0.8},
        }
    ]
    assert dsl.required_params(steps) == ("content",)
    assert dsl.render_params_map(steps[0]["params_map"], {"content": "今天很好"}) == {
        "fact": "今天很好",
        "importance": 0.8,
    }
    assert dsl.render_params_map(steps[0]["params_map"], {})["fact"] == ""


def test_render_params_map_bool_normalization():
    rendered = dsl.render_params_map({"k": "{params.flag}"}, {"flag": True})
    assert rendered == {"k": "true"}


def test_module_has_no_execution_primitives():
    """纪律：DSL 模块无执行原语（无 eval/exec/open/__import__，无网络/进程模块）。"""
    tree = ast.parse(Path(dsl.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in {
                    "eval",
                    "exec",
                    "open",
                    "compile",
                    "__import__",
                }, func.id
            else:
                assert getattr(func, "attr", "") not in {
                    "import_module",
                    "system",
                    "popen",
                    "spawn",
                }, getattr(func, "attr", "")
    assert imported <= {"__future__", "re", "collections", "typing", "app"}, imported
