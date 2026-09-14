"""TOOL-011 清单加载与八项校验（§2.2、§4.1、§6.1、§6.3 E1~E4 / E15 / E16）。"""

import logging
from pathlib import Path

import pytest

from app.services.tool import ext_api
from app.services.tool.registry import ToolRegistry
from tests.v24.tool011_support import (
    HOOK_ENV,
    HOOK_TOOL_ID,
    MANIFESTS_DIR,
    WEATHER_ENV,
    WEATHER_HOST,
    WEATHER_SECRET,
    WEATHER_TOOL_ID,
    CapturingHandler,
    assert_no_secret,
    ext_settings,
    hook_manifest,
    load_manifests,
    loader,
    weather_manifest,
    write_manifest,
)


@pytest.fixture
def index() -> ext_api.ManifestIndex:
    return ext_api.ManifestIndex()


@pytest.fixture
def environ() -> dict[str, str]:
    return {WEATHER_ENV: WEATHER_SECRET}


def _skip_rule(report: ext_api.LoadReport) -> int | str:
    assert len(report.skipped) == 1, report.as_dict()
    return report.skipped[0]["rule"]


def _load_one(tmp_path: Path, payload, index, **kwargs):
    registry = ToolRegistry()
    report = loader(index, kwargs.get("settings"), kwargs.get("environ")).load(
        _write(tmp_path, payload), registry
    )
    return registry, report


def _write(tmp_path: Path, payload) -> Path:
    write_manifest(tmp_path, "manifest.yaml", payload)
    return tmp_path


def test_load_success_registers_definition(tmp_path, index, environ):
    """AC：新增一个外部 API 工具 ≤ 1 个 YAML 声明文件（零 Python 改动）。"""
    registry = ToolRegistry()
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    report = loader(index, environ=environ).load(tmp_path, registry)

    assert report.loaded == [WEATHER_TOOL_ID]
    assert report.skipped == []
    assert report.total == 1
    definition = registry.get(WEATHER_TOOL_ID)
    assert definition is not None
    assert definition.namespace == "ext.api"
    assert definition.capability == "external_api"
    assert definition.action == "call"
    assert definition.permission.level == "sensitive"
    assert definition.permission.confirm == "first_time"
    assert definition.memory_policy_key == WEATHER_TOOL_ID
    assert [parameter.name for parameter in definition.input_schema.parameters] == [
        "host",
        "city",
    ]
    assert registry.effective_status(WEATHER_TOOL_ID) == "enabled"


def test_host_parameter_is_pinned_to_declared_host(tmp_path, index, environ):
    """host 参数由清单生成：required + enum 只含声明值（白名单硬禁令可判且不可绕）。"""
    registry, _ = _load_one(tmp_path, weather_manifest(), index, environ=environ)
    host_parameter = registry.get(WEATHER_TOOL_ID).input_schema.parameters[0]
    assert host_parameter.name == "host"
    assert host_parameter.required is True
    assert host_parameter.enum == (WEATHER_HOST,)
    assert host_parameter.default == WEATHER_HOST


def test_package_sample_manifests_are_loadable(tmp_path):
    """仓库自带示例清单：白名单与凭据齐备时两条都能注册（示例不含真实值）。"""
    index = ext_api.ManifestIndex()
    registry = ToolRegistry()
    report = loader(
        index, environ={WEATHER_ENV: "x", HOOK_ENV: "y"}
    ).load(MANIFESTS_DIR, registry)

    assert report.skipped == []
    assert report.loaded == [WEATHER_TOOL_ID, HOOK_TOOL_ID]
    for path in MANIFESTS_DIR.glob("*.yaml"):
        assert_no_secret(path.read_text(encoding="utf-8"))


def test_sample_manifest_without_env_is_skipped_by_rule_4(tmp_path):
    """E4：凭据环境变量缺失 → 跳过该条 + 告警（不打印变量值）。"""
    index = ext_api.ManifestIndex()
    registry = ToolRegistry()
    report = loader(index, environ={WEATHER_ENV: WEATHER_SECRET}).load(
        MANIFESTS_DIR, registry
    )
    assert report.loaded == [WEATHER_TOOL_ID]
    assert [item["tool_id"] for item in report.skipped] == [HOOK_TOOL_ID]
    assert report.skipped[0]["rule"] == 4
    assert HOOK_ENV in report.skipped[0]["reason"]


def test_e1_empty_path_loads_nothing(index):
    """E1：路径为空 → 不加载任何清单；报告为空；正常启动（不抛异常）。"""
    registry = ToolRegistry()
    report = loader(index, environ={}).load("", registry)
    assert report.as_dict() == {"path": "", "loaded": [], "skipped": [], "total": 0}
    assert index.tool_ids() == ()


def test_e1_whitespace_path_loads_nothing(index):
    registry = ToolRegistry()
    report = loader(index, environ={}).load("   ", registry)
    assert report.total == 0


def test_e2_directory_without_yaml_files(tmp_path, index):
    """E2：目录存在但无 .yaml → total=0，正常启动。"""
    (tmp_path / "notes.txt").write_text("not a manifest", encoding="utf-8")
    registry = ToolRegistry()
    report = loader(index, environ={}).load(tmp_path, registry)
    assert report.total == 0
    assert report.path == str(tmp_path)


def test_directory_missing_returns_empty_report(tmp_path, index):
    """§4.1 失败形态：目录不存在返回空报告且不抛异常。"""
    registry = ToolRegistry()
    report = loader(index, environ={}).load(tmp_path / "absent", registry)
    assert report.total == 0
    assert report.loaded == []
    assert report.skipped == []


def test_path_is_file_returns_empty_report(tmp_path, index):
    target = write_manifest(tmp_path, "single.yaml", weather_manifest())
    registry = ToolRegistry()
    report = loader(index, environ={}).load(target, registry)
    assert report.total == 0


def test_registry_unavailable_returns_empty_report(tmp_path, index, monkeypatch):
    monkeypatch.setattr(ext_api, "get_tool_registry", lambda: None)
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    report = loader(index, environ={WEATHER_ENV: WEATHER_SECRET}).load(tmp_path)
    assert report.total == 0


def test_e3_yaml_syntax_error_skips_only_that_file(tmp_path, index, environ):
    """E3：语法错误 → 跳过该文件 + 告警（含文件名）；其他文件继续加载。"""
    write_manifest(tmp_path, "broken.yaml", "tool_id: [unclosed\n  name: x\n")
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    registry = ToolRegistry()
    report = loader(index, environ=environ).load(tmp_path, registry)

    assert report.loaded == [WEATHER_TOOL_ID]
    assert len(report.skipped) == 1
    assert report.skipped[0]["file"] == "broken.yaml"
    assert report.skipped[0]["rule"] == ext_api.RULE_YAML_SYNTAX
    assert registry.get(WEATHER_TOOL_ID) is not None


def test_e3_syntax_error_is_logged_without_aborting(tmp_path, index, environ, caplog):
    write_manifest(tmp_path, "broken.yaml", "tool_id: [unclosed\n")
    with caplog.at_level(logging.WARNING, logger="app.services.tool.ext_api"):
        loader(index, environ=environ).load(tmp_path, ToolRegistry())
    assert "broken.yaml" in caplog.text


def test_empty_manifest_file_is_skipped(tmp_path, index):
    write_manifest(tmp_path, "empty.yaml", "")
    registry = ToolRegistry()
    report = loader(index, environ={}).load(tmp_path, registry)
    assert report.skipped[0]["rule"] == ext_api.RULE_STRUCTURE


def test_rule1_tool_id_prefix(tmp_path, index, environ):
    """八项校验 ①：tool_id 前缀必须为 ext.api.。"""
    payload = weather_manifest(tool_id="api.weather.current")
    _, report = _load_one(tmp_path, payload, index, environ=environ)
    assert _skip_rule(report) == 1
    assert "ext.api." in report.skipped[0]["reason"]


def test_rule1_tool_id_format(tmp_path, index, environ):
    """八项校验 ①：tool_id 必须符合点分命名空间格式。"""
    payload = weather_manifest(tool_id="ext.api.Weather-Current")
    _, report = _load_one(tmp_path, payload, index, environ=environ)
    assert _skip_rule(report) == 1
    assert "格式" in report.skipped[0]["reason"]


def test_rule1_tool_id_missing(tmp_path, index, environ):
    payload = weather_manifest()
    payload.pop("tool_id")
    _, report = _load_one(tmp_path, payload, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE


def test_rule2_requires_https(tmp_path, index, environ):
    """八项校验 ②：http.url 必须为 https。"""
    payload = weather_manifest(
        http={**weather_manifest()["http"], "url": "http://api.example.com/v1/weather"}
    )
    _, report = _load_one(tmp_path, payload, index, environ=environ)
    assert _skip_rule(report) == 2
    assert "https" in report.skipped[0]["reason"]


def test_rule2_host_must_be_allowlisted(tmp_path, index, environ):
    """八项校验 ②：host 必须在 v24_tool_ext_allowed_hosts 内。"""
    payload = weather_manifest(
        http={**weather_manifest()["http"], "url": "https://evil.example.org/v1"}
    )
    _, report = _load_one(tmp_path, payload, index, environ=environ)
    assert _skip_rule(report) == 2
    assert "evil.example.org" in report.skipped[0]["reason"]


def test_rule2_empty_whitelist_blocks_everything(tmp_path, index, environ):
    """AC：白名单为空时全禁（0 条加载）。"""
    settings = ext_settings(v24_tool_ext_allowed_hosts="")
    registry = ToolRegistry()
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    write_manifest(tmp_path, "hook.yaml", hook_manifest())
    report = loader(index, settings, environ).load(tmp_path, registry)

    assert report.loaded == []
    assert [item["rule"] for item in report.skipped] == [2, 2]
    assert registry.list() == []


def test_rule3_method_whitelist(tmp_path, index, environ):
    """八项校验 ③：http.method 只允许 GET / POST。"""
    payload = weather_manifest(
        http={**weather_manifest()["http"], "method": "DELETE"}
    )
    _, report = _load_one(tmp_path, payload, index, environ=environ)
    assert _skip_rule(report) == 3
    assert "GET, POST" in report.skipped[0]["reason"]


def test_rule3_method_is_case_insensitive(tmp_path, index, environ):
    payload = weather_manifest(http={**weather_manifest()["http"], "method": "get"})
    registry, report = _load_one(tmp_path, payload, index, environ=environ)
    assert report.loaded == [WEATHER_TOOL_ID]


def test_rule4_env_reference_missing(tmp_path, index):
    """八项校验 ④ / E4：引用的环境变量不存在 → 跳过 + 告警（只记变量名）。"""
    _, report = _load_one(tmp_path, weather_manifest(), index, environ={})
    assert _skip_rule(report) == 4
    assert WEATHER_ENV in report.skipped[0]["reason"]


def test_rule4_auth_type_must_be_known(tmp_path, index):
    body = weather_manifest()
    body["http"] = {**body["http"], "auth": {"type": "magic", "env": WEATHER_ENV}}
    _, report = _load_one(tmp_path, body, index, environ={WEATHER_ENV: WEATHER_SECRET})
    assert _skip_rule(report) == 4


def test_rule4_header_type_requires_header_name(tmp_path, index):
    body = weather_manifest()
    body["http"] = {**body["http"], "auth": {"type": "header", "env": WEATHER_ENV}}
    _, report = _load_one(tmp_path, body, index, environ={WEATHER_ENV: WEATHER_SECRET})
    assert _skip_rule(report) == 4


def test_rule4_auth_is_optional(tmp_path, index):
    body = weather_manifest()
    body["http"] = {key: value for key, value in body["http"].items() if key != "auth"}
    registry, report = _load_one(tmp_path, body, index, environ={})
    assert report.loaded == [WEATHER_TOOL_ID]


def test_rule5_expression_subset_rejects_function(tmp_path, index, environ):
    """八项校验 ⑤：函数调用超出子集。"""
    body = weather_manifest(response_map={"weather.condition": "$.len($.data.items)"})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 5
    assert "子集" in report.skipped[0]["reason"]


@pytest.mark.parametrize(
    "expression",
    [
        "$.data.temp + 1",
        "$.data.flag ? 1 : 2",
        "$.items[*].name",
        "$.data.temp:float",
        "$.data.temp:num:str",
        "$.data.temp | str",
        "$",
    ],
)
def test_rule5_subset_rejects_out_of_scope_expressions(tmp_path, index, environ, expression):
    body = weather_manifest(response_map={"weather.temperature": expression})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 5


@pytest.mark.parametrize(
    "expression",
    ["$.data.temp", "$.items[0].name", "$.data.temp:num", "$.a.b.c:str", "$.ok:bool"],
)
def test_rule5_subset_accepts_supported_expressions(tmp_path, index, environ, expression):
    body = weather_manifest(response_map={"weather.temperature": expression})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert report.loaded == [WEATHER_TOOL_ID]


def test_rule5_expression_to_key_direction_is_supported(tmp_path, index, environ):
    """TOOL-011 §2.2「表达式 → observations 键」与 architecture §10.2 的键值方向都收。"""
    body = weather_manifest(response_map={"$.data.condition": "weather.condition"})
    registry, report = _load_one(tmp_path, body, index, environ=environ)
    assert report.loaded == [WEATHER_TOOL_ID]
    assert registry.get(WEATHER_TOOL_ID) is not None
    assert index.get(WEATHER_TOOL_ID).response_map == {
        "weather.condition": "$.data.condition"
    }


def test_rule5_missing_response_map(tmp_path, index, environ):
    body = weather_manifest()
    body.pop("response_map")
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 5


def test_rule5_rejects_invalid_observation_key(tmp_path, index, environ):
    body = weather_manifest(response_map={"Weather-Condition": "$.data.condition"})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 5


def test_rule6_level_must_be_at_least_sensitive(tmp_path, index, environ):
    """八项校验 ⑥：level 不得低于 sensitive。"""
    body = weather_manifest(permission={"level": "normal", "confirm": "first_time"})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 6
    assert "sensitive" in report.skipped[0]["reason"]


def test_rule6_confirm_never_is_rejected(tmp_path, index, environ):
    body = weather_manifest(permission={"level": "sensitive", "confirm": "never"})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 6


def test_rule6_dangerous_level_is_accepted(tmp_path, index, environ):
    body = weather_manifest(
        permission={"level": "dangerous", "confirm": "always"}
    )
    registry, report = _load_one(tmp_path, body, index, environ=environ)
    assert report.loaded == [WEATHER_TOOL_ID]
    assert registry.get(WEATHER_TOOL_ID).permission.level == "dangerous"


def test_rule6_scope_defaults_to_declared_host(tmp_path, index, environ):
    body = weather_manifest(permission={"level": "sensitive"})
    registry, _ = _load_one(tmp_path, body, index, environ=environ)
    assert registry.get(WEATHER_TOOL_ID).permission.scope == (f"external:{WEATHER_HOST}",)


def test_e16_irreversible_side_effect_is_rejected(tmp_path, index, environ):
    """E16：side_effects 含 irreversible → 校验 ⑦ 拒绝。"""
    body = weather_manifest(side_effects=["read", "irreversible"])
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 7
    assert "irreversible" in report.skipped[0]["reason"]


def test_rule7_unknown_side_effect_is_rejected(tmp_path, index, environ):
    body = weather_manifest(side_effects=["read", "ghost"])
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 7


def test_rule7_side_effects_required(tmp_path, index, environ):
    body = weather_manifest()
    body.pop("side_effects")
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 7


def test_rule8_name_budget(tmp_path, index, environ):
    """八项校验 ⑧：name 长度预算（≤ 20 字）。"""
    body = weather_manifest(name="查" * 21)
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 8
    assert "name" in report.skipped[0]["reason"]


def test_rule8_description_budget(tmp_path, index, environ):
    body = weather_manifest(description="查" * 121)
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == 8
    assert "description" in report.skipped[0]["reason"]


def test_structure_rejects_unknown_keys(tmp_path, index, environ):
    body = weather_manifest(code="os.system('rm -rf /')")
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE


def test_structure_requires_fixed_capability_and_action(tmp_path, index, environ):
    body = weather_manifest(capability="world_action")
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE


def test_rule1_duplicate_tool_id_in_two_files_keeps_first(tmp_path, index, environ):
    """E15：同 tool_id 多文件重复 → 首条注册成功，后续跳过 + 告警（不覆盖）。"""
    first = weather_manifest(name="首条")
    second = weather_manifest(name="后条")
    registry = ToolRegistry()
    write_manifest(tmp_path, "a_first.yaml", first)
    write_manifest(tmp_path, "b_second.yaml", second)
    report = loader(index, environ=environ).load(tmp_path, registry)

    assert report.loaded == [WEATHER_TOOL_ID]
    assert report.skipped[0]["rule"] == 1
    assert "重复" in report.skipped[0]["reason"]
    assert registry.get(WEATHER_TOOL_ID).name == "首条"


def test_duplicate_signature_is_rejected(tmp_path, index, environ):
    """参数签名重复会导致执行期无法确定性路由 → 装载期拒绝（校验 1）。"""
    registry = ToolRegistry()
    write_manifest(tmp_path, "a.yaml", weather_manifest())
    write_manifest(
        tmp_path,
        "b.yaml",
        weather_manifest(tool_id="ext.api.weather.today", name="今日天气"),
    )
    report = loader(index, environ=environ).load(tmp_path, registry)
    assert report.loaded == [WEATHER_TOOL_ID]
    assert report.skipped[0]["rule"] == 1
    assert "参数签名" in report.skipped[0]["reason"]


def test_loader_never_raises_on_broken_input(tmp_path, index, environ):
    """纪律：逐条跳过、不抛异常、不阻塞启动。"""
    write_manifest(tmp_path, "list.yaml", "- a\n- b\n")
    write_manifest(tmp_path, "scalar.yaml", "just-a-string\n")
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    registry = ToolRegistry()
    report = loader(index, environ=environ).load(tmp_path, registry)
    assert report.loaded == [WEATHER_TOOL_ID]
    assert {item["rule"] for item in report.skipped} == {ext_api.RULE_STRUCTURE}


def test_logs_never_contain_credential_value(tmp_path, index, caplog):
    """AC：日志中凭据值不可见（只允许出现变量名 / 域名等非机密信息）。"""
    body = weather_manifest(
        http={**weather_manifest()["http"], "url": "https://evil.example.org/v1"}
    )
    handler = CapturingHandler()
    logger = logging.getLogger("app.services.tool.ext_api")
    logger.addHandler(handler)
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.tool.ext_api"):
            _load_one(tmp_path, body, index, environ={WEATHER_ENV: WEATHER_SECRET})
    finally:
        logger.removeHandler(handler)

    assert handler.text(), "白名单外清单必须留下告警"
    assert_no_secret(caplog.text)
    assert_no_secret(handler.text())
    assert "evil.example.org" in handler.text()


def test_yaml_unavailable_degrades_without_crashing(tmp_path, index, monkeypatch):
    """守卫式导入：PyYAML 缺失 → 跳过加载并告警，不崩。"""
    monkeypatch.setattr(ext_api, "_load_yaml", lambda: None)
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    registry = ToolRegistry()
    report = loader(index, environ={WEATHER_ENV: WEATHER_SECRET}).load(tmp_path, registry)
    assert report.loaded == []
    assert report.skipped[0]["rule"] == ext_api.RULE_YAML_UNAVAILABLE
    assert registry.list() == []


def test_loader_records_last_report(tmp_path, index, environ):
    tool_loader = loader(index, environ=environ)
    write_manifest(tmp_path, "weather.yaml", weather_manifest())
    tool_loader.load(tmp_path, ToolRegistry())
    assert tool_loader.last_report().loaded == [WEATHER_TOOL_ID]


def test_manifest_public_view_has_no_credential_value(tmp_path, environ):
    _, loaded_index, report = load_manifests(
        tmp_path, manifests={"weather.yaml": weather_manifest()}, environ=environ
    )
    assert report.loaded == [WEATHER_TOOL_ID]
    view = loaded_index.get(WEATHER_TOOL_ID).public_view()
    assert_no_secret(str(view))
    assert view["auth"] == {
        "type": "bearer",
        "env": WEATHER_ENV,
        "header": "",
        "configured": True,
    }


def test_timeout_is_capped_at_ten_seconds(tmp_path, index, environ):
    body = weather_manifest()
    body["http"] = {**body["http"], "timeout_seconds": 60}
    registry, _ = _load_one(tmp_path, body, index, environ=environ)
    assert registry.get(WEATHER_TOOL_ID).timeout_seconds == 10.0


def test_timeout_must_be_positive_number(tmp_path, index, environ):
    body = weather_manifest()
    body["http"] = {**body["http"], "timeout_seconds": 0}
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE


def test_undeclared_placeholder_becomes_required_parameter(tmp_path, index, environ):
    """http.params 里的占位符自动进入 input_schema（strict 校验不会误拒）。"""
    body = weather_manifest()
    body.pop("input_schema")
    registry, _ = _load_one(tmp_path, body, index, environ=environ)
    parameters = registry.get(WEATHER_TOOL_ID).input_schema.parameters
    assert [(item.name, item.required) for item in parameters] == [
        ("host", True),
        ("city", True),
    ]


def test_manifest_cannot_redeclare_host_parameter(tmp_path, index, environ):
    body = weather_manifest(
        input_schema={
            "parameters": [
                {"name": "host", "type": "string", "required": True},
                {"name": "city", "type": "string", "required": True},
            ]
        }
    )
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE


def test_invalid_placeholder_syntax_is_rejected(tmp_path, index, environ):
    body = weather_manifest()
    body["http"] = {**body["http"], "params": {"city": "{params.City}"}}
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE


def test_declared_tags_are_honored_and_extended(tmp_path, index, environ):
    body = weather_manifest(tags=["weather", "external"])
    registry, report = _load_one(tmp_path, body, index, environ=environ)
    assert report.loaded == [WEATHER_TOOL_ID]
    assert registry.get(WEATHER_TOOL_ID).tags == ("external", "api", "weather")


def test_tags_must_be_string_list(tmp_path, index, environ):
    body = weather_manifest(tags={"a": 1})
    _, report = _load_one(tmp_path, body, index, environ=environ)
    assert _skip_rule(report) == ext_api.RULE_STRUCTURE
